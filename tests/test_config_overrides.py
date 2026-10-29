from pathlib import Path

import pytest

from pattern_explorer.catalog.manifest import Pattern, load_pattern_dir
from pattern_explorer.orchestration.stack import pattern_compose_file


def _pattern(tmp_path: Path, config: list[dict]) -> Pattern:
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / "tiered.xml").write_text("<clickhouse/>\n")
    return Pattern(
        title="Config overlay", description="Test pattern.",
        graph="test:\n  client:x -> mergetree:y",
        topology="single", profiles=["single"], driver_node="ch",
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


def _pattern_with_init(tmp_path: Path, init: list[dict]) -> Pattern:
    (tmp_path / "seed.sql").write_text("CREATE TABLE t (id Int32);\n")
    return Pattern(
        title="Init overlay", description="Test pattern.",
        graph="test:\n  client:x -> mergetree:y",
        topology="single", profiles=["single", "postgres"], driver_node="ch",
        slug="init-overlay", dir=tmp_path, schema_sql=None, service_init=init,
    )


def test_database_init_scripts_mount_after_the_shared_seed(tmp_path):
    pattern = _pattern_with_init(tmp_path, [{"service": "postgres", "file": "seed.sql"}])

    overlay = pattern_compose_file(pattern)

    assert overlay is not None
    text = overlay.read_text()
    assert "postgres:" in text
    assert str((tmp_path / "seed.sql").resolve()) in text
    # The zz- prefix sorts the script after the stack's shared init.sql seed.
    assert "/docker-entrypoint-initdb.d/zz-pattern-seed.sql:ro" in text


def test_database_init_scripts_reject_unsafe_values(tmp_path):
    with pytest.raises(ValueError, match="init scripts"):
        _pattern_with_init(tmp_path, [{"service": "kafka", "file": "seed.sql"}])
    with pytest.raises(ValueError, match="relative"):
        _pattern_with_init(tmp_path, [{"service": "postgres", "file": "../seed.sql"}])
    with pytest.raises(ValueError, match=".sql"):
        _pattern_with_init(tmp_path, [{"service": "postgres", "file": "seed.sh"}])
    with pytest.raises(ValueError, match="same destination"):
        _pattern_with_init(tmp_path, [
            {"service": "postgres", "file": "seed.sql"},
            {"service": "postgres", "file": "seed.sql"},
        ])


def _pattern_with_native_config(tmp_path, mounts):
    (tmp_path / "connector.yaml").write_text("buffer.flush.time.ms: 30\n")
    return Pattern(
        title="Native connector configuration", description="Test pattern.",
        graph="changes:\n  mysql:source -> connector:sink -> mergetree:target",
        topology="single", profiles=["cdc-ch", "mysql", "cdc-mysql"], driver_node="ch-cdc",
        slug="native-config", dir=tmp_path, schema_sql=None, service_config=mounts,
    )


def test_native_config_mounts_are_pattern_local_and_read_only(tmp_path):
    import yaml
    from pattern_explorer.orchestration.session import pattern_digest

    pattern = _pattern_with_native_config(tmp_path, [
        {"service": "cdc-mysql", "file": "connector.yaml", "target": "/config.yml"},
    ])
    overlay = yaml.safe_load(pattern_compose_file(pattern).read_text())

    assert set(overlay["services"]) == {"cdc-mysql"}
    assert overlay["services"]["cdc-mysql"]["volumes"] == [
        f"{tmp_path / 'connector.yaml'}:/config.yml:ro",
    ]
    original_digest = pattern_digest(pattern)
    (tmp_path / "connector.yaml").write_text("buffer.flush.time.ms: 10\n")
    assert pattern_digest(pattern) != original_digest


@pytest.mark.parametrize("mount, error", [
    ({"service": "unknown", "file": "connector.yaml", "target": "/config.yml"}, "unknown configuration service"),
    ({"service": "ch", "file": "connector.yaml", "target": "/etc/config.xml"}, "additive ClickHouse"),
    ({"service": "cdc-mysql", "file": "../connector.yaml", "target": "/config.yml"}, "relative"),
    ({"service": "cdc-mysql", "file": "missing.yaml", "target": "/config.yml"}, "not found"),
    ({"service": "cdc-mysql", "file": "connector.yaml", "target": "config.yml"}, "absolute container file"),
    ({"service": "cdc-mysql", "file": "connector.yaml", "target": "/etc/../config.yml"}, "absolute container file"),
])
def test_native_config_rejects_invalid_mounts(tmp_path, mount, error):
    with pytest.raises(ValueError, match=error):
        _pattern_with_native_config(tmp_path, [mount])


def test_native_config_rejects_duplicate_destinations(tmp_path):
    mount = {"service": "cdc-mysql", "file": "connector.yaml", "target": "/config.yml"}
    with pytest.raises(ValueError, match="same destination"):
        _pattern_with_native_config(tmp_path, [mount, mount])


def test_grouped_manifest_loads_native_service_config(tmp_path):
    import yaml

    pattern = _pattern_with_native_config(tmp_path, [])
    (tmp_path / "pattern.yaml").write_text(yaml.safe_dump({
        "manifest_version": 2,
        "metadata": {"title": pattern.title, "description": pattern.description,
                     "graph": pattern.graph, "topology": "single"},
        "spec": {"profiles": pattern.profiles, "driver_node": "ch-cdc", "services": {
            "cdc-mysql": {"config": [{"file": "connector.yaml", "target": "/config.yml"}]},
        }},
    }))

    loaded = load_pattern_dir(tmp_path, "native-config")

    assert loaded.service_config[0].service == "cdc-mysql"
    assert loaded.service_config[0].target == "/config.yml"
