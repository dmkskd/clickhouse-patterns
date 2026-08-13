"""Local HTTP control plane for the interactive Pattern Explorer."""
from __future__ import annotations

import errno
import json
import hashlib
import secrets
import threading
import webbrowser
from collections import deque
from datetime import datetime, timezone
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ..orchestration import session as sessions
from ..rendering.site import (
    EXPLORER_DIR,
    _browser_pattern,
    explorer_catalog_json,
    parse_resource_graph,
)
from ..orchestration.lifecycle import (
    get_session_status,
    run_session,
    stop_session,
    validate_and_record_session,
)
from ..catalog.manifest import discover_patterns, discover_workspace_patterns, load_pattern
from ..orchestration.nodes import connect
from ..orchestration.topology import compose_topology
from ..logs import configure_logging
from .resource_readers import RESOURCE_READERS, ReaderContext



def _browser_revision() -> str:
    """Fingerprint the live browser sources and compiled catalog data."""
    digest = hashlib.sha256()
    for name in (
        "index.html", "app.css", "util.js", "diagram.js", "topology.js",
        "session.js", "app.js",
    ):
        digest.update((EXPLORER_DIR / name).read_bytes())
    digest.update(explorer_catalog_json().encode())
    return digest.hexdigest()


class ExplorerConflict(RuntimeError):
    """A requested browser operation conflicts with current session state."""


class EventStream:
    def __init__(self, limit: int = 200):
        self._events: deque[dict] = deque(maxlen=limit)
        self._sequence = 0
        self._condition = threading.Condition()

    def publish(self, event_type: str, payload: dict, slug: str | None = None) -> dict:
        with self._condition:
            self._sequence += 1
            event = {
                "type": event_type,
                "sequence": self._sequence,
                "session": slug,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "payload": payload,
            }
            self._events.append(event)
            self._condition.notify_all()
            return event

    def after(self, sequence: int, timeout: float = 15.0) -> list[dict]:
        with self._condition:
            events = [item for item in self._events if item["sequence"] > sequence]
            if events:
                return events
            self._condition.wait(timeout)
            return [item for item in self._events if item["sequence"] > sequence]

    def recent(self, limit: int = 30) -> list[dict]:
        with self._condition:
            return list(self._events)[-limit:]

    def next_sequence(self) -> int:
        with self._condition:
            return self._sequence + 1


