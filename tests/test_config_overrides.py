from pathlib import Path

import pytest

from pattern_explorer.catalog.manifest import Pattern
from pattern_explorer.orchestration.stack import pattern_compose_file


def _pattern(tmp_path: Path, config: list[dict]) -> Pattern:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "tiered.xml").write_text("<clickhouse/>\n")
    return Pattern(
        title="Config overlay", description="Test pattern.",
        graph="test:\n  client:x -> mergetree:y", category="test",
        flow="test", topology="single", profiles=["single"], driver_node="ch",
        slug="config-overlay", dir=tmp_path, schema_sql=None, clickhouse_config=config,
    )


def test_pattern_config_is_written_as_an_additive_compose_overlay(tmp_path):
    pattern = _pattern(tmp_path, [{"node": "ch", "file": "config/tiered.xml", "depends_on": ["minio-init"]}])

    overlay = pattern_compose_file(pattern)

    assert overlay is not None
    text = overlay.read_text()
    assert str((tmp_path / "config" / "tiered.xml").resolve()) in text
    assert "/etc/clickhouse-server/config.d/99-pattern-tiered.xml:ro" in text
    assert "minio-init:" in text
    assert "condition: service_healthy" in text


def test_pattern_config_rejects_unsafe_or_duplicate_destinations(tmp_path):
    with pytest.raises(ValueError, match="relative"):
        _pattern(tmp_path, [{"node": "ch", "file": "../secret.xml"}])
    with pytest.raises(ValueError, match="same destination"):
        _pattern(tmp_path, [
            {"node": "ch", "file": "config/tiered.xml"},
            {"node": "ch", "file": "config/tiered.xml"},
        ])
