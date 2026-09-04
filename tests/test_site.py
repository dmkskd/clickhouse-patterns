import json
import subprocess
from pathlib import Path

import pytest

from pattern_explorer.catalog.graph import GraphSyntaxError, parse_resource_graph
from pattern_explorer.rendering.site import (
    build_explorer_site,
    build_pattern_site,
    explorer_catalog_json,
    write_explorer_catalog,
)
from pattern_explorer.catalog.manifest import discover_patterns, load_pattern


GRAPH = """\
ingestion:
  topic:events(partitions=4)
    -[group w3]-> kafka-table:events_queue@ch-s1
    -> mv:events_mv@ch-s1
    -> distributed:events_all
    -[cityHash64(id)]-> mergetree:events@shards

query:
  client -> distributed:events_all -> mergetree:events@shards
"""


def _catalog_pattern(slug: str) -> dict:
    """Compile the browser catalog and return one pattern's data dict."""
    catalog = json.loads(explorer_catalog_json())
    return next(item for item in catalog["patterns"] if item["slug"] == slug)


def test_every_curated_pattern_has_a_structured_resource_graph():
    patterns = discover_patterns()
    missing = [pattern.slug for pattern in patterns if not pattern.graph]

    assert missing == []
    for pattern in patterns:
        parse_resource_graph(pattern.graph or "")


def test_compact_paths_normalize_into_shared_resources_and_connections():
    graph = parse_resource_graph(GRAPH)

    assert graph.flows == ["ingestion", "query"]
    assert len(graph.resources) == 6
    assert len(graph.connections) == 6
    assert graph.resources["topic:events"].properties == {"partitions": "4"}
    assert graph.resources["kafka-table:events_queue@ch-s1"].scope == "ch-s1"
    assert graph.resources["mergetree:events@shards"].scope == "shards"
    assert [edge.label for edge in graph.connections if edge.label] == [
        "group w3",
        "cityHash64(id)",
    ]


def test_compact_graph_supports_explicit_fan_out():
    graph = parse_resource_graph(
        """\
output:
  refreshable-mv:status -> {topic:status, topic:alerts}
"""
    )

    assert set(graph.resources) == {
        "refreshable-mv:status",
        "topic:status",
        "topic:alerts",
    }
    assert len(graph.connections) == 2


def test_compact_graph_rejects_conflicting_inline_properties():
    with pytest.raises(GraphSyntaxError, match="conflicting `partitions`"):
        parse_resource_graph(
            """\
ingestion:
  topic:events(partitions=4) -> client
query:
  topic:events(partitions=8) -> client
"""
        )


def test_pattern_graph_builds_browser_site(tmp_path: Path):
    pattern = load_pattern("kafka-ingest-sharded-single-consumer")

    html_path = build_pattern_site(pattern, tmp_path)

    assert html_path == (tmp_path / "index.html").resolve()
    html = html_path.read_text()
    assert "ClickHouse Pattern Explorer" in html
    assert 'href="app.css"' in html
    assert 'src="app.js"' in html
    assert 'id="toggle-groups"' in html
    assert 'id="session-panel"' in html
    assert 'id="start-session"' in html
    assert 'id="explorer-mode"' in html
    assert 'id="catalog-home"' in html
    assert 'id="diagram-modal"' in html
    assert (tmp_path / "app.js").exists()
    assert (tmp_path / "app.css").exists()
    app = (tmp_path / "app.js").read_text()
    session = (tmp_path / "session.js").read_text()
    util = (tmp_path / "util.js").read_text()
    assert 'apiUrl("api/session")' in session
    assert "setDiagramZoom" in app
    assert "openDiagramModal" in app
    assert "data-clickhouse-resource-key" in util
    catalog = (tmp_path / "catalog.js").read_text()
    assert "topic:events(partitions=4)" in catalog
    assert '"location": "library"' in catalog
    assert '"location": "workspace"' in catalog


def test_static_site_contains_catalog_and_declares_capability_mode(tmp_path: Path):
    html_path = build_explorer_site(tmp_path)

    assert html_path == (tmp_path / "index.html").resolve()
    assert {path.name for path in tmp_path.iterdir()} == {
        "index.html", "app.css", "app.js", "catalog.js",
        "util.js", "diagram.js", "topology.js", "session.js",
    }
    html = html_path.read_text()
    app = (tmp_path / "app.js").read_text()
    session = (tmp_path / "session.js").read_text()
    assert ">Static catalog</span>" in html
    assert 'control.mode === "local"' in session
    assert "renderCatalogHome" in app
    assert "showCatalogHome" in app
    assert 'window.addEventListener("popstate"' in app
    assert "Diagrams, trade-offs, references, and SVG export work without a local service" in session
    assert "window.CLICKHOUSE_PATTERN_CATALOG" in (tmp_path / "catalog.js").read_text()


