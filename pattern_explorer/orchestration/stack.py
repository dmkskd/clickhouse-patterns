"""Bring the infra up/down by driving compose with the pattern's profiles."""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

from python_on_whales import DockerClient
import yaml

COMPOSE_FILE = Path(__file__).resolve().parents[2] / "compose" / "stack.yml"
PROJECT = "chp"   # compose project name: namespaces containers, networks, volumes
Reporter = Callable[[str], None]


def docker(profiles: list[str]) -> DockerClient:
    return DockerClient(
        compose_files=[str(COMPOSE_FILE)],
        compose_profiles=profiles,
        compose_project_name=PROJECT,
    )


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
    keep: bool = False,
    report: Reporter | None = None,
):
    """Context manager: `up --wait` on enter, `down -v` on exit (unless keep)."""
    dc = docker(profiles)
    compose_up(dc, profiles, report=report)
    try:
        yield dc
    finally:
        if not keep:
            compose_down(dc, profiles, report=report)
