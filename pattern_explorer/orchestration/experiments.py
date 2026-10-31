"""Run a pattern's on-demand experiments against the active session.

An experiment is a script in the pattern folder. Parameters with a `config`
entry are written to that config file, and the session is reloaded so the
service reads the new value. The file is restored and the session reloaded
again afterwards. Other parameters are passed to the script as arguments.

Each run appends one JSON line to .runtime/experiments/<slug>.jsonl, so results
survive the reloads that tear down the pattern's volumes.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import session as sessions
from ..catalog.manifest import Experiment, ExperimentParameter, Pattern
from .lifecycle import reload_session
from .runner import Reporter

_ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = _ROOT / ".runtime" / "experiments"
RESULT_PREFIX = "RESULT "


def find_experiment(pattern: Pattern, name: str) -> Experiment:
    for experiment in pattern.experiments:
        if experiment.name == name:
            return experiment
    known = [experiment.name for experiment in pattern.experiments]
    raise ValueError(f"{pattern.slug} has no experiment {name!r}; known: {known}")


def resolve_values(experiment: Experiment, overrides: dict) -> dict[str, int | float]:
    """Defaults merged with overrides, each coerced to its default's type."""
    known = {parameter.name: parameter for parameter in experiment.parameters}
    unknown = set(overrides) - set(known)
    if unknown:
        raise ValueError(f"unknown parameter(s) {sorted(unknown)}; known: {sorted(known)}")
    values = {}
    for name, parameter in known.items():
        raw = overrides.get(name, parameter.default)
        try:
            value = type(parameter.default)(raw)
        except (TypeError, ValueError):
            raise ValueError(f"{name} must be a {type(parameter.default).__name__}") from None
        if value <= 0:
            raise ValueError(f"{name} must be positive")
        values[name] = value
    return values


def _config_line(key: str) -> re.Pattern:
    # `key = value` (TOML, SQL options), `key: value` (YAML) or `"key": "value"`
    # (JSON), keeping quotes, trailing commas and comments.
    return re.compile(
        rf'^(\s*"?{re.escape(key)}"?\s*[:=]\s*"?)([^\s#,"]+)(.*)$', re.MULTILINE
    )


def _set_config(pattern: Pattern, parameter: ExperimentParameter, value) -> str | None:
    """Write the value; return the original text when the file changed."""
    path = pattern.dir / parameter.config.file
    text = path.read_text()
    line = _config_line(parameter.config.key)
    match = line.search(text)
    if match is None:
        raise ValueError(f"{parameter.config.file} has no `{parameter.config.key}` line")
    if match.group(2) == str(value):
        return None
    path.write_text(line.sub(lambda m: f"{m.group(1)}{value}{m.group(3)}", text, count=1))
    return text


def read_runs(slug: str) -> list[dict]:
    path = RESULTS_DIR / f"{slug}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def clear_runs(slug: str) -> None:
    (RESULTS_DIR / f"{slug}.jsonl").unlink(missing_ok=True)


def _record(run: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with (RESULTS_DIR / f"{run['pattern']}.jsonl").open("a") as handle:
        handle.write(json.dumps(run) + "\n")


def _run_script(pattern: Pattern, experiment: Experiment, args: list[str], report: Reporter) -> dict:
    path = pattern.dir / experiment.script
    env = {**os.environ, "PYTHONPATH": str(_ROOT), "PYTHONUNBUFFERED": "1"}
    command = [sys.executable, str(path), *args]
    process = subprocess.Popen(
        command, cwd=pattern.dir, env=env, text=True, bufsize=1,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    assert process.stdout is not None
    result: dict = {}
    for line in process.stdout:
        message = line.rstrip()
        if message.startswith(RESULT_PREFIX):
            result = json.loads(message[len(RESULT_PREFIX):])
        elif message:
            report(f"EXPERIMENT {message}")
    if process.wait():
        raise subprocess.CalledProcessError(process.returncode, command)
    if not result:
        raise RuntimeError(f"{experiment.script} printed no `{RESULT_PREFIX.strip()}` line")
    return result


def run_experiment(
    pattern: Pattern, name: str, overrides: dict, report: Reporter | None = None
) -> dict:
    report = report or print
    experiment = find_experiment(pattern, name)
    values = resolve_values(experiment, overrides)
    active = sessions.read_session(required=True)
    if active.slug != pattern.slug:
        raise sessions.SessionError(f"{active.slug} is running, not {pattern.slug}")

    originals: dict[Path, str] = {}
    try:
        for parameter in experiment.parameters:
            if parameter.config is None:
                continue
            original = _set_config(pattern, parameter, values[parameter.name])
            if original is not None:
                originals.setdefault(pattern.dir / parameter.config.file, original)
                report(f"EXPERIMENT set {parameter.config.key} = {values[parameter.name]}"
                       f" in {parameter.config.file}")
        if originals:
            report("EXPERIMENT reloading the session to apply the config change")
            reload_session(report=report)

        args = []
        for parameter in experiment.parameters:
            if parameter.config is None:
                args += [f"--{parameter.name.replace('_', '-')}", str(values[parameter.name])]
        started_at = datetime.now(timezone.utc).isoformat()
        report(f"EXPERIMENT running {experiment.title}: "
               + ", ".join(f"{key}={value}" for key, value in values.items()))
        with sessions.operation_lock():
            result = _run_script(pattern, experiment, args, report)
        run = {
            "pattern": pattern.slug,
            "experiment": experiment.name,
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "parameters": values,
            "results": result,
        }
        _record(run)
        report("EXPERIMENT " + ", ".join(f"{key}={value}" for key, value in result.items()))
        return run
    finally:
        for path, text in originals.items():
            path.write_text(text)
        if originals:
            report("EXPERIMENT restoring the original config and reloading the session")
            reload_session(report=report)
