"""Type-keyed, read-only readers for live Pattern Explorer resources."""
from __future__ import annotations

import io
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import PurePosixPath
from typing import Any, Callable, Protocol
from uuid import UUID

from ..catalog.graph import Resource

SAMPLE_LIMIT = 20
OBJECT_LIMIT = 100
OBJECT_PREVIEW_BYTES = 8 * 1024 * 1024



_MV_TARGET = re.compile(
    r"\bTO\s+((?:`[^`]+`|\w+)(?:\.(?:`[^`]+`|\w+))?)",
    re.IGNORECASE,
)


def _materialized_view_target(engine: str, create_statement: str) -> str | None:
    """The table a `TO`-form materialized view writes into.

    A materialized view stores nothing itself: `system.columns` and a `SELECT`
    against the view both resolve to this table, so the browser has to name it
    rather than present those rows as the view's own.
    """
    if engine.lower() != "materializedview":
        return None
    match = _MV_TARGET.search(create_statement or "")
    return match.group(1).replace("`", "") if match else None

class ResourceReader(Protocol):
    """A bounded, read-only browser for one or more graph resource kinds."""

    kinds: frozenset[str]

    def inspect(self, context: "ReaderContext", object_key: str | None = None) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ReaderContext:
    resource: Resource
    session: Any
    source_changed: bool
    # Takes an optional node name; falls back to the session's driver node.
    clickhouse_client: Callable[..., Any]


