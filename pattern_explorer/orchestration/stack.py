"""Bring the infra up/down by driving compose with the pattern's profiles."""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, TYPE_CHECKING

from python_on_whales import DockerClient
import yaml

if TYPE_CHECKING:
    from ..catalog.manifest import Pattern

COMPOSE_FILE = Path(__file__).resolve().parents[2] / "compose" / "stack.yml"
PROJECT = "chp"   # compose project name: namespaces containers, networks, volumes
Reporter = Callable[[str], None]


def pattern_compose_file(pattern: "Pattern") -> Path | None:
    """Write a small Compose overlay for a pattern's additive service customizations.

    Carries two kinds of mounts, both additive to the shared stack:
    CH XML fragments into config.d/users.d, and database init scripts into a
    service's /docker-entrypoint-initdb.d (run once on a fresh container, after
    the stack's shared init.sql seed thanks to the zz- sort prefix).
    """
    if not pattern.clickhouse_config and not pattern.service_init:
        return None
    services: dict[str, dict] = {}
    for item in pattern.clickhouse_config:
        source = (pattern.dir / item.file).resolve()
        target = f"/etc/clickhouse-server/{item.directory}/99-pattern-{item.destination_name}"
        service = services.setdefault(item.node, {"volumes": [], "depends_on": {}})
        service["volumes"].append(f"{source}:{target}:ro")
        for dependency in item.depends_on:
            service["depends_on"][dependency] = {"condition": "service_healthy"}
    for item in pattern.service_init:
        source = (pattern.dir / item.file).resolve()
        target = f"/docker-entrypoint-initdb.d/zz-pattern-{item.destination_name}"
        service = services.setdefault(item.service, {"volumes": [], "depends_on": {}})
        service["volumes"].append(f"{source}:{target}:ro")
    path = RUNTIME_OVERRIDES / f"{pattern.slug}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"services": services}, sort_keys=True))
    return path


RUNTIME_OVERRIDES = Path(__file__).resolve().parents[2] / ".runtime" / "compose-overrides"


def docker(profiles: list[str], pattern: "Pattern | None" = None) -> DockerClient:
    compose_files = [str(COMPOSE_FILE)]
    if pattern:
        overlay = pattern_compose_file(pattern)
        if overlay:
            compose_files.append(str(overlay))
    return DockerClient(
        compose_files=compose_files,
        compose_profiles=profiles,
        compose_project_name=PROJECT,
    )


def all_profiles() -> list[str]:
    """Every profile the stack declares, for teardown that must miss nothing."""
    compose = yaml.safe_load(COMPOSE_FILE.read_text())
    names: set[str] = set()
    for config in compose.get("services", {}).values():
        names.update(config.get("profiles", []))
    return sorted(names)


def profile_services(profiles: list[str]) -> list[str]:
    """Return Compose services enabled by the selected profiles."""
    compose = yaml.safe_load(COMPOSE_FILE.read_text())
    selected = set(profiles)
    return [
        name
        for name, config in compose.get("services", {}).items()
        if selected.intersection(config.get("profiles", []))
    ]


def _service_name(container) -> str:
    name = container.name.removeprefix(f"{PROJECT}-")
    return name.rsplit("-", 1)[0]


def _service_state(container) -> str:
    state = container.state
    health = getattr(state, "health", None)
    health_status = getattr(health, "status", None)
    return health_status or state.status or "created"


def _report_states(dc: DockerClient, report: Reporter, previous: dict[str, str]) -> None:
    try:
        containers = dc.compose.ps(all=True)
    except Exception:  # noqa: BLE001 - Compose may be between create phases
        return
    for container in containers:
        try:
            service = _service_name(container)
            state = _service_state(container)
        except Exception:  # noqa: BLE001 - a container can disappear while polling
            continue
        if previous.get(service) != state:
            previous[service] = state
            report(f"INFRA   {service} · {state}")


def compose_up(
    dc: DockerClient,
    profiles: list[str],
    report: Reporter | None = None,
) -> None:
    """Start Compose and report real per-service state transitions."""
    if report is None:
        dc.compose.up(detach=True, wait=True)
        return

    services = profile_services(profiles)
    report(f"INFRA   start · {len(services)} components")
    for service in services:
        report(f"INFRA   {service} · pending")

    previous: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(dc.compose.up, detach=True, wait=True)
        while not future.done():
            _report_states(dc, report, previous)
            time.sleep(0.75)
        future.result()
    _report_states(dc, report, previous)
    report("INFRA   all components ready")


def compose_down(
    dc: DockerClient,
    profiles: list[str],
    report: Reporter | None = None,
) -> None:
    """Stop Compose with concise per-service cleanup milestones."""
    services = profile_services(profiles)
    if report:
        for service in services:
            report(f"INFRA   {service} · stopping")
    dc.compose.down(volumes=True, remove_orphans=True)
    if report:
        report("INFRA   components and volumes removed")


@contextmanager
def stack(
    profiles: list[str],
    pattern: "Pattern | None" = None,
    keep: bool = False,
    report: Reporter | None = None,
):
    """Context manager: `up --wait` on enter, `down -v` on exit (unless keep)."""
    dc = docker(profiles, pattern)
    compose_up(dc, profiles, report=report)
    try:
        yield dc
    finally:
        if not keep:
            compose_down(dc, profiles, report=report)
