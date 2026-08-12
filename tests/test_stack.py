from pathlib import Path
from types import SimpleNamespace

import yaml

from pattern_explorer.orchestration.stack import compose_up, profile_services


class FakeCompose:
    def __init__(self):
        self.up_calls = []

    def up(self, **kwargs):
        self.up_calls.append(kwargs)

    def ps(self, **kwargs):
        return []


def test_profiles_resolve_to_concrete_compose_components():
    assert profile_services(["single"]) == ["ch"]
    services = profile_services(["single", "postgres", "s3", "peerdb"])
    assert "ch" in services
    assert "postgres" in services
    assert "minio" in services
    assert "peerdb-catalog" in services
    assert "peerdb-flow-worker" in services
    assert "peerdb-server" in services


def test_compose_start_reports_each_pending_component_and_completion():
    compose = FakeCompose()
    dc = SimpleNamespace(compose=compose)
    messages = []

    compose_up(dc, ["single", "postgres"], report=messages.append)

    assert compose.up_calls == [{"detach": True, "wait": True}]
    assert messages == [
        "INFRA   start · 2 components",
        "INFRA   ch · pending",
        "INFRA   postgres · pending",
        "INFRA   all components ready",
    ]


def test_clickhouse_http_and_native_ports_are_published_to_the_host():
    compose = yaml.safe_load(Path("compose/stack.yml").read_text())
    expected = {
        "ch": {"8123:8123", "9000:9000"},
        "ch-01": {"8123:8123", "9000:9000"},
        "ch-02": {"8124:8123", "9001:9000"},
        "ch-s1": {"8123:8123", "9000:9000"},
        "ch-s2": {"8124:8123", "9001:9000"},
        "ch-cdc": {"8123:8123", "9000:9000"},
    }

    for service, ports in expected.items():
        assert set(compose["services"][service]["ports"]) == ports