def test_static_site_hides_session_panel_until_local_mode(tmp_path: Path):
    html_path = build_explorer_site(tmp_path)

    html = html_path.read_text()
    css = (tmp_path / "app.css").read_text()
    session = (tmp_path / "session.js").read_text()
    assert 'id="session-panel" class="session-panel" aria-live="polite" hidden' in html
    assert ".session-panel[hidden] { display: none !important; }" in css
    assert 'const isLocal = control.mode === "local" && control.interactive' in session
    assert "panel.hidden = !isLocal" in session


def test_pattern_switch_uses_one_launch_action(tmp_path: Path):
    build_explorer_site(tmp_path)

    session = (tmp_path / "session.js").read_text()
    assert '!selectedDiffers\n        && active.owner !== "terminal"' in session
    assert 'switching ? "Launch this pattern" : "Launch pattern"' in session
    assert "Stop ${active.slug} and launch ${selected.slug}?" in session
    assert 'command(apiUrl("api/session/switch"), { pattern: selected.slug })' in session


def test_flat_light_reuses_soft_palette_with_flat_borders(tmp_path: Path):
    build_explorer_site(tmp_path)

    css = (tmp_path / "app.css").read_text()
    for token in (
        "--bg: #e6e8ec;",
        "--text: #26292e;",
        "--muted: #5f656e;",
        "--green: #3d9e6d;",
        "--blue: #4f86c6;",
        "--amber: #c97f1f;",
        "--violet: #7d8fc4;",
    ):
        assert css.count(token) >= 2  # shared by soft/light and flat/light
    assert '[data-theme="flat"][data-scheme="light"] .tradeoffs { background: var(--panel); }' in css
    assert '[data-theme="flat"][data-scheme="light"] .tradeoff-card { background: var(--panel); }' in css
    assert ".tradeoff-card { border: 1px solid var(--line);" in css
    assert ".architecture-panel, .tradeoffs { overflow: hidden; }" in css
    assert '[data-theme="flat"][data-scheme="light"] .session-panel.active .session-indicator' in css


def test_catalog_compiler_writes_data_without_ui_markup(tmp_path: Path):
    catalog_path = write_explorer_catalog(tmp_path / "catalog.js")

    catalog = catalog_path.read_text()
    assert "window.CLICKHOUSE_PATTERN_CATALOG" in catalog
    assert "topic:events(partitions=4)" in catalog
    assert "<html" not in catalog


def test_javascript_packer_builds_one_self_contained_file(tmp_path: Path):
    catalog_path = write_explorer_catalog(tmp_path / "catalog.js")
    output_path = tmp_path / "pattern-explorer.html"
    script = Path(__file__).parents[1] / "explorer" / "scripts" / "build-static.mjs"

    subprocess.run(
        [
            "node", str(script), "--single", "--catalog", str(catalog_path),
            "--output", str(output_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    html = output_path.read_text()
    assert "window.CLICKHOUSE_PATTERN_CATALOG" in html
    assert "topic:events(partitions=4)" in html
    assert "Static catalog" in html
    assert '<link rel="stylesheet" href="app.css"' not in html
    assert '<script src="catalog.js"' not in html
    assert '<script src="app.js"' not in html


def test_connector_delivery_claims_link_precise_upstream_documentation():
    pattern = load_pattern("kafka-push-connect")
    urls = {reference.url for reference in pattern.references}

    assert "https://clickhouse.com/docs/integrations/kafka/clickhouse-kafka-connect-sink" in urls
    assert "https://github.com/ClickHouse/clickhouse-kafka-connect/blob/main/docs/DESIGN.md" in urls


def test_peerdb_graph_compiles_operation_labels_and_hover_note():
    """The browser catalog carries the edge labels and hover note the JS renders."""
    pattern = _catalog_pattern("cdc-postgres-peerdb")
    labels = {edge["label"] for edge in pattern["graph"]["connections"] if edge["label"]}

    assert "SNAPSHOT · INSERT INTO orders FROM s3()" in labels
    assert "SNAPSHOT · INSERT INTO orders_existing FROM s3()" in labels
    assert "INSERT INTO _peerdb_raw … FROM s3()" in labels
    assert "PeerDB SQL · destination = orders" in labels
    assert "PeerDB SQL · destination = orders_existing" in labels

    resources = {item["key"]: item for item in pattern["graph"]["resources"]}
    node_labels = {item["properties"].get("label") for item in pattern["graph"]["resources"]}
    assert "test.orders · PeerDB-owned schema" in node_labels
    assert "test.orders_existing · user-owned schema" in node_labels

    raw = resources["mergetree:_peerdb_raw_two_table_mirror@peerdb-internal"]
    note = raw["properties"]["note"]
    assert note.startswith("**How this table fills**")
    assert "\\n- Owned by the two_table_mirror job" in note
    assert "\\n- Routed by _peerdb_destination_table_name" in note
