from types import SimpleNamespace

from pattern_explorer import cli
from pattern_explorer.cli import _cmd_describe, _cmd_status, _print_pattern_plan, _print_started
import pytest

from pattern_explorer.catalog.manifest import (
    PatternManifestError,
    discover_patterns,
    load_pattern,
    load_pattern_dir,
)
from pattern_explorer.orchestration.runner import Result
from pattern_explorer.orchestration.wait import ConvergenceError


def test_plain_description_strips_inline_pattern_links():
    description = "Companion to [[ttl-move-to-s3|TTL move: hot/cold storage with S3]]."

    assert cli._plain_description(description) == "Companion to TTL move: hot/cold storage with S3."


def test_plain_description_strips_external_markdown_links():
    description = "One [Postgres Table Engine](https://clickhouse.com/docs/engines/table-engines/integrations/postgresql) table."

    assert cli._plain_description(description) == "One Postgres Table Engine table."


def test_show_renders_inline_pattern_link_label(capsys):
    assert cli._cmd_show(SimpleNamespace(pattern="ttl-move-to-s3-replicated")) == 0

    output = capsys.readouterr().out
    assert "TTL move: hot/cold storage with S3" in output
    assert "[[" not in output
    assert "[]" not in output


def test_describe_explains_pattern_without_execution_details(capsys):
    pattern = load_pattern("cdc-mysql-clickhouse")

    assert _cmd_describe(SimpleNamespace()) == 0

    output = capsys.readouterr().out
    normalized = " ".join(output.split())
    assert " ".join(pattern.description.split()) in normalized
    assert " ".join(cli._flow_summary(pattern).split()) in normalized
    assert "DATABASES → CLICKHOUSE  (5 patterns)" in output
    assert "\n    profiles" not in output
    assert "\n    driver" not in output
    assert "\n    schema" not in output
    assert "\n    validation" not in output
    assert "\n    verify" not in output


def test_pattern_plan_explains_the_run(capsys):
    pattern = load_pattern("cdc-mysql-clickhouse")

    _print_pattern_plan(pattern, "end-to-end test with teardown")

    output = capsys.readouterr().out
    normalized = " ".join(output.replace("│", "").split())
    assert pattern.title in output
    assert " ".join(pattern.description.split()) in normalized
    assert " ".join(cli._flow_summary(pattern).split()) in normalized
    assert "DATA FLOW" in output
    assert "WHAT IT DEMONSTRATES" in output
    assert "RUN PLAN" in output
    assert "Start ClickHouse, MySQL, and the MySQL CDC sink." in normalized
    assert "Prepare the CDC-created and existing ClickHouse targets." in normalized
    assert "Run load.py using ch-cdc as the driver." in normalized
    assert "Wait for 6 convergence checks, then compare verify.sql with expected.txt." in normalized
    assert "Tear down the containers and volumes." in normalized
    assert "pins Altinity sink `2.9.1-lt` to ClickHouse `25.3`" in normalized
    assert "Altinity 2.9.1 supported ClickHouse versions (24.8+)" in normalized
    assert "Altinity 2.9.1 lightweight JDBC dependency (0.6.5)" in normalized


def test_interactive_run_plan_waits_before_cleanup(capsys):
    pattern = load_pattern("kafka-produce-refreshable-mv")

    _print_pattern_plan(pattern, "interactive run")

    normalized = " ".join(capsys.readouterr().out.replace("│", "").split())
    assert "Wait for 2 convergence checks" in normalized
    assert "Keep the validated environment available until the user finishes." in normalized
    assert "Tear down the containers and volumes." in normalized


