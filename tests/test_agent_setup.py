from pathlib import Path

import pytest

from integrations.agent_setup import (
    AgentSetupError,
    install_skill_link,
    validate_mcp_adapter,
    validate_skill,
)


def test_repository_agent_adapters_are_valid():
    assert validate_skill() == []
    assert validate_mcp_adapter("codex") == []
    assert validate_mcp_adapter("claude") == []


def test_skill_link_is_idempotent(tmp_path):
    source = tmp_path / "source" / "clickhouse-pattern-lab"
    source.mkdir(parents=True)
    skills_dir = tmp_path / "client" / "skills"

    target, created = install_skill_link(skills_dir, source)
    same_target, created_again = install_skill_link(skills_dir, source)

    assert created is True
    assert created_again is False
    assert same_target == target
    assert target.resolve() == source.resolve()


def test_skill_link_refuses_to_overwrite(tmp_path):
    source = tmp_path / "source" / "clickhouse-pattern-lab"
    source.mkdir(parents=True)
    skills_dir = tmp_path / "client" / "skills"
    target = skills_dir / "clickhouse-pattern-lab"
    target.mkdir(parents=True)

    with pytest.raises(AgentSetupError, match="refusing to overwrite"):
        install_skill_link(skills_dir, source)
