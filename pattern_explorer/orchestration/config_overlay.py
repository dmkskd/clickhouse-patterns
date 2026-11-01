"""Experiment config values for the running session, kept outside the pattern.

An experiment that changes a config parameter writes an edited copy of the
pattern's file to .runtime/experiment-config/<slug>/<same relative path>. The
pattern file itself is never edited. The copies are used at session start:

- `stack.pattern_compose_file()` mounts a copy in place of the pattern file;
- `config_file()` returns a copy to loaders that read config from the host
  (PeerDB `mirror.sql`, Kafka Connect JSON), found through PATTERN_CONFIG_OVERLAY.

values.json beside the copies records the parameter values they apply, so the
Explorer can show which experiment values the session runs with. A normal
start, stop, reload or reset clears the copies, so those always use the
pattern's committed files.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

OVERLAY_ROOT = Path(__file__).resolve().parents[2] / ".runtime" / "experiment-config"
ENV = "PATTERN_CONFIG_OVERLAY"
VALUES = "values.json"


def overlay_dir(slug: str) -> Path:
    return OVERLAY_ROOT / slug


def effective(pattern_dir: Path, slug: str, relative: str) -> Path:
    """The file a session should read: the experiment copy when one exists."""
    copy = overlay_dir(slug) / relative
    return copy if copy.is_file() else pattern_dir / relative


def loader_env(slug: str) -> dict[str, str]:
    """Environment for a loader subprocess, pointing at the copies if any."""
    directory = overlay_dir(slug)
    return {ENV: str(directory)} if directory.is_dir() else {}


def config_file(pattern_dir: Path, relative: str) -> Path:
    """For loaders: the experiment copy of `relative` when the runner set one."""
    overlay = os.environ.get(ENV)
    if overlay and (Path(overlay) / relative).is_file():
        return Path(overlay) / relative
    return pattern_dir / relative


def applied_values(slug: str) -> dict:
    """Parameter values the current copies apply; empty when there are none."""
    path = overlay_dir(slug) / VALUES
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _current_files(slug: str) -> dict[str, str]:
    directory = overlay_dir(slug)
    if not directory.is_dir():
        return {}
    return {
        str(path.relative_to(directory)): path.read_text()
        for path in directory.rglob("*")
        if path.is_file() and path.name != VALUES
    }


def replace(slug: str, files: dict[str, str], values: dict) -> bool:
    """Make the copies exactly `files` ({relative path: text}); True if they changed.

    An empty `files` removes the copies, so the session goes back to the
    pattern's own files on its next start.
    """
    changed = _current_files(slug) != files
    if changed:
        clear(slug)
    if files:
        directory = overlay_dir(slug)
        for relative, text in files.items():
            path = directory / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        (directory / VALUES).write_text(json.dumps(values))
    return changed


def clear(slug: str | None = None) -> bool:
    """Remove one pattern's copies, or every pattern's; True if any existed."""
    directory = overlay_dir(slug) if slug else OVERLAY_ROOT
    existed = directory.is_dir()
    shutil.rmtree(directory, ignore_errors=True)
    return existed
