from types import SimpleNamespace

import pytest

from pattern_explorer.orchestration import lifecycle
from pattern_explorer.orchestration import session as sessions
from pattern_explorer.catalog.manifest import Pattern
from pattern_explorer.orchestration.runner import Result


class FakeCompose:
    def __init__(self):
        self.up_calls = []
        self.down_calls = []

    def up(self, **kwargs):
        self.up_calls.append(kwargs)

    def down(self, **kwargs):
        self.down_calls.append(kwargs)


@pytest.fixture
def pattern(tmp_path):
    pattern_dir = tmp_path / "pattern"
    pattern_dir.mkdir()
    (pattern_dir / "pattern.yaml").write_text("title: Demo\n")
    return Pattern.model_construct(
        title="Demo",
        description="Demonstrates a small pattern for lifecycle tests.",
        graph="ingestion:\n  client:source -> mergetree:demo",
        category="demo",
        flow="ingestion",
        topology="single",
        tags=["demo"],
        profiles=["single"],
        driver_node="ch",
        slug="demo",
        dir=pattern_dir,
        schema_sql=None,
        load=None,
    )


@pytest.fixture
def isolated_session(tmp_path, monkeypatch):
    state_file = tmp_path / "runtime" / "session.json"
    monkeypatch.setattr(sessions, "STATE_FILE", state_file)
    return state_file


def test_start_status_and_stop_session(pattern, isolated_session, monkeypatch):
    compose = FakeCompose()
    prepared = []
    monkeypatch.setattr(lifecycle, "docker", lambda profiles: SimpleNamespace(compose=compose))
    monkeypatch.setattr(
        lifecycle,
        "prepare_pattern",
        lambda value, report=None: prepared.append(value.slug),
    )
    monkeypatch.setattr(sessions, "load_session_pattern", lambda active: pattern)
    monkeypatch.setattr(
        lifecycle, "connect", lambda node: SimpleNamespace(ping=lambda: True)
    )

    active = lifecycle.start_session(pattern)

    assert active.phase == "ready"
    assert active.driver_url == "http://localhost:8123"
    assert active.schema_url == "http://localhost:8123/schema"
    assert active.play_url == "http://localhost:8123/play"
    assert active.as_dict()["schema_url"] == "http://localhost:8123/schema"
    assert active.as_dict()["play_url"] == "http://localhost:8123/play"
    assert active.pattern_dir == str(pattern.dir.resolve())
    assert active.pattern_location == "library"
    assert prepared == ["demo"]
    assert compose.up_calls == [{"detach": True, "wait": True}]

    status = lifecycle.get_session_status()
    assert status is not None
    assert status.reachable is True
    assert status.source_changed is False

    (pattern.dir / "schema.sql").write_text("SELECT 1\n")
    assert lifecycle.get_session_status().source_changed is True

    monkeypatch.setattr(
        lifecycle,
        "connect",
        lambda _node: pytest.fail("reachability should not be probed"),
    )
    status_without_probe = lifecycle.get_session_status(probe_reachability=False)
    assert status_without_probe is not None
    assert status_without_probe.reachable is False

    stopped = lifecycle.stop_session()
    assert stopped.slug == "demo"
    assert compose.down_calls == [{"volumes": True, "remove_orphans": True}]
    assert not isolated_session.exists()


def test_failed_start_remains_inspectable(pattern, isolated_session, monkeypatch):
    compose = FakeCompose()
    monkeypatch.setattr(lifecycle, "docker", lambda profiles: SimpleNamespace(compose=compose))

    def fail(_pattern, report=None):
        raise RuntimeError("load did not complete")

    monkeypatch.setattr(lifecycle, "prepare_pattern", fail)

    with pytest.raises(RuntimeError, match="load did not complete"):
        lifecycle.start_session(pattern)

    active = sessions.read_session(required=True)
    assert active.phase == "failed"
    assert active.error == "RuntimeError: load did not complete"
    assert isolated_session.exists()


def test_second_session_is_rejected(pattern, isolated_session):
    sessions.write_session(sessions.new_session(pattern).with_phase("ready"))

    with pytest.raises(sessions.SessionError, match="already has a ready session"):
        lifecycle.start_session(pattern)


def test_validate_uses_active_pattern(pattern, isolated_session, monkeypatch):
    sessions.write_session(sessions.new_session(pattern).with_phase("ready"))
    monkeypatch.setattr(sessions, "load_session_pattern", lambda active: pattern)
    expected = SimpleNamespace(passed=True)
    calls = []
    monkeypatch.setattr(
        lifecycle,
        "validate_pattern",
        lambda value, update=False, report=None: calls.append((value.slug, update)) or expected,
    )

    assert lifecycle.validate_session(update=True) is expected
    assert calls == [("demo", True)]


def test_browser_run_records_owner_and_validation_phase(
    pattern, isolated_session, monkeypatch
):
    compose = FakeCompose()
    monkeypatch.setattr(lifecycle, "docker", lambda profiles: SimpleNamespace(compose=compose))
    monkeypatch.setattr(lifecycle, "prepare_pattern", lambda value, report=None: None)
    monkeypatch.setattr(sessions, "load_session_pattern", lambda active: pattern)
    monkeypatch.setattr(
        lifecycle,
        "validate_pattern",
        lambda value, update=False, report=None: Result(value.slug, True),
    )

    result = lifecycle.run_session(pattern)

    active = sessions.read_session(required=True)
    assert result.passed is True
    assert active.owner == "browser"
    assert active.phase == "validated"


def test_operation_lock_rejects_a_second_mutation(isolated_session):
    with sessions.operation_lock():
        with pytest.raises(sessions.SessionError, match="already in progress"):
            with sessions.operation_lock():
                pass
