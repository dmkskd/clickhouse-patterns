from pathlib import Path
from types import SimpleNamespace

import pytest

from pattern_explorer import cli
from pattern_explorer.catalog import manifest
from pattern_explorer.orchestration import session as sessions
from pattern_explorer.catalog.workspaces import (
    CloneError,
    CloneInfo,
    clone_pattern,
    create_workspace_pattern,
    delete_clone,
    read_clone_info,
)


def _write_pattern(root: Path, slug: str, group: str = "demo-group") -> Path:
    # Library patterns live under a group folder (patterns/<group>/<slug>) with a
    # group.yaml; workspace roots stay flat.
    if root == manifest.PATTERNS_DIR:
        group_dir = root / group
        group_dir.mkdir(parents=True, exist_ok=True)
        (group_dir / "group.yaml").write_text("title: Demo\norder: 1\n")
        directory = group_dir / slug
    else:
        directory = root / slug
    directory.mkdir(parents=True)
    (directory / "pattern.yaml").write_text(
        """\
manifest_version: 2
metadata:
  title: Demo pattern
  description: A complete pattern used to test local cloning.
  graph: "ingestion:\n  client:source -> mergetree:ch"
  status: stable
  category: demo
  flow: ingestion
  topology: single
  tags: [demo]
spec:
  profiles: [single]
  driver_node: ch
  steps:
    schema: null
    load: null
    verify:
      sql: null
      expected: null
"""
    )
    (directory / "README.md").write_text("# Demo\n")
    return directory


@pytest.fixture
def isolated_pattern_roots(tmp_path, monkeypatch):
    library = tmp_path / "patterns"
    cloned = tmp_path / "workspace-patterns"
    monkeypatch.setattr(manifest, "PATTERNS_DIR", library)
    monkeypatch.setattr(manifest, "WORKSPACE_PATTERNS_DIR", cloned)
    return library, cloned


def test_clone_creates_complete_local_copy_outside_curated_discovery(
    isolated_pattern_roots,
):
    library, cloned = isolated_pattern_roots
    source = _write_pattern(library, "demo-source")

    info = clone_pattern("demo-source", "my-demo")

    destination = cloned / "my-demo"
    assert info.directory == destination.resolve()
    assert (destination / "pattern.yaml").read_text() == (
        (source / "pattern.yaml").read_text().replace("  status: stable", "  status: wip")
    )
    assert (destination / "README.md").read_text() == "# Demo\n"
    metadata = read_clone_info(destination)
    assert metadata is not None
    assert metadata.source == "demo-source"

    loaded = manifest.load_pattern("my-demo")
    assert loaded.location == "workspace"
    assert loaded.status == "wip"
    assert loaded.dir == destination
    assert [pattern.slug for pattern in manifest.discover_patterns()] == ["demo-source"]
    assert [pattern.slug for pattern in manifest.discover_cloned_patterns()] == ["my-demo"]

    session = sessions.new_session(loaded)
    assert session.pattern_location == "workspace"
    assert session.pattern_dir == str(destination.resolve())
    assert sessions.load_session_pattern(session).dir == destination.resolve()


def test_clone_never_overwrites_library_patterns_or_existing_clones(
    isolated_pattern_roots,
):
    library, _cloned = isolated_pattern_roots
    _write_pattern(library, "demo-source")
    _write_pattern(library, "reserved-name")

    with pytest.raises(FileExistsError, match="reserved-name"):
        clone_pattern("demo-source", "reserved-name")

    clone_pattern("demo-source", "my-demo")
    with pytest.raises(FileExistsError, match="my-demo"):
        clone_pattern("demo-source", "my-demo")


def test_delete_clone_removes_only_managed_local_copy(isolated_pattern_roots):
    library, cloned = isolated_pattern_roots
    source = _write_pattern(library, "demo-source")
    clone_pattern("demo-source", "my-demo")

    info = delete_clone("my-demo")

    assert info.slug == "my-demo"
    assert info.source == "demo-source"
    assert not (cloned / "my-demo").exists()
    assert source.exists()


def test_delete_clone_refuses_library_and_unmanaged_directory(
    isolated_pattern_roots,
):
    library, cloned = isolated_pattern_roots
    _write_pattern(library, "demo-source")

    with pytest.raises(CloneError, match="library pattern"):
        delete_clone("demo-source")

    unmanaged = _write_pattern(cloned, "unmanaged")
    with pytest.raises(CloneError, match="missing .workspace.yaml"):
        delete_clone("unmanaged")
    assert unmanaged.exists()


@pytest.mark.parametrize("slug", ("My-Demo", "my_demo", "../demo", "my--demo"))
def test_clone_rejects_unsafe_or_inconsistent_names(isolated_pattern_roots, slug):
    library, _cloned = isolated_pattern_roots
    _write_pattern(library, "demo-source")

    with pytest.raises(ValueError, match="lowercase"):
        clone_pattern("demo-source", slug)


