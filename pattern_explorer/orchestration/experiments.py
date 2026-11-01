"""Run a pattern's on-demand experiments against the active session.

An experiment is a script in the pattern folder. Parameters with a `config`
entry are applied through edited copies of the pattern's config files
(config_overlay); the pattern files themselves are never edited. When the
copies change, the session reloads to read them, and it keeps running with them
after the run, so repeated runs at the same values need no reload. A normal
reload, stop or start goes back to the committed files. Other parameters are
passed to the script as arguments.

Each run appends one JSON line to .runtime/experiments/<slug>.jsonl, so results
survive the reloads that tear down the pattern's volumes.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from . import config_overlay
from . import session as sessions
from ..catalog.manifest import Experiment, Pattern
from .lifecycle import reload_session
from .probe import RESULT_PREFIX
from .runner import Reporter

_ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = _ROOT / ".runtime" / "experiments"
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")

# The script process of the experiment in progress, so stop_experiment() can end it.
_process_lock = threading.Lock()
_process: subprocess.Popen | None = None
_stop_requested = False


def stop_experiment() -> bool:
    """Terminate the running experiment script; False when none is running."""
    global _stop_requested
    with _process_lock:
        if _process is None or _process.poll() is not None:
            return False
        _stop_requested = True
        _process.terminate()
        return True


def find_experiment(pattern: Pattern, name: str) -> Experiment:
    for experiment in pattern.experiments:
        if experiment.name == name:
            return experiment
    known = [experiment.name for experiment in pattern.experiments]
    raise ValueError(f"{pattern.slug} has no experiment {name!r}; known: {known}")


def resolve_values(experiment: Experiment, overrides: dict) -> dict[str, int | float | str]:
    """Defaults merged with overrides, each coerced to its default's type and
    checked against the parameter's `choices` and `min`."""
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
            kind = "a whole number" if isinstance(parameter.default, int) else "a number"
            raise ValueError(f"{name} must be {kind}") from None
        if parameter.choices and value not in parameter.choices:
            raise ValueError(f"{name} must be one of {parameter.choices}")
        if parameter.min is not None and value < parameter.min:
            raise ValueError(f"{name} must be at least {parameter.min}")
        values[name] = value
    return values


def _config_line(key: str) -> re.Pattern:
    # `key = value` (TOML, SQL options), `key: value` (YAML) or `"key": "value"`
    # (JSON), keeping quotes, trailing commas and comments.
    return re.compile(
        rf'^(\s*"?{re.escape(key)}"?\s*[:=]\s*"?)([^\s#,"]+)(.*)$', re.MULTILINE
    )


def edit_config(text: str, key: str, value) -> str | None:
    """`text` with the first `key` line set to `value`, or None when it already is."""
    line = _config_line(key)
    match = line.search(text)
    if match is None:
        raise ValueError(f"no `{key}` line")
    if match.group(2) == str(value):
        return None
    return line.sub(lambda m: f"{m.group(1)}{value}{m.group(3)}", text, count=1)


def _results_path(slug: str) -> Path:
    # The slug arrives from HTTP requests; keep it to a plain file name.
    if not _SLUG.match(slug):
        raise ValueError(f"invalid pattern slug {slug!r}")
    return RESULTS_DIR / f"{slug}.jsonl"


def read_runs(slug: str) -> list[dict]:
    """Saved runs, oldest first. A line that is not valid JSON (a run cut off
    mid-write) is skipped rather than hiding every other run."""
    path = _results_path(slug)
    if not path.exists():
        return []
    runs = []
    for line in path.read_text().splitlines():
        try:
            runs.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return runs


def clear_runs(slug: str) -> None:
    _results_path(slug).unlink(missing_ok=True)


def _record(run: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with _results_path(run["pattern"]).open("a") as handle:
        handle.write(json.dumps(run) + "\n")


def _run_script(pattern: Pattern, experiment: Experiment, args: list[str], report: Reporter) -> dict:
    global _process, _stop_requested
    path = pattern.dir / experiment.script
    env = {**os.environ, "PYTHONPATH": str(_ROOT), "PYTHONUNBUFFERED": "1"}
    command = [sys.executable, str(path), *args]
    with _process_lock:
        _stop_requested = False
        process = _process = subprocess.Popen(
            command, cwd=pattern.dir, env=env, text=True, bufsize=1,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
    try:
        return _read_script(process, command, experiment, report)
    finally:
        with _process_lock:
            _process = None


def _read_script(process, command, experiment: Experiment, report: Reporter) -> dict:
    assert process.stdout is not None
    result: dict = {}
    for line in process.stdout:
        message = line.rstrip()
        if message.startswith(RESULT_PREFIX):
            # NaN would make the saved line unreadable to the browser.
            result = json.loads(message[len(RESULT_PREFIX):], parse_constant=lambda _: None)
        elif message:
            report(f"EXPERIMENT {message}")
    if process.wait():
        if _stop_requested:
            raise RuntimeError("experiment stopped")
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

    # Copies of each config file the parameters touch, edited from the pattern's
    # committed text. A value equal to the committed one needs no copy.
    copies: dict[str, str] = {}
    applied: dict[str, int | float | str] = {}
    for parameter in experiment.parameters:
        if parameter.config is None:
            continue
        relative = parameter.config.file
        text = copies.get(relative, (pattern.dir / relative).read_text())
        try:
            edited = edit_config(text, parameter.config.key, values[parameter.name])
        except ValueError as exc:
            raise ValueError(f"{relative}: {exc}") from None
        if edited is not None:
            copies[relative] = edited
            applied[parameter.name] = values[parameter.name]
    described = ", ".join(f"{name}={value}" for name, value in applied.items()) or "the pattern's own config"
    if config_overlay.replace(pattern.slug, copies, applied):
        report(f"EXPERIMENT reloading the session with {described}")
        reload_session(report=report, keep_experiment_config=True)
    elif applied:
        report(f"EXPERIMENT session already runs with {described}; no reload")

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
    report("EXPERIMENT " + ", ".join(f"{key}={value}" for key, value in result.items() if key != "stages"))
    return run
