"""On-demand experiments: manifest rules, value resolution, config edits, saved
runs and the probe helpers. No Docker: the runner's I/O is exercised on files."""
from __future__ import annotations

import json
import math

import pytest
from pydantic import ValidationError

from pattern_explorer.catalog.manifest import (
    Experiment,
    ExperimentParameter,
    discover_patterns,
    discover_workspace_patterns,
    load_pattern,
)
import yaml

from pattern_explorer.orchestration import config_overlay, experiments, stack
from pattern_explorer.orchestration.experiments import edit_config, resolve_values
from pattern_explorer.orchestration.probe import paced, result_line
from pattern_explorer.rendering.site import _browser_pattern


def _experiment(*parameters: dict) -> Experiment:
    return Experiment(name="probe", title="Probe", script="run.py",
                      parameters=[ExperimentParameter(**p) for p in parameters])


def test_text_default_needs_choices():
    with pytest.raises(ValidationError, match="needs `choices`"):
        ExperimentParameter(name="mode", default="kill")


def test_default_must_be_a_choice_and_respect_min():
    with pytest.raises(ValidationError, match="not in choices"):
        ExperimentParameter(name="mode", default="kill", choices=["restart"])
    with pytest.raises(ValidationError, match="`min`"):
        ExperimentParameter(name="rate", default=0, min=1)


def test_resolve_values_coerces_and_checks_rules():
    experiment = _experiment(
        {"name": "rate", "default": 50, "min": 1},
        {"name": "mode", "default": "restart", "choices": ["restart", "kill"]},
        {"name": "pause", "default": 0},
    )
    assert resolve_values(experiment, {"rate": "500", "mode": "kill"}) == {
        "rate": 500, "mode": "kill", "pause": 0,
    }
    with pytest.raises(ValueError, match="at least 1"):
        resolve_values(experiment, {"rate": "0"})
    with pytest.raises(ValueError, match="one of"):
        resolve_values(experiment, {"mode": "drop"})
    with pytest.raises(ValueError, match="whole number"):
        resolve_values(experiment, {"rate": "1.5"})
    with pytest.raises(ValueError, match="unknown parameter"):
        resolve_values(experiment, {"speed": "1"})


@pytest.mark.parametrize("text, key, expected", [
    ("[ch]\nflush_timeout_ms = 1000  # ms\n", "flush_timeout_ms", "[ch]\nflush_timeout_ms = 200  # ms\n"),
    ("poll.interval.ms: 500\n", "poll.interval.ms", "poll.interval.ms: 200\n"),
    ('{\n  "poll.interval.ms": "500",\n  "x": 1\n}\n', "poll.interval.ms", '{\n  "poll.interval.ms": "200",\n  "x": 1\n}\n'),
    ("-- sync_interval = 9 in a comment\nWITH (\n    sync_interval = 1\n);\n", "sync_interval",
     "-- sync_interval = 9 in a comment\nWITH (\n    sync_interval = 200\n);\n"),
])
def test_edit_config_rewrites_one_value_in_each_format(text, key, expected):
    assert edit_config(text, key, 200) == expected


def test_edit_config_reports_no_change_and_missing_keys():
    assert edit_config("rate = 5\n", "rate", 5) is None
    with pytest.raises(ValueError, match="no `rate` line"):
        edit_config("speed = 5\n", "rate", 1)


def test_saved_runs_skip_broken_lines_and_reject_path_slugs(tmp_path, monkeypatch):
    monkeypatch.setattr(experiments, "RESULTS_DIR", tmp_path)
    (tmp_path / "demo.jsonl").write_text('{"experiment": "a"}\n{"experim\n{"experiment": "b"}\n')
    assert [run["experiment"] for run in experiments.read_runs("demo")] == ["a", "b"]
    with pytest.raises(ValueError, match="invalid pattern slug"):
        experiments.read_runs("../demo")
    experiments.clear_runs("demo")
    assert experiments.read_runs("demo") == []


