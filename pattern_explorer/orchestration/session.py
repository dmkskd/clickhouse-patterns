"""Persist the single live pattern session used by both interfaces."""
from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

import fcntl

from ..catalog.manifest import Pattern, load_pattern, load_pattern_dir
from .nodes import NODE_HTTP_PORT

_ROOT = Path(__file__).resolve().parents[2]
STATE_FILE = _ROOT / ".runtime" / "session.json"


class SessionError(RuntimeError):
    """The requested lifecycle operation is incompatible with session state."""


@dataclass(frozen=True)
class Session:
    slug: str
    profiles: list[str]
    driver_node: str
    started_at: str
    source_digest: str
    pattern_dir: str = ""
    pattern_location: str = "library"
    phase: str = "starting"
    error: str | None = None
    owner: str = "detached"

    @property
    def driver_port(self) -> int:
        return NODE_HTTP_PORT[self.driver_node]

    @property
    def driver_url(self) -> str:
        return f"http://localhost:{self.driver_port}"

    @property
    def schema_url(self) -> str:
        return f"{self.driver_url}/schema"

    @property
    def play_url(self) -> str:
        return f"{self.driver_url}/play"

    def with_phase(self, phase: str, error: str | None = None) -> Session:
        return replace(self, phase=phase, error=error)

    def as_dict(self) -> dict:
        return {
            **asdict(self),
            "driver_port": self.driver_port,
            "driver_url": self.driver_url,
            "schema_url": self.schema_url,
            "play_url": self.play_url,
        }


def pattern_digest(pattern: Pattern) -> str:
    """Fingerprint the authored files so status can detect edits needing reload."""
    digest = hashlib.sha256()
    for path in sorted(p for p in pattern.dir.rglob("*") if p.is_file()):
        if "__pycache__" in path.parts:
            continue
        digest.update(str(path.relative_to(pattern.dir)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def new_session(pattern: Pattern, owner: str = "detached") -> Session:
    return Session(
        slug=pattern.slug,
        profiles=list(pattern.profiles),
        driver_node=pattern.driver_node,
        started_at=datetime.now(timezone.utc).isoformat(),
        source_digest=pattern_digest(pattern),
        pattern_dir=str(pattern.dir.resolve()),
        pattern_location=pattern.location,
        owner=owner,
    )


def load_session_pattern(session: Session) -> Pattern:
    """Resolve the exact authored directory, with fallback for older sessions."""
    if session.pattern_dir:
        return load_pattern_dir(
            Path(session.pattern_dir),
            session.slug,
            session.pattern_location,
        )
    return load_pattern(session.slug)


def read_session(required: bool = False) -> Session | None:
    if not STATE_FILE.exists():
        if required:
            raise SessionError(
                "no active pattern; use `just run <pattern>` for interactive exploration "
                "or `just start <pattern>` for an advanced detached session"
            )
        return None
    return Session(**json.loads(STATE_FILE.read_text()))


def write_session(session: Session) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(asdict(session), indent=2) + "\n")
    temporary.replace(STATE_FILE)


def clear_session() -> None:
    STATE_FILE.unlink(missing_ok=True)


@contextmanager
def operation_lock():
    """Serialize lifecycle mutations across terminal and browser processes."""
    lock_file = STATE_FILE.with_name("lifecycle.lock")
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    with lock_file.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SessionError(
                "another pattern lifecycle operation is already in progress; "
                "wait for it to finish and try again"
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
