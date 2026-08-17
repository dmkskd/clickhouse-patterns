"""Type-keyed, read-only readers for live Pattern Explorer resources."""
from __future__ import annotations

import io
import os
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
            "create_statement": create_statement, "columns": columns, "sample": sample,
            "sample_error": sample_error, "sample_disabled": sample_disabled,
        }


class MinioReader:
    """List declared S3 prefixes and preview small Parquet or Avro objects."""

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
        return {".parquet": "Parquet", ".avro": "Avro"}.get(suffix, "Unknown")

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


class ReaderRegistry:
    def __init__(self, *readers: ResourceReader):
        self._readers = {kind: reader for reader in readers for kind in reader.kinds}

    def reader_for(self, kind: str) -> ResourceReader | None:
        return self._readers.get(kind)

    @property
    def kinds(self) -> frozenset[str]:
        return frozenset(self._readers)


RESOURCE_READERS = ReaderRegistry(ClickHouseReader(), MinioReader())