def test_pattern_lookup_rejects_path_traversal(isolated_pattern_roots):
    with pytest.raises(ValueError, match="lowercase"):
        manifest.load_pattern("../outside")


def test_clone_command_prints_workspace_destination(
    tmp_path, monkeypatch, capsys
):
    destination = (tmp_path / "workspace-patterns" / "my-demo").resolve()
    info = CloneInfo(
        slug="my-demo",
        source="demo-source",
        directory=destination,
        created_at="2026-07-21T12:00:00+00:00",
    )
    monkeypatch.setattr(cli, "clone_pattern", lambda source, clone: info)

    assert cli._cmd_clone(SimpleNamespace(pattern="demo-source", clone="my-demo")) == 0

    output = capsys.readouterr().out
    assert f"destination {destination}" in output
    assert f"commit {destination.parent} to its workspace repository" in output
    assert "just run my-demo" in output
    assert "just test my-demo" in output


def test_delete_command_prints_removed_destination(tmp_path, monkeypatch, capsys):
    destination = (tmp_path / "workspace-patterns" / "my-demo").resolve()
    info = CloneInfo(
        slug="my-demo",
        source="demo-source",
        directory=destination,
        created_at="2026-07-21T12:00:00+00:00",
    )
    monkeypatch.setattr(cli.sessions, "read_session", lambda: None)
    monkeypatch.setattr(cli, "delete_clone", lambda clone: info)

    assert cli._cmd_delete(SimpleNamespace(clone="my-demo")) == 0

    output = capsys.readouterr().out
    assert "DELETED  my-demo (derived from demo-source)" in output
    assert f"removed {destination}" in output


def test_delete_command_refuses_active_clone(monkeypatch):
    active = SimpleNamespace(slug="my-demo", pattern_location="workspace")
    monkeypatch.setattr(cli.sessions, "read_session", lambda: active)

    with pytest.raises(CloneError, match="just stop"):
        cli._cmd_delete(SimpleNamespace(clone="my-demo"))


def test_list_shows_workspace_patterns_separately(
    isolated_pattern_roots, capsys
):
    library, _cloned = isolated_pattern_roots
    _write_pattern(library, "demo-source")
    clone_pattern("demo-source", "my-demo")

    assert cli._cmd_list(SimpleNamespace()) == 0

    output = capsys.readouterr().out
    assert "ClickHouse Patterns (1)" in output
    assert "Workspace Patterns (1)" in output
    assert "company and team extensions" in output
    assert "my-demo" in output
    assert "demo-source" in output


def test_new_workspace_pattern_is_documentation_first(isolated_pattern_roots):
    _library, workspace = isolated_pattern_roots

    info = create_workspace_pattern("our-orders-cdc")
    pattern = manifest.load_pattern("our-orders-cdc")

    assert info.source == "scratch"
    assert info.directory == (workspace / "our-orders-cdc").resolve()
    assert pattern.location == "workspace"
    assert pattern.runnable is False
    assert pattern.status == "wip"
    assert pattern.graph
    assert pattern.profiles == []
    assert not (pattern.dir / "README.md").exists()


def test_configured_workspace_root_is_discovered(tmp_path, monkeypatch):
    library = tmp_path / "patterns"
    configured = tmp_path / "company-patterns"
    monkeypatch.setattr(manifest, "PATTERNS_DIR", library)
    monkeypatch.setattr(manifest, "WORKSPACE_PATTERNS_DIR", tmp_path / "workspace-patterns")
    monkeypatch.setenv("CLICKHOUSE_PATTERN_WORKSPACES", str(configured))
    _write_pattern(configured, "company-orders")

    pattern = manifest.load_pattern("company-orders")

    assert pattern.location == "workspace"
    assert pattern.dir == configured / "company-orders"


def test_external_workspace_root_is_used_for_creation_and_discovery(tmp_path, monkeypatch):
    library = tmp_path / "patterns"
    canonical = tmp_path / "workspace-patterns"
    private_workspace = tmp_path / "private-patterns"
    monkeypatch.setattr(manifest, "PATTERNS_DIR", library)
    monkeypatch.setattr(manifest, "WORKSPACE_PATTERNS_DIR", canonical)
    monkeypatch.setenv("CLICKHOUSE_PATTERN_WORKSPACE_DIR", str(private_workspace))
    _write_pattern(library, "demo-source")

    info = clone_pattern("demo-source", "private-demo")

    assert info.directory == (private_workspace / "private-demo").resolve()
    assert manifest.load_pattern("private-demo").dir == info.directory
    assert private_workspace.resolve() in manifest.workspace_pattern_dirs()
    assert not canonical.exists()

    delete_clone("private-demo")
    assert not info.directory.exists()