def test_run_validates_waits_and_cleans_up(monkeypatch, capsys):
    pattern = load_pattern("kafka-produce-refreshable-mv")
    state = {"active": None}
    calls = []

    def active(phase="ready", error=None):
        value = SimpleNamespace(
            slug=pattern.slug,
            phase=phase,
            error=error,
            play_url="http://localhost:8123/play",
            schema_url="http://localhost:8123/schema",
        )
        value.with_phase = lambda next_phase, next_error=None: active(
            next_phase, next_error
        )
        return value

    def start(_pattern, report=None, owner="detached"):
        assert owner == "terminal"
        state["active"] = active()
        calls.append("start")
        return state["active"]

    def stop(report=None):
        calls.append("stop")
        stopped = state["active"]
        state["active"] = None
        return stopped

    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(cli, "load_pattern", lambda slug: pattern)
    monkeypatch.setattr(cli, "_print_pattern_plan", lambda pattern, action: None)
    monkeypatch.setattr(cli, "start_session", start)
    monkeypatch.setattr(
        cli,
        "validate_session",
        lambda update=False, report=None: calls.append("validate")
        or Result(pattern.slug, True),
    )
    monkeypatch.setattr(cli.sessions, "read_session", lambda: state["active"])
    monkeypatch.setattr(
        cli.sessions, "write_session", lambda value: state.update(active=value)
    )
    monkeypatch.setattr(
        cli,
        "get_session_status",
        lambda: SimpleNamespace(reachable=True, session=state["active"]),
    )
    monkeypatch.setattr(
        cli,
        "_wait_for_finish",
        lambda value: calls.append(("wait", value.phase)),
    )
    monkeypatch.setattr(cli, "stop_session", stop)

    rc = cli._cmd_run(SimpleNamespace(pattern=pattern.slug, update=False))

    assert rc == 0
    assert calls == ["start", "validate", ("wait", "validated"), "stop"]
    assert state["active"] is None
    assert f"PASS  {pattern.slug}" in capsys.readouterr().out


def test_run_requires_an_interactive_terminal(monkeypatch, capsys):
    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: False))

    assert cli._cmd_run(SimpleNamespace(pattern="demo", update=False)) == 2

    error = capsys.readouterr().err
    assert "requires an interactive terminal" in error
    assert "just test <pattern>" in error


def test_wait_prints_browse_with_architecture_link(monkeypatch, capsys, tmp_path):
    active = SimpleNamespace(
        play_url="http://localhost:8123/play",
        schema_url="http://localhost:8123/schema",
    )
    pattern = SimpleNamespace(slug="demo", graph="ingestion:\n  source -> target")
    html_path = tmp_path / "index.html"
    html_path.write_text("<html></html>")
    monkeypatch.setattr(cli.sessions, "load_session_pattern", lambda _active: pattern)
    monkeypatch.setattr(cli, "build_pattern_site", lambda _pattern, _output: html_path)

    cli._wait_for_finish(active, input_fn=lambda _prompt: "")

    output = capsys.readouterr().out
    assert "BROWSE" in output
    assert f"architecture       {html_path.as_uri()}?pattern=demo" in output


def test_run_waits_on_reachable_validation_failure_then_cleans_up(
    monkeypatch, capsys
):
    pattern = load_pattern("kafka-produce-refreshable-mv")
    state = {"active": None}
    calls = []

    def make_active(phase="ready", error=None):
        value = SimpleNamespace(
            slug=pattern.slug,
            phase=phase,
            error=error,
            play_url="http://localhost:8123/play",
            schema_url="http://localhost:8123/schema",
        )
        value.with_phase = lambda next_phase, next_error=None: make_active(
            next_phase, next_error
        )
        return value

    def start(_pattern, report=None, owner="detached"):
        assert owner == "terminal"
        state["active"] = make_active()
        return state["active"]

    def fail_validation(update=False, report=None):
        raise ConvergenceError("rows did not converge")

    def stop(report=None):
        stopped = state["active"]
        state["active"] = None
        calls.append("stop")
        return stopped

    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(cli, "load_pattern", lambda slug: pattern)
    monkeypatch.setattr(cli, "_print_pattern_plan", lambda pattern, action: None)
    monkeypatch.setattr(cli, "start_session", start)
    monkeypatch.setattr(cli, "validate_session", fail_validation)
    monkeypatch.setattr(cli.sessions, "read_session", lambda: state["active"])
    monkeypatch.setattr(
        cli.sessions, "write_session", lambda value: state.update(active=value)
    )
    monkeypatch.setattr(
        cli,
        "get_session_status",
        lambda: SimpleNamespace(reachable=True, session=state["active"]),
    )
    monkeypatch.setattr(
        cli,
        "_wait_for_finish",
        lambda value: calls.append(("wait", value.phase)),
    )
    monkeypatch.setattr(cli, "stop_session", stop)

    rc = cli._cmd_run(SimpleNamespace(pattern=pattern.slug, update=False))

    assert rc == 1
    assert calls == [("wait", "failed"), "stop"]
    assert state["active"] is None
    assert "data did not converge in time" in capsys.readouterr().err


