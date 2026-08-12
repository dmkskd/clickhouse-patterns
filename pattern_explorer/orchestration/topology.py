"""Physical view of a pattern: the Compose services behind its profiles.

`pattern.yaml` describes the logical architecture (tables, views, flows). The
container wiring that carries it lives in `compose/stack.yml`, selected by the
pattern's profiles. Rather than restate that wiring in the manifest, this module
reads it back from Compose itself:

  declared  `docker compose config`  fully resolved after anchors, profile
            filtering, and interpolation: images, ports, binds, depends_on
  live      `docker compose ps`      container names, status, health

The two are merged per service, so a pattern that is not running still renders
its declared topology, and a running one gains state.
"""
from __future__ import annotations

from pathlib import Path

from .stack import COMPOSE_FILE, PROJECT, docker

REPO_ROOT = COMPOSE_FILE.resolve().parents[1]
_MODEL_CACHE: dict[tuple, dict] = {}


def _relative_source(source: str) -> str:
    """Show bind sources as repo-relative paths; leave volume names alone."""
    if not source.startswith("/"):
        return source
    try:
        return str(Path(source).relative_to(REPO_ROOT))
    except ValueError:
        return source


def _ports(service: dict) -> list[dict]:
    ports = []
    for port in service.get("ports") or []:
        published = str(port.get("published") or "")
        target = port.get("target")
        if not published or target is None:
            continue
        ports.append(
            {
                "host": published,
                "container": target,
                "protocol": port.get("protocol") or "tcp",
            }
        )
    return ports


def _mounts(service: dict) -> list[dict]:
    mounts = []
    for volume in service.get("volumes") or []:
        if isinstance(volume, str):  # short syntax survives some Compose versions
            source, _, target = volume.partition(":")
            mounts.append(
                {
                    "type": "bind" if source.startswith((".", "/")) else "volume",
                    "source": _relative_source(source),
                    "target": target.split(":")[0],
                    "read_only": volume.endswith(":ro"),
                }
            )
            continue
        mounts.append(
            {
                "type": volume.get("type", "volume"),
                "source": _relative_source(str(volume.get("source") or "")),
                "target": volume.get("target") or "",
                "read_only": bool(volume.get("read_only")),
            }
        )
    return mounts


def _healthcheck(service: dict) -> str | None:
    check = service.get("healthcheck") or {}
    test = check.get("test")
    if not test:
        return None
    if isinstance(test, list):
        # ["CMD", "clickhouse-client", "--query", "SELECT 1"] -> the command only
        test = " ".join(test[1:] if test and test[0] in {"CMD", "CMD-SHELL"} else test)
    return str(test)


def _depends_on(service: dict) -> list[tuple[str, str]]:
    """Return (dependency, condition) pairs in both Compose spellings."""
    depends = service.get("depends_on")
    if not depends:
        return []
    if isinstance(depends, list):
        return [(name, "service_started") for name in depends]
    return [
        (name, (config or {}).get("condition", "service_started"))
        for name, config in depends.items()
    ]


def _service_of(container) -> str | None:
    labels = getattr(getattr(container, "config", None), "labels", None) or {}
    service = labels.get("com.docker.compose.service")
    if service:
        return service
    name = getattr(container, "name", "")
    if not name.startswith(f"{PROJECT}-"):
        return None
    return name.removeprefix(f"{PROJECT}-").rsplit("-", 1)[0]


def _live_state(profiles: list[str]) -> dict[str, dict]:
    """Map service name to its running container's state, when the stack is up."""
    try:
        containers = docker(profiles).compose.ps(all=True)
    except Exception:  # noqa: BLE001 - Docker may be absent or the project down
        return {}
    states: dict[str, dict] = {}
    for container in containers:
        try:
            service = _service_of(container)
            if service is None:
                continue
            state = container.state
            health = getattr(getattr(state, "health", None), "status", None)
            states[service] = {
                "container": container.name,
                "status": state.status or "created",
                "health": health,
            }
        except Exception:  # noqa: BLE001 - a container can vanish mid-poll
            continue
    return states


def _declared_model(profiles: list[str]) -> dict:
    """Resolved Compose model, cached per profile set and per stack.yml mtime.

    `docker compose config` shells out and costs a few hundred milliseconds. The
    file changes rarely and the browser re-asks on every session event, so cache
    on content age and let live state be the part that is always re-read.
    """
    key = (tuple(profiles), COMPOSE_FILE.stat().st_mtime_ns)
    cached = _MODEL_CACHE.get(key)
    if cached is None:
        _MODEL_CACHE.clear()
        cached = docker(profiles).compose.config(return_json=True)
        _MODEL_CACHE[key] = cached
    return cached


def compose_topology(profiles: list[str]) -> dict:
    """Return the container graph for `profiles`, annotated with live state."""
    model = _declared_model(profiles)
    services = model.get("services") or {}
    live = _live_state(profiles)

    nodes = []
    edges = []
    for name, service in sorted(services.items()):
        command = service.get("command")
        nodes.append(
            {
                "name": name,
                "image": service.get("image") or "",
                # What this container is for, when the image and name do not say
                # it. Two Postgres services in one stack (a CDC source and
                # PeerDB's catalog) are indistinguishable without this.
                "role": (service.get("labels") or {}).get("chp.role", ""),
                "ports": _ports(service),
                "mounts": _mounts(service),
                "networks": sorted((service.get("networks") or {"default": None}).keys()),
                "healthcheck": _healthcheck(service),
                "command": " ".join(command) if isinstance(command, list) else command,
                "state": live.get(name),
            }
        )
        for dependency, condition in _depends_on(service):
            if dependency in services:
                edges.append(
                    {"source": dependency, "target": name, "condition": condition}
                )

    networks = [
        {"key": key, "name": (config or {}).get("name") or key}
        for key, config in (model.get("networks") or {}).items()
    ]
    return {
        "project": PROJECT,
        "profiles": profiles,
        "compose_file": str(COMPOSE_FILE.relative_to(REPO_ROOT)),
        "services": nodes,
        "edges": edges,
        "networks": networks,
        "live": bool(live),
    }