def test_config_copies_replace_and_clear(tmp_path, monkeypatch):
    monkeypatch.setattr(config_overlay, "OVERLAY_ROOT", tmp_path)
    files = {"config/latency.toml": "flush_timeout_ms = 200\n"}
    assert config_overlay.replace("demo", files, {"flush_timeout_ms": 200}) is True
    # Same copies again: nothing changed, so the runner skips the reload.
    assert config_overlay.replace("demo", files, {"flush_timeout_ms": 200}) is False
    assert config_overlay.applied_values("demo") == {"flush_timeout_ms": 200}
    pattern_dir = tmp_path / "pattern"
    assert config_overlay.effective(pattern_dir, "demo", "config/latency.toml") == tmp_path / "demo" / "config/latency.toml"
    assert config_overlay.effective(pattern_dir, "demo", "config/other.toml") == pattern_dir / "config/other.toml"
    # Back to the committed value: the copies go away.
    assert config_overlay.replace("demo", {}, {}) is True
    assert config_overlay.applied_values("demo") == {}
    assert not (tmp_path / "demo").exists()


def test_loaders_read_the_copy_named_by_the_runner(tmp_path, monkeypatch):
    copy = tmp_path / "copies" / "config" / "mirror.sql"
    copy.parent.mkdir(parents=True)
    copy.write_text("sync_interval = 5")
    pattern_dir = tmp_path / "pattern"
    monkeypatch.delenv(config_overlay.ENV, raising=False)
    assert config_overlay.config_file(pattern_dir, "config/mirror.sql") == pattern_dir / "config/mirror.sql"
    monkeypatch.setenv(config_overlay.ENV, str(tmp_path / "copies"))
    assert config_overlay.config_file(pattern_dir, "config/mirror.sql") == copy


def test_compose_mounts_the_copy_instead_of_the_pattern_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config_overlay, "OVERLAY_ROOT", tmp_path / "copies")
    monkeypatch.setattr(stack, "RUNTIME_OVERRIDES", tmp_path / "overrides")
    pattern = load_pattern("cdc-postgres-walshadow")
    mounted = lambda: yaml.safe_load(stack.pattern_compose_file(pattern).read_text())["services"]["walshadow"]["volumes"]
    assert any(str(pattern.dir / "config/latency.toml") in volume for volume in mounted())
    config_overlay.replace(pattern.slug, {"config/latency.toml": "[ch]\nflush_timeout_ms = 200\n"}, {"flush_timeout_ms": 200})
    assert any(str(tmp_path / "copies" / pattern.slug / "config/latency.toml") in volume for volume in mounted())


def test_result_line_turns_nan_into_null():
    line = result_line({"p50_ms": math.nan, "stages": [{"label": "x", "ms": math.inf}]})
    assert line == 'RESULT {"p50_ms": null, "stages": [{"label": "x", "ms": null}]}'


def test_paced_writes_whole_transactions_in_order():
    batches = []
    paced(100, 6, rate=1_000_000, rows_per_txn=3, write_transaction=lambda ids: batches.append(list(ids)))
    assert batches == [[100, 101, 102], [103, 104, 105]]


def test_cdc_experiments_reach_the_browser_catalog():
    for slug in ("cdc-postgres-walshadow", "cdc-postgres-peerdb", "cdc-postgres-kafka", "cdc-mysql-clickhouse"):
        (experiment,) = _browser_pattern(load_pattern(slug))["experiments"]
        assert experiment["name"] == "replication-latency"
        assert experiment["groups"][-1] == "End to end (ms)"


def test_every_declared_experiment_script_and_config_key_exists():
    patterns = [p for p in [*discover_patterns(), *discover_workspace_patterns()] if p.experiments]
    assert patterns
    for pattern in patterns:
        for experiment in pattern.experiments:
            assert (pattern.dir / experiment.script).is_file(), (pattern.slug, experiment.script)
            for parameter in experiment.parameters:
                if parameter.config is None:
                    continue
                text = (pattern.dir / parameter.config.file).read_text()
                # A missing key would fail every run that changes the value.
                assert edit_config(text, parameter.config.key, 987654) is not None, (pattern.slug, parameter.name)