def json_value(value: Any) -> Any:
    """Convert values to bounded, browser-safe JSON primitives."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value if len(value) <= 500 else f"{value[:497]}…"
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (Decimal, UUID)):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    return str(value)


def quote_identifier(value: str) -> str:
    return f"`{value.replace('`', '``')}`"


class ClickHouseReader:
    """The existing table/view inspector, retained behind the common registry."""

    kinds = frozenset({
        "kafka-table", "mv", "refreshable-mv", "distributed", "mergetree",
        "replicated-mergetree", "keepermap", "remote-table",
    })

    def inspect(self, context: ReaderContext, object_key: str | None = None) -> dict[str, Any]:
        if object_key:
            raise ValueError("ClickHouse table inspection does not accept an object key")
        resource = context.resource
        # `table=` carries the real name when the graph id is something else, as
        # it is when one table is drawn once per replica.
        declared = resource.properties.get("table") or resource.name
        requested_database = None
        requested_table = declared
        if "." in declared:
            requested_database, requested_table = declared.rsplit(".", 1)

        node = resource.properties.get("node")
        try:
            client = context.clickhouse_client(node)
        except KeyError as exc:
            raise ValueError(f"resource declares `node={node}`, which is not a node in this session") from exc
        metadata_query = """
            SELECT database, name, engine, create_table_query
            FROM system.tables
            WHERE name = {table:String}
              AND database NOT IN ('system', 'information_schema', 'INFORMATION_SCHEMA')
        """
        parameters = {"table": requested_table}
        if requested_database:
            metadata_query += " AND database = {database:String}"
            parameters["database"] = requested_database
        metadata_query += " ORDER BY database"
        metadata = client.query(metadata_query, parameters=parameters).result_rows
        if not metadata:
            qualified = f"{requested_database}.{requested_table}" if requested_database else requested_table
            where = f"on node {node}" if node else "in the live ClickHouse session"
            detail = f"{qualified} is not present {where}"
            if context.source_changed:
                detail += "; this pattern changed after the session started—reload it to inspect the newly declared resource"
            raise ValueError(detail)
        if len(metadata) > 1:
            databases = ", ".join(row[0] for row in metadata)
            raise ValueError(f"{requested_table} exists in multiple databases ({databases}); qualify its name in the resource graph")

        database, table, engine, create_statement = metadata[0]
        column_result = client.query(
            """
            SELECT name, type, default_kind, default_expression, comment
            FROM system.columns
            WHERE database = {database:String} AND table = {table:String}
            ORDER BY position
            """,
            parameters={"database": database, "table": table},
        )
        columns = [
            {"name": row[0], "type": row[1], "default_kind": row[2], "default_expression": row[3], "comment": row[4]}
            for row in column_result.result_rows
        ]

        sample = None
        sample_error = None
        sample_disabled = None
        if resource.kind == "kafka-table" or engine.lower() == "kafka":
            sample_disabled = "Live rows are intentionally not read from Kafka-engine tables because a SELECT can consume messages. Inspect the durable destination instead."
        else:
            try:
                result = client.query(f"SELECT * FROM {quote_identifier(database)}.{quote_identifier(table)} LIMIT {SAMPLE_LIMIT}")
                sample = {"columns": list(result.column_names), "rows": [[json_value(value) for value in row] for row in result.result_rows], "limit": SAMPLE_LIMIT}
            except Exception as exc:  # noqa: BLE001 - definition remains useful
                sample_error = f"{type(exc).__name__}: {str(exc).splitlines()[0]}"

        return {
            "type": "clickhouse-table",
            "resource": {"key": resource.key, "kind": resource.kind, "declared_name": resource.name},
            "database": database, "table": table, "engine": engine, "node": node,
            "target": _materialized_view_target(engine, create_statement),
            "create_statement": create_statement, "columns": columns, "sample": sample,
            "sample_error": sample_error, "sample_disabled": sample_disabled,
        }


class DictionaryReader:
    """Read a dictionary's definition, load state, and current contents.

    A dictionary is not in `system.tables` unless it was created inside a
    Dictionary-engine table, so its metadata comes from `system.dictionaries`.
    Its contents are readable as a table, which is the only way to see what a
    `dictGet` in a materialized view or a query would currently resolve to.
    """

    kinds = frozenset({"dictionary"})

    def inspect(self, context: ReaderContext, object_key: str | None = None) -> dict[str, Any]:
        if object_key:
            raise ValueError("Dictionary inspection does not accept an object key")
        resource = context.resource
        declared = resource.properties.get("dictionary") or resource.properties.get("table") or resource.name
        requested_database = None
        requested_name = declared
        if "." in declared:
            requested_database, requested_name = declared.rsplit(".", 1)

        node = resource.properties.get("node")
        try:
            client = context.clickhouse_client(node)
        except KeyError as exc:
            raise ValueError(f"resource declares `node={node}`, which is not a node in this session") from exc

        metadata_query = """
            SELECT database, name, status, type, key.names, key.types,
                   attribute.names, attribute.types, element_count,
                   bytes_allocated, lifetime_min, lifetime_max, source,
                   last_successful_update_time, loading_duration, last_exception
            FROM system.dictionaries
            WHERE name = {name:String}
        """
        parameters = {"name": requested_name}
        if requested_database:
            metadata_query += " AND database = {database:String}"
            parameters["database"] = requested_database
        metadata_query += " ORDER BY database"
        metadata = client.query(metadata_query, parameters=parameters).result_rows
        if not metadata:
            qualified = f"{requested_database}.{requested_name}" if requested_database else requested_name
            where = f"on node {node}" if node else "in the live ClickHouse session"
            detail = f"{qualified} is not present {where}"
            if context.source_changed:
                detail += "; this pattern changed after the session started—reload it to inspect the newly declared resource"
            raise ValueError(detail)
        if len(metadata) > 1:
            databases = ", ".join(row[0] for row in metadata)
            raise ValueError(f"{requested_name} exists in multiple databases ({databases}); qualify its name in the resource graph")

        (
            database, name, status, layout, key_names, key_types,
            attribute_names, attribute_types, element_count, bytes_allocated,
            lifetime_min, lifetime_max, source, last_update, loading_duration,
            last_exception,
        ) = metadata[0]

        qualified = f"{quote_identifier(database)}.{quote_identifier(name)}"
        try:
            create_statement = client.query(f"SHOW CREATE DICTIONARY {qualified}").result_rows[0][0]
        except Exception as exc:  # noqa: BLE001 - load state remains useful
            create_statement = f"-- SHOW CREATE DICTIONARY failed: {type(exc).__name__}: {str(exc).splitlines()[0]}"

        columns = [
            {"name": column, "type": column_type, "role": "key"}
            for column, column_type in zip(key_names, key_types)
        ] + [
            {"name": column, "type": column_type, "role": "attribute"}
            for column, column_type in zip(attribute_names, attribute_types)
        ]

        sample = None
        sample_error = None
        # A dictionary that has never loaded has no contents to read, and
        # selecting from it would trigger the load this inspection is reporting on.
        if status == "NOT_LOADED":
            sample_disabled = "This dictionary has not been loaded yet, so it holds no contents. A dictGet or a SELECT against it triggers its first load."
        else:
            sample_disabled = None
            try:
                result = client.query(f"SELECT * FROM {qualified} LIMIT {SAMPLE_LIMIT}")
                sample = {"columns": list(result.column_names), "rows": [[json_value(value) for value in row] for row in result.result_rows], "limit": SAMPLE_LIMIT}
            except Exception as exc:  # noqa: BLE001 - definition remains useful
                sample_error = f"{type(exc).__name__}: {str(exc).splitlines()[0]}"

        return {
            "type": "clickhouse-dictionary",
            "resource": {"key": resource.key, "kind": resource.kind, "declared_name": resource.name},
            "database": database, "dictionary": name, "node": node,
            "status": status, "layout": layout, "source": source,
            "element_count": json_value(element_count),
            "bytes_allocated": json_value(bytes_allocated),
            "lifetime_min": json_value(lifetime_min), "lifetime_max": json_value(lifetime_max),
            "last_successful_update_time": json_value(last_update),
            "loading_duration": json_value(loading_duration),
            "last_exception": last_exception or None,
            "create_statement": create_statement, "columns": columns, "sample": sample,
            "sample_error": sample_error, "sample_disabled": sample_disabled,
        }


class MinioReader:
    """List declared S3 prefixes and preview small Parquet, Avro, or JSON objects."""

    kinds = frozenset({"minio"})

    def inspect(self, context: ReaderContext, object_key: str | None = None) -> dict[str, Any]:
        resource = context.resource
        bucket = resource.properties.get("bucket")
        if not bucket:
            raise ValueError("MinIO resources need `bucket=<name>` in the graph to be inspected")
        prefix = resource.properties.get("prefix", "")
        if object_key:
            self._validate_object_key(object_key, prefix)
            return self._preview_object(resource, bucket, object_key)
        client = self._client(resource)
        response = client.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=OBJECT_LIMIT)
        objects = [
            {"key": item["Key"], "size": item["Size"], "modified": item["LastModified"].isoformat(), "format": self._format(resource, item["Key"])}
            for item in response.get("Contents", [])
        ]
        return {
            "type": "object-store", "resource": {"key": resource.key, "kind": resource.kind, "declared_name": resource.name},
            "title": resource.properties.get("label") or f"s3://{bucket}/{prefix}",
            "subtitle": f"s3://{bucket}/{prefix}", "bucket": bucket, "prefix": prefix,
            "objects": objects, "object_limit": OBJECT_LIMIT, "truncated": bool(response.get("IsTruncated")),
        }

    def _client(self, resource: Resource):
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - packaging protects this
            raise RuntimeError("MinIO inspection requires the `boto3` package") from exc
        return boto3.client(
            "s3",
            endpoint_url=resource.properties.get("endpoint", "http://127.0.0.1:9010"),
            aws_access_key_id=os.environ.get("CLICKHOUSE_PATTERN_S3_ACCESS_KEY", "clickhouse"),
            aws_secret_access_key=os.environ.get("CLICKHOUSE_PATTERN_S3_SECRET_KEY", "clickhouse_secret"),
            region_name=resource.properties.get("region", "us-east-1"),
        )

    def _validate_object_key(self, object_key: str, prefix: str) -> None:
        path = PurePosixPath(object_key)
        if object_key.startswith("/") or ".." in path.parts or not object_key.startswith(prefix):
            raise ValueError("object is outside this resource's declared prefix")

    def _format(self, resource: Resource, object_key: str) -> str:
        configured = resource.properties.get("format")
        if configured:
            return configured
        suffix = PurePosixPath(object_key).suffix.lower()
        return {".parquet": "Parquet", ".avro": "Avro", ".json": "JSON"}.get(suffix, "Unknown")

    def _preview_object(self, resource: Resource, bucket: str, object_key: str) -> dict[str, Any]:
        client = self._client(resource)
        head = client.head_object(Bucket=bucket, Key=object_key)
        size = int(head["ContentLength"])
        if size > OBJECT_PREVIEW_BYTES:
            return {"type": "object-preview", "title": object_key, "subtitle": self._format(resource, object_key), "object": {"key": object_key, "size": size}, "sample_disabled": f"Preview is limited to objects no larger than {OBJECT_PREVIEW_BYTES // (1024 * 1024)} MiB."}
        payload = client.get_object(Bucket=bucket, Key=object_key)["Body"].read(OBJECT_PREVIEW_BYTES + 1)
        if len(payload) > OBJECT_PREVIEW_BYTES:
            raise ValueError("object exceeded the preview limit while reading")
        format_name = self._format(resource, object_key)
        if format_name.lower() == "json":
            # Documents such as Iceberg table metadata are nested, not tabular,
            # so they are shown as indented text instead of a sample table.
            try:
                text, error = json.dumps(json.loads(payload), indent=2), None
            except ValueError as exc:
                text, error = None, f"{type(exc).__name__}: {str(exc).splitlines()[0]}"
            return {"type": "object-preview", "title": object_key, "subtitle": format_name, "object": {"key": object_key, "size": size}, "text": text, "sample": None, "sample_error": error}
        try:
            columns, rows = self._decode(format_name, payload)
            sample = {"columns": columns, "rows": rows, "limit": SAMPLE_LIMIT}
            error = None
        except Exception as exc:  # noqa: BLE001 - object metadata still helps
            sample = None
            error = f"{type(exc).__name__}: {str(exc).splitlines()[0]}"
        return {"type": "object-preview", "title": object_key, "subtitle": format_name, "object": {"key": object_key, "size": size}, "sample": sample, "sample_error": error}

    def _decode(self, format_name: str, payload: bytes) -> tuple[list[str], list[list[Any]]]:
        if format_name.lower() == "parquet":
            import pyarrow.parquet as parquet
            table = parquet.read_table(io.BytesIO(payload)).slice(0, SAMPLE_LIMIT)
            return list(table.column_names), [[json_value(value) for value in row.values()] for row in table.to_pylist()]
        if format_name.lower() == "avro":
            from fastavro import reader
            rows = list(reader(io.BytesIO(payload)))[:SAMPLE_LIMIT]
            columns = list(rows[0]) if rows else []
            return columns, [[json_value(row.get(column)) for column in columns] for row in rows]
        raise ValueError(f"No reader is registered for {format_name} objects")


class SourceDatabaseReader:
    """Shared reader for source OLTP databases (Postgres, MySQL).

    A graph resource names its tables with `table=`, `tables=`, or its label,
    several joined by `+` (`public.orders + public.orders_existing`). For each
    table the reader returns a definition, its columns, and up to
    SAMPLE_LIMIT rows. A subclass supplies the database-specific hooks:
    `connect`, `subtitle`, `describe`, and `quote`.
    """

    kinds: frozenset[str] = frozenset()
    system = ""
    default_schema = ""
    _NAME = re.compile(r"^[A-Za-z_][\w$]*(\.[A-Za-z_][\w$]*)?$")

    def connect(self, resource: Resource): ...
    def subtitle(self, conn) -> str: ...
    def describe(self, conn, schema: str, table: str) -> tuple[str, list[dict[str, str]]]: ...
    def quote(self, schema: str, table: str) -> str: ...

    def schema_for(self, resource: Resource) -> str:
        """Schema an unqualified table name resolves to."""
        return self.default_schema

    def inspect(self, context: ReaderContext, object_key: str | None = None) -> dict[str, Any]:
        if object_key:
            raise ValueError(f"{self.system} table inspection does not accept an object key")
        resource = context.resource
        declared = (resource.properties.get("table") or resource.properties.get("tables")
                    or resource.properties.get("label") or resource.name)
        names = [part.strip() for part in declared.split("+") if part.strip()]
        if not names or not all(self._NAME.match(name) for name in names):
            raise ValueError(
                f"{self.system} resources need `tables=<schema.table>` (several joined by `+`) to be inspected"
            )
        default_schema = self.schema_for(resource)
        conn = self.connect(resource)
        try:
            subtitle = self.subtitle(conn)
            tables = []
            for name in names:
                schema, table = name.split(".", 1) if "." in name else (default_schema, name)
                create_statement, columns = self.describe(conn, schema, table)
                tables.append({
                    "schema": schema, "table": table, "create_statement": create_statement,
                    "columns": columns, **self._sample(conn, schema, table),
                })
        finally:
            conn.close()
        return {
            "type": "database-tables", "system": self.system,
            "resource": {"key": resource.key, "kind": resource.kind, "declared_name": resource.name},
            "title": " + ".join(f"{t['schema']}.{t['table']}" for t in tables),
            "subtitle": subtitle, "tables": tables,
        }

    def _sample(self, conn, schema: str, table: str) -> dict[str, Any]:
        try:
            cursor = conn.cursor()
            cursor.execute(f"SELECT * FROM {self.quote(schema, table)} LIMIT {SAMPLE_LIMIT}")
            return {"sample": {
                "columns": [column[0] for column in cursor.description],
                "rows": [[json_value(value) for value in row] for row in cursor.fetchall()],
                "limit": SAMPLE_LIMIT,
            }, "sample_error": None}
        except Exception as exc:  # noqa: BLE001 - definition remains useful
            return {"sample": None, "sample_error": f"{type(exc).__name__}: {str(exc).splitlines()[0]}"}

    @staticmethod
    def _query(conn, sql: str, params: tuple = ()) -> list[tuple]:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        return cursor.fetchall()


class PostgresReader(SourceDatabaseReader):
    """Postgres has no SHOW CREATE TABLE, so the definition is reconstructed
    from the catalog: columns, defaults, NOT NULL, constraints, and replica
    identity."""

    kinds = frozenset({"postgres"})
    system = "Postgres"
    default_schema = "public"

    def connect(self, resource: Resource):
        import psycopg
        return psycopg.connect(
            host=resource.properties.get("host", "localhost"),
            port=int(resource.properties.get("port", 5432)),
            user=os.environ.get("CLICKHOUSE_PATTERN_PG_USER", "postgres"),
            password=os.environ.get("CLICKHOUSE_PATTERN_PG_PASSWORD", "postgres"),
            dbname=resource.properties.get("database", "test"),
            autocommit=True,
            connect_timeout=3,
        )

    def subtitle(self, conn) -> str:
        return f"Postgres · wal_level = {self._query(conn, 'SHOW wal_level')[0][0]}"

    def quote(self, schema: str, table: str) -> str:
        return ".".join('"' + part.replace('"', '""') + '"' for part in (schema, table))

    def describe(self, conn, schema: str, table: str):
        meta = self._query(conn, """
            SELECT c.oid, c.relreplident
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = %s AND c.relname = %s
        """, (schema, table))
        if not meta:
            raise ValueError(f"{schema}.{table} is not present in the live Postgres session")
        oid, replident = meta[0]
        column_rows = self._query(conn, """
            SELECT a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull,
                   pg_get_expr(d.adbin, d.adrelid)
            FROM pg_attribute a
            LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
            WHERE a.attrelid = %s AND a.attnum > 0 AND NOT a.attisdropped
            ORDER BY a.attnum
        """, (oid,))
        constraints = [row[0] for row in self._query(
            conn, "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = %s ORDER BY contype", (oid,)
        )]
        lines = [
            f"    {name} {column_type}{' NOT NULL' if not_null else ''}{f' DEFAULT {default}' if default else ''}"
            for name, column_type, not_null, default in column_rows
        ] + [f"    {constraint}" for constraint in constraints]
        identity = {"d": "DEFAULT", "f": "FULL", "i": "USING INDEX", "n": "NOTHING"}.get(replident, replident)
        create_statement = (f"CREATE TABLE {schema}.{table} (\n" + ",\n".join(lines)
                            + f"\n);\n-- REPLICA IDENTITY {identity}")
        columns = [{"name": name, "type": column_type, "default": default or ""}
                   for name, column_type, _not_null, default in column_rows]
        return create_statement, columns


class MySQLReader(SourceDatabaseReader):
    """MySQL returns its own definition through SHOW CREATE TABLE."""

    kinds = frozenset({"mysql"})
    system = "MySQL"
    default_schema = "test"

    def connect(self, resource: Resource):
        import pymysql
        return pymysql.connect(
            host=resource.properties.get("host", "127.0.0.1"),
            port=int(resource.properties.get("port", 3306)),
            user=os.environ.get("CLICKHOUSE_PATTERN_MYSQL_USER", "root"),
            password=os.environ.get("CLICKHOUSE_PATTERN_MYSQL_PASSWORD", "root"),
            database=resource.properties.get("database", "test"),
            connect_timeout=3,
        )

    def schema_for(self, resource: Resource) -> str:
        # A MySQL database is the schema, so the connection's database qualifies bare names.
        return resource.properties.get("database", self.default_schema)

    def subtitle(self, conn) -> str:
        binlog_format, row_image = self._query(conn, "SELECT @@binlog_format, @@binlog_row_image")[0]
        return f"MySQL · binlog_format = {binlog_format} · binlog_row_image = {row_image}"

    def quote(self, schema: str, table: str) -> str:
        return ".".join("`" + part.replace("`", "``") + "`" for part in (schema, table))

    def describe(self, conn, schema: str, table: str):
        column_rows = self._query(conn, """
            SELECT COLUMN_NAME, COLUMN_TYPE, COLUMN_DEFAULT
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
            ORDER BY ORDINAL_POSITION
        """, (schema, table))
        if not column_rows:
            raise ValueError(f"{schema}.{table} is not present in the live MySQL session")
        create_statement = self._query(conn, f"SHOW CREATE TABLE {self.quote(schema, table)}")[0][1]
        columns = [{"name": name, "type": column_type, "default": "" if default is None else str(default)}
                   for name, column_type, default in column_rows]
        return create_statement, columns

class KafkaTopicReader:
    """Read a topic's partition offsets and its most recent messages.

    Partitions are assigned directly and read from `high - SAMPLE_LIMIT`, with
    no consumer group membership and no offset commits, so inspection leaves
    every real consumer's position (Kafka engine, sink connectors) untouched.
    """

    kinds = frozenset({"topic"})

    def inspect(self, context: ReaderContext, object_key: str | None = None) -> dict[str, Any]:
        if object_key:
            raise ValueError("Kafka topic inspection does not accept an object key")
        from confluent_kafka import Consumer, TopicPartition

        resource = context.resource
        topic = resource.properties.get("topic") or resource.properties.get("label") or resource.name
        consumer = Consumer({
            "bootstrap.servers": resource.properties.get("bootstrap", "localhost:9092"),
            "group.id": "pattern-explorer-inspect",
            "enable.auto.commit": False,
            "socket.timeout.ms": 3000,
        })
        try:
            metadata = consumer.list_topics(topic, timeout=5).topics.get(topic)
            if metadata is None or metadata.error is not None or not metadata.partitions:
                raise ValueError(f"topic {topic} is not present in the live Kafka session")
            partitions = []
            assignment = []
            for partition in sorted(metadata.partitions):
                low, high = consumer.get_watermark_offsets(TopicPartition(topic, partition), timeout=5)
                partitions.append({"partition": partition, "low": low, "high": high, "messages": high - low})
                if high > low:
                    assignment.append(TopicPartition(topic, partition, max(low, high - SAMPLE_LIMIT)))
            expected = sum(min(SAMPLE_LIMIT, item["messages"]) for item in partitions)
            messages = []
            if assignment:
                consumer.assign(assignment)
                deadline = time.monotonic() + 5
                while len(messages) < expected and time.monotonic() < deadline:
                    message = consumer.poll(0.5)
                    if message is None or message.error():
                        continue
                    messages.append(message)
        finally:
            consumer.close()
        messages.sort(key=lambda message: (message.timestamp()[1], message.partition(), message.offset()), reverse=True)
        rows = [
            [
                message.partition(), message.offset(),
                datetime.fromtimestamp(message.timestamp()[1] / 1000).isoformat(timespec="milliseconds")
                if message.timestamp()[1] > 0 else "",
                json_value(self._decode(message.key())), json_value(self._decode(message.value())),
            ]
            for message in messages[:SAMPLE_LIMIT]
        ]
        return {
            "type": "kafka-topic",
            "resource": {"key": resource.key, "kind": resource.kind, "declared_name": resource.name},
            "title": topic,
            "subtitle": f"Kafka · {len(partitions)} partition{'s' if len(partitions) != 1 else ''} · "
                        f"{sum(item['messages'] for item in partitions)} messages retained",
            "partitions": partitions,
            "sample": {"columns": ["partition", "offset", "timestamp", "key", "value"], "rows": rows, "limit": SAMPLE_LIMIT},
        }

    @staticmethod
    def _decode(payload: bytes | None) -> str | None:
        """Bytes as compact JSON when they parse, else as UTF-8 text, else hex."""
        if payload is None:
            return None
        try:
            text = payload.decode()
        except UnicodeDecodeError:
            return payload.hex()
        try:
            return json.dumps(json.loads(text), separators=(", ", ": "))
        except ValueError:
            return text

class ReaderRegistry:
    def __init__(self, *readers: ResourceReader):
        self._readers = {kind: reader for reader in readers for kind in reader.kinds}

    def reader_for(self, kind: str) -> ResourceReader | None:
        return self._readers.get(kind)

    @property
    def kinds(self) -> frozenset[str]:
        return frozenset(self._readers)


RESOURCE_READERS = ReaderRegistry(ClickHouseReader(), DictionaryReader(), MinioReader(), PostgresReader(), MySQLReader(), KafkaTopicReader())
