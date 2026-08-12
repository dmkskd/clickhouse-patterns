"""Install and inspect repository-local adapters for Agent Skills clients."""
from __future__ import annotations

import json
import os
import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SKILL_NAMES = ("clickhouse-pattern-lab", "clickhouse-pattern-author")
_MCP_NAME = "clickhouse-patterns"
_MCP_COMMAND = "uv"
_MCP_ARGS = [
    "run",
    "--no-project",
    "--with",
    "mcp-clickhouse",
    "--python",
    "3.12",
    "mcp-clickhouse",
]
_MCP_ENV = {
    "CLICKHOUSE_ALLOW_WRITE_ACCESS": "false",
    "CLICKHOUSE_HOST": "localhost",
    "CLICKHOUSE_PASSWORD": "",
    "CLICKHOUSE_PORT": "8123",
    "CLICKHOUSE_SECURE": "false",
    "CLICKHOUSE_USER": "default",
    "CLICKHOUSE_VERIFY": "false",
}


class AgentSetupError(RuntimeError):
    pass


@dataclass(frozen=True)
class AgentAdapter:
    name: str
    executable: str
    skills_dir: Path
    mcp_config: Path
    approval_note: str


_ADAPTERS = {
    "codex": AgentAdapter(
        name="codex",
        executable="codex",
        skills_dir=Path(".agents/skills"),
        mcp_config=Path(".codex/config.toml"),
        approval_note="restart Codex and trust this repository if prompted",
    ),
    "claude": AgentAdapter(
        name="claude",
        executable="claude",
        skills_dir=Path(".claude/skills"),
        mcp_config=Path(".mcp.json"),
        approval_note="approve the project MCP server when Claude prompts",
    ),
}


def _skill_source(repo_root: Path, skill_name: str) -> Path:
    return repo_root / "skills" / skill_name


def validate_skill(repo_root: Path = _REPO_ROOT) -> list[str]:
    errors = []
    for skill_name in _SKILL_NAMES:
        skill_dir = _skill_source(repo_root, skill_name)
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.is_file():
            errors.append(f"missing {skill_file}")
            continue
        text = skill_file.read_text()
        parts = text.split("---", 2)
        if len(parts) != 3 or parts[0].strip():
            errors.append(f"{skill_file} must begin with YAML frontmatter")
            continue
        metadata = yaml.safe_load(parts[1]) or {}
        if metadata.get("name") != skill_dir.name:
            errors.append(f"{skill_file}: skill name must match its parent directory")
        if not metadata.get("description"):
            errors.append(f"{skill_file}: skill description is required")
    return errors


def _mcp_entry(config_path: Path, agent: str) -> dict:
    if not config_path.is_file():
        raise AgentSetupError(f"missing MCP adapter {config_path}")
    if agent == "codex":
        data = tomllib.loads(config_path.read_text())
        return (data.get("mcp_servers") or {}).get(_MCP_NAME) or {}
    data = json.loads(config_path.read_text())
    return (data.get("mcpServers") or {}).get(_MCP_NAME) or {}


def validate_mcp_adapter(agent: str, repo_root: Path = _REPO_ROOT) -> list[str]:
    adapter = _ADAPTERS[agent]
    config_path = repo_root / adapter.mcp_config
    try:
        entry = _mcp_entry(config_path, agent)
    except (AgentSetupError, json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
        return [str(exc)]

    errors = []
    if entry.get("command") != _MCP_COMMAND:
        errors.append(f"{config_path}: {_MCP_NAME} command must be {_MCP_COMMAND!r}")
    if entry.get("args") != _MCP_ARGS:
        errors.append(f"{config_path}: {_MCP_NAME} arguments differ from the shared adapter")
    if entry.get("env") != _MCP_ENV:
        errors.append(f"{config_path}: {_MCP_NAME} must use the shared read-only environment")
    return errors


def _link_state(target: Path, source: Path) -> str:
    if target.is_symlink():
        try:
            return "linked" if target.resolve() == source.resolve() else "conflict"
        except FileNotFoundError:
            return "conflict"
    return "conflict" if target.exists() else "missing"


def install_skill_link(skills_dir: Path, source: Path) -> tuple[Path, bool]:
    skills_dir = skills_dir.expanduser()
    target = skills_dir / source.name
    state = _link_state(target, source)
    if state == "linked":
        return target, False
    if state == "conflict":
        raise AgentSetupError(f"refusing to overwrite {target}")

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        relative_source = Path(os.path.relpath(source, target.parent))
        target.symlink_to(relative_source, target_is_directory=True)
    except OSError as exc:
        raise AgentSetupError(f"could not link {target}: {exc.strerror or exc}") from exc
    return target, True


def _selected_agents(names: list[str]) -> list[str]:
    if not names or names == ["all"]:
        return list(_ADAPTERS)
    if "all" in names:
        raise AgentSetupError("use 'all' by itself or list individual agents")
    return list(dict.fromkeys(names))


def setup_agents(
    names: list[str],
    extra_skills_dirs: list[str],
    repo_root: Path = _REPO_ROOT,
    report: Callable[[str], None] = print,
) -> int:
    errors = validate_skill(repo_root)
    selected = _selected_agents(names)
    sources = [_skill_source(repo_root, name) for name in _SKILL_NAMES]

    report("AGENT SETUP")
    report(f"  shared skills {', '.join(source.name for source in sources)}")
    for agent in selected:
        adapter = _ADAPTERS[agent]
        report(f"\n  {agent}")
        executable = shutil.which(adapter.executable)
        report(f"    client  {executable or 'not installed'}")
        errors.extend(validate_mcp_adapter(agent, repo_root))
        try:
            for source in sources:
                target, created = install_skill_link(repo_root / adapter.skills_dir, source)
                report(f"    skill   {'linked' if created else 'ready'} at {target}")
        except AgentSetupError as exc:
            errors.append(str(exc))
        report(f"    MCP     {repo_root / adapter.mcp_config}")
        report(f"    next    {adapter.approval_note}")

    for raw_dir in extra_skills_dirs:
        try:
            report(f"\n  generic Agent Skills client")
            for source in sources:
                target, created = install_skill_link(Path(raw_dir), source)
                report(f"    skill   {'linked' if created else 'ready'} at {target}")
            report("    MCP     configure clickhouse-patterns using this client's MCP format")
        except AgentSetupError as exc:
            errors.append(str(exc))

    if errors:
        for error in errors:
            report(f"  ERROR  {error}")
        return 1
    return 0


def status_agents(
    names: list[str],
    repo_root: Path = _REPO_ROOT,
    report: Callable[[str], None] = print,
) -> int:
    selected = _selected_agents(names)
    errors = validate_skill(repo_root)

    report("AGENT STATUS")
    report(f"  standard skills {'valid' if not errors else 'invalid'}")
    for agent in selected:
        adapter = _ADAPTERS[agent]
        mcp_errors = validate_mcp_adapter(agent, repo_root)
        errors.extend(mcp_errors)
        report(f"\n  {agent}")
        report(f"    client  {shutil.which(adapter.executable) or 'not installed'}")
        for skill_name in _SKILL_NAMES:
            source = _skill_source(repo_root, skill_name)
            target = repo_root / adapter.skills_dir / skill_name
            state = _link_state(target, source)
            report(f"    skill   {state} at {target}")
            if state != "linked":
                errors.append(f"{agent} {skill_name} skill is {state}")
        report(f"    MCP     {'valid' if not mcp_errors else 'invalid'} at {repo_root / adapter.mcp_config}")

    if errors:
        for error in errors:
            report(f"  ERROR  {error}")
        return 1
    return 0