class ExplorerController:
    """Translate narrow browser commands into shared lifecycle calls."""

    def __init__(self):
        self.events = EventStream()
        self._state_lock = threading.Lock()
        self._operation: dict | None = None

    def catalog(self) -> dict:
        patterns = [*discover_patterns(), *discover_workspace_patterns()]
        return {"patterns": [_browser_pattern(pattern) for pattern in patterns]}

    def inspect_resource(self, slug: str, resource_key: str, object_key: str | None = None) -> dict:
        """Dispatch a declared live resource to its type-specific, read-only reader."""
        status = get_session_status()
        if status is None:
            raise ExplorerConflict("start this pattern to inspect its live resources")
        if status.session.slug != slug:
            raise ExplorerConflict(
                f"{status.session.slug} is running; open that pattern to inspect live resources"
            )
        if not status.reachable:
            raise ExplorerConflict("the active ClickHouse node is not reachable")

        pattern = sessions.load_session_pattern(status.session)
        graph = parse_resource_graph(pattern.graph or "")
        resource = graph.resources.get(resource_key)
        if resource is None:
            raise ValueError("resource is not declared by this pattern")
        reader = RESOURCE_READERS.reader_for(resource.kind)
        if reader is None:
            raise ValueError(f"no live reader is registered for `{resource.kind}` resources")
        try:
            return reader.inspect(
                ReaderContext(
                    resource=resource,
                    session=status.session,
                    source_changed=getattr(status, "source_changed", False),
                    clickhouse_client=lambda: connect(status.session.driver_node),
                ),
                object_key=object_key,
            )
        except ValueError as exc:
            if resource.kind in {"kafka-table", "mv", "refreshable-mv", "distributed", "mergetree", "replicated-mergetree", "keepermap", "remote-table"} and "is not present in the live ClickHouse session" in str(exc):
                raise ExplorerConflict(str(exc)) from exc
            raise

    def topology(self, slug: str) -> dict:
        """Return the live container wiring behind one pattern's profiles.

        Restricted to the running pattern. `docker compose config` alone would
        describe any pattern's declared services, but all patterns share the one
        `chp` Compose project, so container state read while a *different*
        pattern is up belongs to that other pattern. Rather than show a topology
        that is half declaration and half someone else's containers, the
        physical view exists only for the session that is actually running.
        """
        pattern = load_pattern(slug)
        profiles = list(pattern.profiles or [])
        if not profiles:
            raise ExplorerConflict(
                "this pattern declares no infrastructure profiles, so it has no "
                "container topology"
            )
        active = sessions.read_session()
        if active is None:
            raise ExplorerConflict("start this pattern to see its containers")
        if active.slug != slug:
            raise ExplorerConflict(
                f"{active.slug} is running; open that pattern to see its containers"
            )
        payload = compose_topology(profiles)
        payload["pattern"] = slug
        return payload

    def snapshot(self) -> dict:
        with self._state_lock:
            operation = dict(self._operation) if self._operation else None
        # A missing ClickHouse endpoint is expected while browser-owned lifecycle
        # operations are starting or tearing down infrastructure. Progress events
        # and polling both request snapshots, so probing here would emit the same
        # connection-refused warning many times without adding useful information.
        infrastructure_changing = bool(
            operation
            and operation.get("status") == "running"
            and operation.get("name") in {"run", "stop", "switch"}
        )
        status = get_session_status(probe_reachability=not infrastructure_changing)
        slug = (
            status.session.slug
            if status
            else operation.get("pattern") if operation else None
        )
        events = self.events.recent(100)
        if slug:
            events = [event for event in events if event["session"] == slug]
        if operation and operation.get("event_sequence"):
            events = [
                event
                for event in events
                if event["sequence"] >= operation["event_sequence"]
            ]
        return {
            "active": status is not None,
            "session": status.as_dict() if status else None,
            "operation": operation,
            "events": events[-30:],
        }

    def _reporter(self, slug: str):
        def report(message: str) -> None:
            stage, _, detail = message.partition(" ")
            self.events.publish(
                "progress",
                {"stage": stage.strip().lower(), "message": message, "detail": detail.strip()},
                slug,
            )

        return report

    def _start_operation(self, name: str, slug: str | None, action) -> dict:
        with self._state_lock:
            if self._operation and self._operation["status"] == "running":
                raise ExplorerConflict(
                    f"{self._operation['name']} is already in progress"
                )
            operation = {
                "name": name,
                "pattern": slug,
                "status": "running",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "event_sequence": self.events.next_sequence(),
                "error": None,
            }
            self._operation = operation

        self.events.publish("operation", operation, slug)

        def work() -> None:
            try:
                result = action()
                if result is not None and hasattr(result, "passed"):
                    self.events.publish(
                        "validation",
                        {
                            "passed": result.passed,
                            "updated": result.updated,
                            "detail": result.detail,
                        },
                        slug,
                    )
                    if not result.passed:
                        raise RuntimeError(result.detail or "validation failed")
            except Exception as exc:  # noqa: BLE001 - API boundary reports failures
                error = f"{type(exc).__name__}: {str(exc).splitlines()[0]}"
                with self._state_lock:
                    self._operation = {
                        **operation,
                        "status": "failed",
                        "error": error,
                        "finished_at": datetime.now(timezone.utc).isoformat(),
                    }
                self.events.publish("operation", self._operation, slug)
            else:
                with self._state_lock:
                    self._operation = {
                        **operation,
                        "status": "complete",
                        "finished_at": datetime.now(timezone.utc).isoformat(),
                    }
                self.events.publish("operation", self._operation, slug)
            finally:
                snapshot = self.snapshot()
                snapshot.pop("events", None)
                self.events.publish("session", snapshot, slug)

        threading.Thread(target=work, name=f"pattern-{name}", daemon=True).start()
        return operation

    def run(self, slug: str) -> dict:
        pattern = load_pattern(slug)
        active = sessions.read_session()
        if active is not None:
            raise ExplorerConflict(
                f"{active.slug} already has a {active.phase} session; stop it first"
            )
        return self._start_operation(
            "run", slug, lambda: run_session(pattern, report=self._reporter(slug))
        )

    def switch(self, slug: str) -> dict:
        """Replace the browser-owned session in one ordered operation."""
        pattern = load_pattern(slug)
        pattern.require_runnable()
        active = sessions.read_session(required=True)
        if active.owner == "terminal":
            raise ExplorerConflict(
                "this session is owned by `just run`; finish it in that terminal"
            )
        if active.slug == slug:
            raise ExplorerConflict(f"{slug} is already running")

        report = self._reporter(slug)

        def replace():
            stop_session(report=report)
            return run_session(pattern, report=report)

        return self._start_operation("switch", slug, replace)

    def validate(self) -> dict:
        active = sessions.read_session(required=True)
        return self._start_operation(
            "validate",
            active.slug,
            lambda: validate_and_record_session(report=self._reporter(active.slug)),
        )

    def stop(self) -> dict:
        active = sessions.read_session(required=True)
        if active.owner == "terminal":
            raise ExplorerConflict(
                "this session is owned by `just run`; finish it in that terminal"
            )
        return self._start_operation(
            "stop", active.slug, lambda: stop_session(report=self._reporter(active.slug))
        )