def test_pattern_plan_shows_external_references(capsys):
    pattern = load_pattern("kafka-ingest-sharded-full-copy")

    _print_pattern_plan(pattern, "end-to-end test with teardown")

    output = capsys.readouterr().out
    assert "REFERENCES" in output
    assert "ClickHouse Kafka table engine" in output
    assert "https://clickhouse.com/docs/engines/table-engines/integrations/kafka" in output
    assert "https://github.com/ClickHouse/ClickHouse/issues/107832" in output


def test_live_session_output_includes_schema_visualizer(monkeypatch, capsys):
    active = SimpleNamespace(
        slug="demo",
        phase="ready",
        driver_node="ch",
        driver_url="http://localhost:8123",
        schema_url="http://localhost:8123/schema",
        play_url="http://localhost:8123/play",
        profiles=["single"],
        pattern_dir="/tmp/demo",
        pattern_location="library",
        error=None,
    )
    status = SimpleNamespace(
        session=active,
        reachable=True,
        source_changed=False,
    )

    _print_started(active)
    monkeypatch.setattr("pattern_explorer.cli.get_session_status", lambda: status)
    assert _cmd_status(SimpleNamespace(json=False)) == 0

    output = capsys.readouterr().out
    assert output.count("BROWSE") == 2
    assert output.count("SQL console        http://localhost:8123/play") == 2
    assert output.count("schema visualizer  http://localhost:8123/schema") == 2
    assert output.count("MANAGE") == 2
    assert "validate           just validate" in output
    assert "rebuild            just reload" in output


def test_sharded_patterns_use_one_cluster_aware_schema():
    slugs = (
        "kafka-ingest-sharded-mv-filter",
        "kafka-ingest-sharded-full-copy",
        "kafka-ingest-sharded-single-consumer",
    )

    for slug in slugs:
        pattern = load_pattern(slug)
        assert pattern.schema_sql == "schema.sql"
        schema = pattern.path(pattern.schema_sql).read_text()
        assert "ON CLUSTER sharded" in schema
        assert "ENGINE = Distributed(sharded, demo, events" in schema


def test_every_pattern_defines_a_graph():
    for pattern in discover_patterns():
        assert pattern.graph, pattern.slug


def test_invalid_manifest_names_its_file_and_field(tmp_path):
    """Loading every manifest at once, the failure must say which one broke."""
    directory = tmp_path / "broken"
    directory.mkdir()
    (directory / "pattern.yaml").write_text(
        "manifest_version: 2\n"
        "metadata:\n"
        "  title: Broken\n"
        "  description: A manifest with a colon that YAML reads as a mapping.\n"
        "  topology: single\n"
        "  graph: |-\n"
        "    lane:\n"
        "      client:writer -> mergetree:events\n"
        "  tradeoffs:\n"
        "    benefits:\n"
        "      - One benefit.\n"
        "    limitations:\n"
        "      - The rollout is manual: each partition needs `MATERIALIZE TTL`.\n"
        "spec:\n"
        "  mode: reference\n"
    )

    with pytest.raises(PatternManifestError) as failure:
        load_pattern_dir(directory, "broken")

    message = str(failure.value).splitlines()[0]
    assert "broken/pattern.yaml" in message
    assert "tradeoffs.limitations.0" in message
    assert "valid string" in message


def test_manifest_failure_does_not_blame_the_requested_pattern(capsys):
    """A manifest error names its own file; any pattern load reads all of them."""
    failure = PatternManifestError("patterns/g/other/pattern.yaml: tradeoffs.limitations.1 bad")

    cli._explain(failure, "ttl-move-to-s3")

    error = capsys.readouterr().err
    assert "ttl-move-to-s3" not in error.splitlines()[0]
    assert "patterns/g/other/pattern.yaml" in error


def test_superseded_by_points_to_a_real_pattern():
    patterns = discover_patterns()
    slugs = {pattern.slug for pattern in patterns}
    for pattern in patterns:
        if pattern.superseded_by:
            assert pattern.superseded_by in slugs, (
                f"{pattern.slug} is superseded_by unknown pattern {pattern.superseded_by!r}"
            )
