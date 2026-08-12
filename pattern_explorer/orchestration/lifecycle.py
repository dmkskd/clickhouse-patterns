"""Lifecycle operations for one inspectable, live pattern session."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from . import session as sessions
from ..catalog.manifest import Pattern
from .nodes import connect
from .runner import Reporter, Result, prepare_pattern, validate_pattern
from .stack import compose_down, compose_up, docker

_log = logging.getLogger(__name__)

# Reachability is probed on every status poll, so an endpoint that stays down
# would otherwise repeat the same warning forever. Track the last reported state
# per node and log only the transitions (down, still down after a while, back up).
_REPEAT_WARNING_AFTER = 60.0
_reachability: dict[str, tuple[str, float, int]] = {}


def _unreachable_reason(exc: Exception) -> str:
    """Summarise a connection failure without the nested urllib3 wrapping."""
    text = str(exc)
    if "Connection refused" in text or "Failed to establish a new connection" in text:
        return "connection refused (is the docker stack running?)"
    return text.splitlines()[0]


def _note_unreachable(node: str, exc: Exception) -> None:
    reason = _unreachable_reason(exc)
    previous = _reachability.get(node)
    now = time.monotonic()
    if previous and previous[0] == reason:
        _, since, suppressed = previous
        if now - since < _REPEAT_WARNING_AFTER:
            _reachability[node] = (reason, since, suppressed + 1)
            _log.debug("ClickHouse node %r still unreachable: %s", node, reason)
            return
        _log.warning(
            "ClickHouse node %r still unreachable after %.0fs: %s (%d probes since)",
            node, now - since, reason, suppressed + 1,
        )
    else:
        _log.warning("ClickHouse node %r unreachable: %s", node, reason)
    _reachability[node] = (reason, now, 0)


def _note_reachable(node: str) -> None:
    if _reachability.pop(node, None) is not None:
        _log.info("ClickHouse node %r reachable again", node)


@dataclass(frozen=True)
class SessionStatus:
    session: sessions.Session
    reachable: bool
    source_changed: bool

    def as_dict(self) -> dict:
        return {
            **self.session.as_dict(),
            "reachable": self.reachable,
            "source_changed": self.source_changed,
        }


def _emit(report: Reporter | None, message: str) -> None:
    if report:
        report(message)


def _start_session(
    pattern: Pattern,
    report: Reporter | None = None,
    owner: str = "detached",
) -> sessions.Session:
    pattern.require_runnable()
    active = sessions.read_session()
    if active:
        raise sessions.SessionError(
            f"pattern {active.slug!r} already has a {active.phase} session; "
            "use `just reload` or `just stop` first"
        )

    current = sessions.new_session(pattern, owner=owner)
    sessions.write_session(current)
    try:
        dc = docker(pattern.profiles)
        compose_up(dc, pattern.profiles, report=report)
        prepare_pattern(pattern, report=report)
    except Exception as exc:
        failed = current.with_phase("failed", f"{type(exc).__name__}: {str(exc).splitlines()[0]}")
        sessions.write_session(failed)
        raise

    ready = current.with_phase("ready")
    sessions.write_session(ready)
    return ready


def start_session(
    pattern: Pattern,
    report: Reporter | None = None,
    owner: str = "detached",
) -> sessions.Session:
    with sessions.operation_lock():
        return _start_session(pattern, report=report, owner=owner)


def _validate_session(update: bool = False, report: Reporter | None = None) -> Result:
    active = sessions.read_session(required=True)
    pattern = sessions.load_session_pattern(active)
    return validate_pattern(pattern, update=update, report=report)


def validate_session(update: bool = False, report: Reporter | None = None) -> Result:
    with sessions.operation_lock():
        return _validate_session(update=update, report=report)


def validate_and_record_session(report: Reporter | None = None) -> Result:
    """Validate the active session and persist its browser-visible outcome."""
    with sessions.operation_lock():
        active = sessions.read_session(required=True)
        try:
            result = _validate_session(report=report)
        except Exception as exc:
            detail = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
            sessions.write_session(
                active.with_phase("failed", f"{type(exc).__name__}: {detail}")
            )
            raise
        if result.passed:
            sessions.write_session(active.with_phase("validated"))
        else:
            detail = result.detail.splitlines()[0] if result.detail else "validation failed"
            sessions.write_session(active.with_phase("failed", detail))
        return result


def run_session(pattern: Pattern, report: Reporter | None = None) -> Result:
    """Prepare, validate, and leave a browser-owned session available."""
    with sessions.operation_lock():
        _start_session(pattern, report=report, owner="browser")
        try:
            result = _validate_session(report=report)
        except Exception as exc:
            active = sessions.read_session()
            if active is not None and active.slug == pattern.slug:
                detail = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
                sessions.write_session(
                    active.with_phase("failed", f"{type(exc).__name__}: {detail}")
                )
            raise

        active = sessions.read_session(required=True)
        if result.passed:
            sessions.write_session(active.with_phase("validated"))
        else:
            detail = result.detail.splitlines()[0] if result.detail else "validation failed"
            sessions.write_session(active.with_phase("failed", detail))
        return result


def _stop_session(report: Reporter | None = None) -> sessions.Session:
    active = sessions.read_session(required=True)
    dc = docker(active.profiles)
    compose_down(dc, active.profiles, report=report)
    sessions.clear_session()
    return active


def stop_session(report: Reporter | None = None) -> sessions.Session:
    with sessions.operation_lock():
        return _stop_session(report=report)


def reload_session(report: Reporter | None = None) -> sessions.Session:
    with sessions.operation_lock():
        return _reload_session(report=report)


def _reload_session(report: Reporter | None = None) -> sessions.Session:
    active = sessions.read_session(required=True)
    # Validate edited manifests before destroying the inspectable environment.
    pattern = sessions.load_session_pattern(active)
    _stop_session(report=report)
    return _start_session(pattern, report=report, owner=active.owner)


def get_session_status(*, probe_reachability: bool = True) -> SessionStatus | None:
    active = sessions.read_session()
    if active is None:
        return None

    reachable = False
    if probe_reachability:
        try:
            reachable = bool(connect(active.driver_node).ping())
        except Exception as exc:  # noqa: BLE001 - status reports an unavailable endpoint
            # Capture the real cause (host + underlying error) instead of letting the
            # driver's generic "Unexpected Http Driver Exception" be all that surfaces.
            _note_unreachable(active.driver_node, exc)
        else:
            if reachable:
                _note_reachable(active.driver_node)

    try:
        changed = (
            sessions.pattern_digest(sessions.load_session_pattern(active))
            != active.source_digest
        )
    except Exception:  # noqa: BLE001 - invalid edits still count as source drift
        changed = True

    return SessionStatus(active, reachable=reachable, source_changed=changed)