class ExplorerRequestHandler(SimpleHTTPRequestHandler):
    server_version = "ClickHousePatternExplorer/0.1"

    def handle(self) -> None:
        try:
            super().handle()
        except OSError:
            # EventSource reconnects and closed browser tabs are normal clients.
            return

    @property
    def controller(self) -> ExplorerController:
        return self.server.controller  # type: ignore[attr-defined]

    @property
    def token(self) -> str:
        return self.server.token  # type: ignore[attr-defined]

    def log_message(self, _format: str, *_args) -> None:
        return

    def end_headers(self) -> None:
        route = urlparse(self.path).path
        if route == "/" or Path(route).suffix in {".html", ".css", ".js"}:
            self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def _json(self, status: int, value: dict) -> None:
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _javascript(self, value: str) -> None:
        body = value.encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/javascript; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        origin = self.headers.get("Origin")
        if origin:
            parsed = urlparse(origin)
            if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
                return False
        return secrets.compare_digest(
            self.headers.get("X-Explorer-Token", ""), self.token
        )

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        parsed_request = urlparse(self.path)
        route = parsed_request.path
        if route == "/catalog.js":
            self._javascript(
                f"window.CLICKHOUSE_PATTERN_CATALOG = {explorer_catalog_json()};\n"
            )
            return
        if route == "/api/config":
            self._json(HTTPStatus.OK, {"interactive": True, "token": self.token})
            return
        if route == "/api/revision":
            self._json(HTTPStatus.OK, {"revision": _browser_revision()})
            return
        if route == "/api/patterns":
            self._json(HTTPStatus.OK, self.controller.catalog())
            return
        if route == "/api/session":
            self._json(HTTPStatus.OK, self.controller.snapshot())
            return
        if route == "/api/resource":
            if not self._authorized():
                self._json(
                    HTTPStatus.FORBIDDEN,
                    {"error": "invalid explorer token or origin"},
                )
                return
            try:
                query = parse_qs(parsed_request.query)
                slug = query.get("pattern", [""])[0]
                resource_key = query.get("resource", [""])[0]
                if not slug or not resource_key:
                    raise ValueError("`pattern` and `resource` are required")
                object_key = query.get("object", [None])[0]
                if object_key is None:
                    payload = self.controller.inspect_resource(slug, resource_key)
                else:
                    payload = self.controller.inspect_resource(slug, resource_key, object_key)
            except ExplorerConflict as exc:
                self._json(HTTPStatus.CONFLICT, {"error": str(exc)})
                return
            except (ValueError, sessions.SessionError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            except Exception as exc:  # noqa: BLE001 - narrow JSON error boundary
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"error": f"{type(exc).__name__}: {str(exc).splitlines()[0]}"},
                )
                return
            self._json(HTTPStatus.OK, payload)
            return
        if route == "/api/topology":
            if not self._authorized():
                self._json(
                    HTTPStatus.FORBIDDEN,
                    {"error": "invalid explorer token or origin"},
                )
                return
            try:
                slug = parse_qs(parsed_request.query).get("pattern", [""])[0]
                if not slug:
                    raise ValueError("`pattern` is required")
                payload = self.controller.topology(slug)
            except ExplorerConflict as exc:
                self._json(HTTPStatus.CONFLICT, {"error": str(exc)})
                return
            except FileNotFoundError:
                self._json(HTTPStatus.NOT_FOUND, {"error": f"no pattern '{slug}'"})
                return
            except (ValueError, sessions.SessionError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            except Exception as exc:  # noqa: BLE001 - narrow JSON error boundary
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"error": f"{type(exc).__name__}: {str(exc).splitlines()[0]}"},
                )
                return
            self._json(HTTPStatus.OK, payload)
            return
        if route == "/api/events":
            self._events()
            return
        super().do_GET()

    def _events(self) -> None:
        try:
            sequence = int(self.headers.get("Last-Event-ID", "0"))
        except ValueError:
            sequence = 0
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.close_connection = True
        self.end_headers()
        try:
            while True:
                events = self.controller.events.after(sequence)
                if not events:
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
                    continue
                for event in events:
                    sequence = event["sequence"]
                    payload = json.dumps(event, separators=(",", ":"))
                    self.wfile.write(
                        f"id: {sequence}\nevent: {event['type']}\ndata: {payload}\n\n".encode()
                    )
                self.wfile.flush()
        except OSError:
            return

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        if not self._authorized():
            self._json(HTTPStatus.FORBIDDEN, {"error": "invalid explorer token or origin"})
            return
        route = urlparse(self.path).path
        try:
            length = min(int(self.headers.get("Content-Length", "0")), 16_384)
            payload = json.loads(self.rfile.read(length) or b"{}")
            if route == "/api/session/run":
                slug = payload.get("pattern")
                if not isinstance(slug, str) or not slug:
                    raise ValueError("`pattern` is required")
                operation = self.controller.run(slug)
            elif route == "/api/session/switch":
                slug = payload.get("pattern")
                if not isinstance(slug, str) or not slug:
                    raise ValueError("`pattern` is required")
                operation = self.controller.switch(slug)
            elif route == "/api/session/validate":
                operation = self.controller.validate()
            elif route == "/api/session/stop":
                operation = self.controller.stop()
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "unknown API route"})
                return
        except ExplorerConflict as exc:
            self._json(HTTPStatus.CONFLICT, {"error": str(exc)})
            return
        except (ValueError, sessions.SessionError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        except Exception as exc:  # noqa: BLE001 - narrow JSON error boundary
            self._json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": f"{type(exc).__name__}: {str(exc).splitlines()[0]}"},
            )
            return
        self._json(HTTPStatus.ACCEPTED, {"operation": operation})


class ExplorerHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, handler, controller: ExplorerController, token: str):
        super().__init__(address, handler)
        self.controller = controller
        self.token = token


def create_server(
    host: str = "127.0.0.1",
    port: int = 8765,
) -> ExplorerHTTPServer:
    controller = ExplorerController()
    token = secrets.token_urlsafe(24)
    handler = partial(ExplorerRequestHandler, directory=str(EXPLORER_DIR))
    return ExplorerHTTPServer((host, port), handler, controller, token)


def serve_explorer(port: int = 8765, open_browser: bool = True) -> int:
    configure_logging()
    host = "127.0.0.1"
    try:
        server = create_server(host=host, port=port)
    except OSError as exc:
        if exc.errno in (errno.EADDRINUSE, errno.EACCES):
            reason = (
                "already in use"
                if exc.errno == errno.EADDRINUSE
                else "not permitted"
            )
            print(f"FAIL: cannot start the explorer — {host}:{port} is {reason}.")
            print(f"  hint  another explorer may be running, or free the port; "
                  f"or choose another: just explore --port {port + 1}")
            return 1
        raise
    host, actual_port = server.server_address[:2]
    url = f"http://{host}:{actual_port}/"
    print("PATTERN EXPLORER")
    print(f"  browser  {url}")
    print("  session  shared with `just status`, `just validate`, and `just stop`")
    print("  finish   Ctrl+C stops the web service; running pattern sessions remain live")
    if open_browser:
        threading.Timer(0.2, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\nExplorer service stopped; any active pattern is still running.")
    finally:
        server.server_close()
    return 0
