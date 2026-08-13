import json
import threading
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from pattern_explorer.server.explorer import ExplorerConflict, ExplorerController, create_server
from pattern_explorer.server.resource_readers import MinioReader, ReaderContext, RESOURCE_READERS
from pattern_explorer.catalog.graph import Resource


@pytest.fixture
def explorer_server(tmp_path):
    server = create_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def get_json(url):
    with urlopen(url) as response:
        return json.loads(response.read())


def test_server_serves_catalog_and_interactive_configuration(explorer_server):
    _server, base = explorer_server

    with urlopen(f"{base}/") as response:
        page = response.read().decode()
        cache_control = response.headers["Cache-Control"]
    config = get_json(f"{base}/api/config")
    revision = get_json(f"{base}/api/revision")
    catalog = get_json(f"{base}/api/patterns")
    with urlopen(f"{base}/catalog.js") as response:
        browser_catalog = response.read().decode()

    assert "ClickHouse Pattern Explorer" in page
    assert cache_control == "no-store"
    assert config["interactive"] is True
    assert config["token"]
    assert len(revision["revision"]) == 64
    assert any(item["slug"] == "kafka-ingest-replicated" for item in catalog["patterns"])
    assert "window.CLICKHOUSE_PATTERN_CATALOG" in browser_catalog
    assert "kafka-ingest-replicated" in browser_catalog


def test_mutations_require_token_and_return_accepted(explorer_server, monkeypatch):
    server, base = explorer_server
    operation = {"name": "run", "pattern": "demo", "status": "running"}
    monkeypatch.setattr(server.controller, "run", lambda slug: operation)
    body = json.dumps({"pattern": "demo"}).encode()

    with pytest.raises(HTTPError) as forbidden:
        urlopen(Request(f"{base}/api/session/run", data=body, method="POST"))
    assert forbidden.value.code == 403

    request = Request(f"{base}/api/session/run", data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    request.add_header("X-Explorer-Token", server.token)
    with urlopen(request) as response:
        payload = json.loads(response.read())

    assert response.status == 202
    assert payload["operation"] == operation


def test_switch_endpoint_returns_one_accepted_operation(explorer_server, monkeypatch):
    server, base = explorer_server
    operation = {"name": "switch", "pattern": "target", "status": "running"}
    monkeypatch.setattr(server.controller, "switch", lambda slug: operation)
    body = json.dumps({"pattern": "target"}).encode()

    request = Request(f"{base}/api/session/switch", data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    request.add_header("X-Explorer-Token", server.token)
    with urlopen(request) as response:
        payload = json.loads(response.read())

    assert response.status == 202
    assert payload["operation"] == operation


def test_terminal_owned_session_cannot_be_stopped_from_browser(
    explorer_server, monkeypatch
):
    server, _base = explorer_server
    monkeypatch.setattr(
        "pattern_explorer.server.explorer.sessions.read_session",
        lambda required=False: SimpleNamespace(slug="demo", owner="terminal"),
    )

    with pytest.raises(ExplorerConflict, match="owned by `just run`"):
        server.controller.stop()


def test_switch_stops_then_runs_as_one_operation(monkeypatch):
    controller = ExplorerController()
    active = SimpleNamespace(slug="current", owner="browser")
    target = SimpleNamespace(slug="target", require_runnable=lambda: None)
    calls = []

    monkeypatch.setattr(
        "pattern_explorer.server.explorer.sessions.read_session",
        lambda required=False: active,
    )
    monkeypatch.setattr(
        "pattern_explorer.server.explorer.load_pattern", lambda slug: target
    )
    monkeypatch.setattr(
        "pattern_explorer.server.explorer.stop_session",
        lambda report=None: calls.append("stop"),
    )
    monkeypatch.setattr(
        "pattern_explorer.server.explorer.run_session",
        lambda pattern, report=None: calls.append(("run", pattern.slug)),
    )

    def run_synchronously(name, slug, action):
        action()
        return {"name": name, "pattern": slug, "status": "running"}

    monkeypatch.setattr(controller, "_start_operation", run_synchronously)

    operation = controller.switch("target")

    assert operation == {"name": "switch", "pattern": "target", "status": "running"}
    assert calls == ["stop", ("run", "target")]


def test_snapshot_only_returns_events_from_the_current_operation(monkeypatch):
    controller = ExplorerController()
    reachability_probes = []
    monkeypatch.setattr(
        "pattern_explorer.server.explorer.get_session_status",
        lambda *, probe_reachability=True: reachability_probes.append(
            probe_reachability
        ) or None,
    )
    controller.events.publish("progress", {"message": "old run"}, "demo")
    controller._operation = {
        "name": "run",
        "pattern": "demo",
        "status": "running",
        "event_sequence": controller.events.next_sequence(),
    }
    controller.events.publish("operation", controller._operation, "demo")
    controller.events.publish("progress", {"message": "new run"}, "demo")

    snapshot = controller.snapshot()

    assert [event["payload"].get("message") for event in snapshot["events"]] == [
        None,
        "new run",
    ]
    assert reachability_probes == [False]


class FakeQueryResult:
    def __init__(self, rows, columns=()):
        self.result_rows = rows
        self.column_names = columns


class FakeClickHouseClient:
    def __init__(self, engine="ReplacingMergeTree"):
        self.engine = engine
        self.queries = []

    def query(self, sql, parameters=None):
        self.queries.append((sql, parameters))
        if "FROM system.tables" in sql:
            return FakeQueryResult(
                [("test", "orders", self.engine, f"CREATE TABLE test.orders ENGINE = {self.engine}")]
            )
        if "FROM system.columns" in sql:
            return FakeQueryResult(
                [("id", "Int32", "", "", ""), ("customer", "String", "", "", "")]
            )
        return FakeQueryResult([(1, "alice")], ("id", "customer"))


def test_resource_inspection_returns_definition_and_bounded_live_sample(monkeypatch):
    controller = ExplorerController()
    session = SimpleNamespace(slug="demo", driver_node="ch")
    client = FakeClickHouseClient()
    monkeypatch.setattr(
        "pattern_explorer.server.explorer.get_session_status",
        lambda: SimpleNamespace(session=session, reachable=True),
    )
    monkeypatch.setattr(
        "pattern_explorer.server.explorer.sessions.load_session_pattern",
        lambda _session: SimpleNamespace(graph="query:\n  client -> mergetree:orders"),
    )
    monkeypatch.setattr("pattern_explorer.server.explorer.connect", lambda _node: client)

    result = controller.inspect_resource("demo", "mergetree:orders")

    assert result["type"] == "clickhouse-table"
    assert result["engine"] == "ReplacingMergeTree"
    assert result["columns"][0] == {
        "name": "id",
        "type": "Int32",
        "default_kind": "",
        "default_expression": "",
        "comment": "",
    }
    assert result["sample"]["rows"] == [[1, "alice"]]
    assert "LIMIT 20" in client.queries[-1][0]


def test_reader_registry_registers_clickhouse_and_minio():
    assert RESOURCE_READERS.reader_for("mergetree") is not None
    assert RESOURCE_READERS.reader_for("minio") is not None
    assert RESOURCE_READERS.reader_for("topic") is None


def test_minio_reader_lists_only_the_declared_prefix(monkeypatch):
    class FakeS3:
        def list_objects_v2(self, **kwargs):
            assert kwargs == {"Bucket": "clickhouse", "Prefix": "events/", "MaxKeys": 100}
            return {"Contents": [{"Key": "events/batch-1.parquet", "Size": 42, "LastModified": __import__("datetime").datetime(2026, 8, 13)}]}

    reader = MinioReader()
    monkeypatch.setattr(reader, "_client", lambda _resource: FakeS3())
    resource = Resource(
        key="minio:files", kind="minio", name="files",
        properties={"bucket": "clickhouse", "prefix": "events/", "format": "Parquet"},
    )

    result = reader.inspect(ReaderContext(resource, None, False, lambda: None))

    assert result["type"] == "object-store"
    assert result["objects"] == [{"key": "events/batch-1.parquet", "size": 42, "modified": "2026-08-13T00:00:00", "format": "Parquet"}]


def test_minio_reader_refuses_object_outside_declared_prefix(monkeypatch):
    reader = MinioReader()
    resource = Resource(
        key="minio:files", kind="minio", name="files",
        properties={"bucket": "clickhouse", "prefix": "events/"},
    )

    with pytest.raises(ValueError, match="outside"):
        reader.inspect(ReaderContext(resource, None, False, lambda: None), "other/data.parquet")


def test_resource_inspection_never_selects_from_kafka_engine(monkeypatch):
    controller = ExplorerController()
    session = SimpleNamespace(slug="demo", driver_node="ch")
    client = FakeClickHouseClient(engine="Kafka")
    monkeypatch.setattr(
        "pattern_explorer.server.explorer.get_session_status",
        lambda: SimpleNamespace(session=session, reachable=True),
    )
    monkeypatch.setattr(
        "pattern_explorer.server.explorer.sessions.load_session_pattern",
        lambda _session: SimpleNamespace(graph="ingestion:\n  topic:events -> kafka-table:orders"),
    )
    monkeypatch.setattr("pattern_explorer.server.explorer.connect", lambda _node: client)

    result = controller.inspect_resource("demo", "kafka-table:orders")

    assert result["sample"] is None
    assert "consume messages" in result["sample_disabled"]
    assert len(client.queries) == 2


def test_resource_inspection_explains_source_drift_for_missing_table(monkeypatch):
    controller = ExplorerController()
    session = SimpleNamespace(slug="demo", driver_node="ch")
    client = FakeClickHouseClient()
    client.query = lambda _sql, parameters=None: FakeQueryResult([])
    monkeypatch.setattr(
        "pattern_explorer.server.explorer.get_session_status",
        lambda: SimpleNamespace(
            session=session, reachable=True, source_changed=True
        ),
    )
    monkeypatch.setattr(
        "pattern_explorer.server.explorer.sessions.load_session_pattern",
        lambda _session: SimpleNamespace(graph="query:\n  client -> mergetree:new_orders"),
    )
    monkeypatch.setattr("pattern_explorer.server.explorer.connect", lambda _node: client)

    with pytest.raises(ExplorerConflict, match="pattern changed after the session started"):
        controller.inspect_resource("demo", "mergetree:new_orders")


def test_resource_endpoint_requires_token(explorer_server, monkeypatch):
    server, base = explorer_server
    payload = {"database": "test", "table": "orders"}
    monkeypatch.setattr(server.controller, "inspect_resource", lambda _slug, _key: payload)
    url = f"{base}/api/resource?pattern=demo&resource=mergetree%3Aorders"

    with pytest.raises(HTTPError) as forbidden:
        urlopen(url)
    assert forbidden.value.code == 403

    request = Request(url)
    request.add_header("X-Explorer-Token", server.token)
    with urlopen(request) as response:
        assert json.loads(response.read()) == payload
