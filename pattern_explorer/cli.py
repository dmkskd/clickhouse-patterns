"""Terminal interface for the ClickHouse Pattern Explorer.

    python -m pattern_explorer list
    python -m pattern_explorer describe
    python -m pattern_explorer new     <name>
    python -m pattern_explorer clone   <pattern> <name>
    python -m pattern_explorer delete  <name>
    python -m pattern_explorer diagram <pattern>
    python -m pattern_explorer catalog --output PATH
    python -m pattern_explorer explorer [--port 8765] [--no-open]
    python -m pattern_explorer run     <pattern> [--update]
    python -m pattern_explorer start   <pattern>
    python -m pattern_explorer status  [--json]
    python -m pattern_explorer validate [--update]
    python -m pattern_explorer reload
    python -m pattern_explorer stop
    python -m pattern_explorer up      <pattern>
    python -m pattern_explorer down    <pattern>
    python -m pattern_explorer test    <pattern> [--keep] [--update]
    python -m pattern_explorer test-all
"""
from __future__ import annotations

import argparse
import json
import re
import signal
import subprocess
import sys
import textwrap
from contextlib import contextmanager
from pathlib import Path

from .orchestration import session as sessions
from integrations.agent_setup import setup_agents, status_agents
from .rendering.site import (
    DEFAULT_OUTPUT_DIR,
    architecture_url,
    build_pattern_site,
    write_explorer_catalog,
)
from .catalog.workspaces import (
    CloneError,
    clone_pattern,
    create_workspace_pattern,
    delete_clone,
    read_clone_info,
)
from .orchestration.lifecycle import (
    get_session_status,
    reload_session,
    reset_environment,
    start_session,
    stop_session,
    validate_session,
)
from .catalog.manifest import discover_groups, discover_patterns, discover_workspace_patterns, load_pattern
from .catalog.migrate import iter_manifest_paths, migrate_manifest
from .orchestration.runner import run_pattern
from .orchestration.stack import docker
from .orchestration.wait import ConvergenceError
from .logs import configure_logging

# Preferred display order; unknown values sort after these, alphabetically.
_TOPOLOGY_ORDER = ["single", "replicated", "sharded"]

_PROFILE_NAMES = {
    "single": "a single ClickHouse node",
    "cluster": "a two-replica ClickHouse cluster",
    "shards": "two ClickHouse shards with Keeper for cluster DDL",
    "kafka": "Kafka",
    "connect": "Kafka Connect",
    "cdc-ch": "ClickHouse",
    "mysql": "MySQL",
    "postgres": "Postgres",
    "s3": "MinIO staging",
    "peerdb": "PeerDB",
    "cdc-mysql": "the MySQL CDC sink",
    "cdc-postgres": "the Postgres CDC sink",
}


def _ordered_key(value: str, preferred: list[str]):
    return (preferred.index(value) if value in preferred else len(preferred), value)


# Inline pattern links ([[slug|label]]) are Explorer markup; the terminal
# renders the plain label, like the Explorer's plain form.
_PATTERN_LINK_RE = re.compile(r"\[\[[a-z0-9-]+\|([^\]]+)\]\]")

# External markdown links ([label](url)) are Explorer markup too; the terminal
# keeps only the label.
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)\s]+\)")


def _plain_description(text: str) -> str:
    return _MD_LINK_RE.sub(r"\1", _PATTERN_LINK_RE.sub(r"\1", text))


def _schema_summary(pattern) -> str:
    if not pattern.runnable:
        return "documentation only"
    return f"{pattern.schema_sql} -> {pattern.driver_node}" if pattern.schema_sql else "connector-managed"


def _validation_summary(pattern) -> str:
    if not pattern.runnable:
        return "documentation only"
    verify = (
        f"{pattern.verify.sql} -> {pattern.verify.expected}"
        if pattern.verify.sql else "no output comparison"
    )
    count = len(pattern.ready_when)
    checks = f"{count} convergence {'check' if count == 1 else 'checks'}"
    return f"{checks}; {verify}"


def _group_order() -> dict[str, int]:
    """Group folder -> display position, from each group.yaml's order."""
    return {group.key: index for index, group in enumerate(discover_groups())}


def _pattern_sort_key(pattern, groups: dict[str, int]):
    return (
        groups.get(pattern.group, len(groups)),
        pattern.order,
        _ordered_key(pattern.topology, _TOPOLOGY_ORDER),
        pattern.slug,
    )


def _flow_summary(pattern) -> str:
    """Return concise terminal prose derived from the canonical resource graph."""
    if pattern.graph:
        flows = list(dict.fromkeys(
            line.rstrip(":")
            for line in pattern.graph.splitlines()
            if line and not line.startswith((" ", "\t")) and line.endswith(":")
        ))
        return f"Structured resource flow: {', '.join(flows) or 'architecture'}"
    return "Architecture not yet documented."


def _cmd_list(_args) -> int:
    from rich.console import Console
    from rich.table import Table

    groups = discover_groups()
    group_labels = {group.key: group.label or group.title for group in groups}
    order = _group_order()
    patterns = sorted(discover_patterns(), key=lambda p: _pattern_sort_key(p, order))

    console = Console()
    console.print(f"\n[bold]ClickHouse Patterns[/bold] ({len(patterns)})\n")

    table = Table(show_edge=False, pad_edge=False, box=None, header_style="dim")
    table.add_column("group", style="bold cyan", min_width=8, no_wrap=True)
    table.add_column("topology", style="dim", min_width=10, no_wrap=True)
    table.add_column(
        "pattern",
        style="bold",
        min_width=18,
        max_width=42,
        no_wrap=True,
        overflow="ellipsis",
    )
    table.add_column("description", min_width=24, ratio=2, overflow="fold")

    previous_group = None
    previous_topology = None
    for pattern_index, p in enumerate(patterns):
        group_changed = p.group != previous_group
        topology_changed = group_changed or p.topology != previous_topology
        if pattern_index and group_changed:
            table.add_section()
        table.add_row(
            group_labels.get(p.group, p.group) if group_changed else "",
            p.topology if topology_changed else "",
            p.slug,
            p.title,
        )
        previous_group = p.group
        previous_topology = p.topology
    console.print(table)

    workspaces = sorted(discover_workspace_patterns(), key=lambda pattern: pattern.slug)
    if workspaces:
        console.print(
            f"\n[bold]Workspace Patterns[/bold] ({len(workspaces)}) "
            "[dim]company and team extensions[/dim]\n"
        )
        workspace_table = Table(
            show_edge=False,
            pad_edge=False,
            box=None,
            header_style="dim",
        )
        workspace_table.add_column("pattern", style="bold", min_width=18, no_wrap=True)
        workspace_table.add_column("derived from", style="cyan", min_width=18, no_wrap=True)
        workspace_table.add_column("description", min_width=24, ratio=2, overflow="fold")
        for pattern in workspaces:
            metadata = read_clone_info(pattern.dir)
            workspace_table.add_row(
                pattern.slug,
                metadata.source if metadata and metadata.source != "scratch" else "from scratch",
                pattern.title,
            )
        console.print(workspace_table)
    return 0


def _cmd_clone(args) -> int:
    info = clone_pattern(args.pattern, args.clone)
    print(f"WORKSPACE  {info.source} -> {info.slug}")
    print(f"  destination {info.directory}")
    print(f"  versioning  commit {info.directory.parent} to its workspace repository when ready")
    print(f"  run         just run {info.slug}")
    print(f"  test        just test {info.slug}")
    return 0


def _cmd_new(args) -> int:
    info = create_workspace_pattern(args.name)
    print(f"WORKSPACE  created {info.slug}")
    print(f"  destination {info.directory}")
    print(f"  edit        {info.directory / 'pattern.yaml'}")
    print(f"  preview     just diagram {info.slug}")
    print("  runtime     optional; this scaffold starts as documentation-only")
    return 0


def _cmd_delete(args) -> int:
    active = sessions.read_session()
    if (
        active is not None
        and active.pattern_location in {"workspace", "clone"}
        and active.slug == args.clone
    ):
        raise CloneError(
            f"workspace pattern {args.clone!r} owns the active session; run `just stop` first"
        )

    info = delete_clone(args.clone)
    origin = "created from scratch" if info.source == "scratch" else f"derived from {info.source}"
    print(f"DELETED  {info.slug} ({origin})")
    print(f"  removed {info.directory}")
    return 0


def _cmd_describe(_args) -> int:
    from rich.console import Console
    from rich.padding import Padding
    from rich.text import Text

    patterns = discover_patterns()
    console = Console()
    console.print(f"\n[bold]What The Patterns Do[/bold] ({len(patterns)})\n")

    # Keep prose at a readable measure even on very wide terminals.
    reading_width = max(24, min(104, console.width - 4))
    groups: dict[str, list] = {}
    for pattern in patterns:
        groups.setdefault(pattern.group, []).append(pattern)

    group_titles = {group.key: group.title for group in discover_groups()}
    order = _group_order()
    for group_index, group_key in enumerate(sorted(groups, key=lambda key: order.get(key, len(order)))):
        if group_index:
            console.print()
        group = sorted(groups[group_key], key=lambda pattern: (pattern.order, pattern.slug))
        noun = "pattern" if len(group) == 1 else "patterns"
        heading = f"{group_titles.get(group_key, group_key).upper()}  ({len(group)} {noun})"
        console.print(Text(heading, style="bold cyan"))

        for pattern in group:
            console.print()
            console.print(Padding(Text(pattern.slug, style="bold"), (0, 0, 0, 2)))
            console.print(Padding(Text(pattern.title, style="bold"), (0, 0, 0, 4)))
            console.print(Padding(Text(_flow_summary(pattern), style="cyan"), (0, 0, 1, 4)))
            description = textwrap.fill(
                _plain_description(pattern.description),
                width=max(20, reading_width - 4),
                # Descriptions carry relative pattern links; hyphen breaking would
                # split `../cdc-postgres-peerdb/` across lines.
                break_on_hyphens=False,
                break_long_words=False,
            )
            console.print(Padding(Text(description), (0, 0, 0, 4)))
            if pattern.tradeoffs:
                console.print(Padding(Text("TRADE-OFFS", style="bold cyan"), (1, 0, 0, 4)))
                for heading, values in (
                    ("Benefits", pattern.tradeoffs.benefits),
                    ("Limitations", pattern.tradeoffs.limitations),
                ):
                    console.print(Padding(Text(heading, style="bold"), (0, 0, 0, 4)))
                    for value in values:
                        console.print(Padding(Text(f"• {value}"), (0, 0, 0, 6)))
    return 0


def _cmd_show(args) -> int:
    from rich.console import Console
    from rich.panel import Panel

    p = load_pattern(args.pattern)
    files = [n for n in (p.schema_sql, p.load, p.verify.sql, p.verify.expected)
             if n and (p.dir / n).exists()]
    checks = "\n".join(f"  • {e.node or p.driver_node}: {e.query} == {e.value}"
                       for e in p.ready_when) or "  (none)"
    references = "\n".join(f"  {ref.label}: {ref.url}" for ref in p.references)
    references_section = (
        f"[dim]references[/dim]\n{references}\n\n" if references else ""
    )
    tradeoffs_section = ""
    if p.tradeoffs:
        benefits = "\n".join(f"  + {value}" for value in p.tradeoffs.benefits)
        limitations = "\n".join(f"  - {value}" for value in p.tradeoffs.limitations)
        tradeoffs_section = (
            f"[bold cyan]TRADE-OFFS[/bold cyan]\n"
            f"[bold]Benefits[/bold]\n{benefits}\n"
            f"[bold]Limitations[/bold]\n{limitations}\n\n"
        )
    workspace = read_clone_info(p.dir) if p.location in {"workspace", "clone"} else None
    if p.location in {"workspace", "clone"}:
        if workspace and workspace.source == "scratch":
            location = "workspace pattern created from scratch"
        else:
            location = f"workspace pattern derived from {workspace.source}" if workspace else "workspace pattern"
    else:
        location = "curated library"
    body = (
        f"[bold]{p.title}[/bold]\n\n"
        f"[cyan]{_flow_summary(p)}[/cyan]\n\n"
        f"{_plain_description(p.description)}\n\n"
        f"{tradeoffs_section}"
        f"{references_section}"
        f"topology   {p.topology}\n"
        f"tags       {', '.join(p.tags)}\n"
        f"mode       {p.mode}\n"
        f"profiles   {', '.join(p.profiles) or 'none'}\n"
        f"driver     {p.driver_node or 'none'}\n"
        f"location   {location}\n"
        f"directory  {p.dir.resolve()}\n"
        f"files      {', '.join(files)}\n\n"
        f"[dim]convergence checks[/dim]\n{checks}\n\n"
        f"[dim]schema     {_schema_summary(p)}\n"
        f"validation {_validation_summary(p)}[/dim]\n\n"
        + (
            f"run:   just run {p.slug}\n"
            f"test:  just test {p.slug}"
            if p.runnable
            else f"preview: just diagram {p.slug}"
        )
    )
    Console().print(Panel(body, title=p.slug, title_align="left", border_style="cyan"))
    return 0


def _cmd_up(args) -> int:
    p = load_pattern(args.pattern)
    p.require_runnable()
    _print_pattern_plan(p, "infrastructure only")
    print(f"up {p.slug}  profiles={p.profiles}")
    docker(p.profiles, p).compose.up(detach=True, wait=True)
    print(f"up. Tear down with:  just down {p.slug}")
    return 0


def _cmd_down(args) -> int:
    p = load_pattern(args.pattern)
    docker(p.profiles, p).compose.down(volumes=True, remove_orphans=True)
    active = sessions.read_session()
    if active and active.slug == p.slug:
        sessions.clear_session()
    print(f"down {p.slug}")
    return 0


def _print_started(active) -> None:
    print(f"STARTED  {active.slug}")
    print(f"  driver   {active.driver_node} at {active.driver_url}")
    print(f"  profiles {', '.join(active.profiles)}")
    if active.pattern_dir:
        print(f"  files    {active.pattern_dir} ({active.pattern_location})")
    _print_live_actions(active)


def _print_browse(active) -> None:
    print("\n  BROWSE")
    print(f"    SQL console        {active.play_url}")
    print(f"    schema visualizer  {active.schema_url}")
    try:
        pattern = sessions.load_session_pattern(active)
        if pattern.graph:
            html_path = build_pattern_site(pattern, DEFAULT_OUTPUT_DIR)
            print(f"    architecture       {architecture_url(html_path, pattern.slug)}")
    except Exception:  # noqa: BLE001 - optional browse aid must not break a session
        pass


def _print_live_actions(active) -> None:
    _print_browse(active)
    print("\n  MANAGE")
    print("    status             just status")
    print("    validate           just validate")
    print("    rebuild            just reload")
    print("    stop               just stop")


def _progress(message: str) -> None:
    print(f"  {message}", flush=True)


class _TerminationRequested(BaseException):
    def __init__(self, signum: int):
        self.signum = signum


@contextmanager
def _foreground_signals():
    """Turn termination signals into exceptions so foreground runs clean up."""
    previous = {}

    def request_termination(signum, _frame):
        raise _TerminationRequested(signum)

    for name in ("SIGTERM", "SIGHUP"):
        signum = getattr(signal, name, None)
        if signum is None:
            continue
        try:
            previous[signum] = signal.getsignal(signum)
            signal.signal(signum, request_termination)
        except (OSError, ValueError):
            previous.pop(signum, None)

    try:
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def _wait_for_finish(active, input_fn=None) -> None:
    _print_browse(active)
    print("\n  EXPLORE")
    print("    The validated environment is running for inspection.")
    print("    Use the links above, another terminal, or an agent while this command waits.")
    prompt = "\n  Press Enter to finish and remove containers and volumes (Ctrl+C also finishes). "
    try:
        (input_fn or input)(prompt)
    except (EOFError, KeyboardInterrupt):
        print()


def _record_run_phase(pattern, phase: str, error: str | None = None) -> None:
    active = sessions.read_session()
    if active is not None and active.slug == pattern.slug:
        sessions.write_session(active.with_phase(phase, error))


def _human_join(values: list[str]) -> str:
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return " and ".join(values)
    return f"{', '.join(values[:-1])}, and {values[-1]}"


def _prepare_steps(pattern) -> list[str]:
    if pattern.schema_sql:
        schema_step = f"Apply {pattern.schema_sql} from {pattern.driver_node}."
    elif "existing" in (pattern.graph or ""):
        schema_step = "Prepare the CDC-created and existing ClickHouse targets."
    else:
        schema_step = "Let the connector create and manage the ClickHouse schema."

    steps = [schema_step]
    if pattern.load:
        steps.append(f"Run {pattern.load} using {pattern.driver_node} as the driver.")
    return steps


def _validation_step(pattern) -> str:
    count = len(pattern.ready_when)
    checks = f"{count} convergence {'check' if count == 1 else 'checks'}"
    if pattern.verify.sql:
        return f"Wait for {checks}, then compare {pattern.verify.sql} with {pattern.verify.expected}."
    return f"Wait for {checks}."


def _run_plan_steps(pattern, action: str) -> list[str]:
    components = [_PROFILE_NAMES.get(profile, profile) for profile in pattern.profiles]
    start = f"Start {_human_join(components)}."
    leave = "Leave the pattern running for inspection."

    if action == "infrastructure only":
        return [start, "Leave the infrastructure running without applying the pattern."]
    if action == "validate live session":
        return [_validation_step(pattern), leave]
    if action == "rebuild and keep running":
        return [
            "Remove the current pattern and its volumes.",
            start,
            *_prepare_steps(pattern),
            leave,
        ]
    if action == "interactive run":
        return [
            start,
            *_prepare_steps(pattern),
            _validation_step(pattern),
            "Keep the validated environment available until the user finishes.",
            "Tear down the containers and volumes.",
        ]

    steps = [start, *_prepare_steps(pattern)]
    if action.startswith("test") or action.startswith("end-to-end"):
        steps.append(_validation_step(pattern))
    steps.append(
        leave if "keep running" in action else "Tear down the containers and volumes."
    )
    return steps


def _print_pattern_plan(pattern, action: str) -> None:
    from rich.console import Console, Group
    from rich.panel import Panel
    from rich.text import Text

    blocks = [
        Text(pattern.title, style="bold"),
        Text(),
        Text("DATA FLOW", style="bold cyan"),
        Text(_flow_summary(pattern), style="cyan"),
        Text(),
        Text("WHAT IT DEMONSTRATES", style="bold cyan"),
        Text(pattern.description),
    ]
    if pattern.tradeoffs:
        blocks.extend([Text(), Text("TRADE-OFFS", style="bold cyan")])
        for heading, values in (
            ("Benefits", pattern.tradeoffs.benefits),
            ("Limitations", pattern.tradeoffs.limitations),
        ):
            blocks.append(Text(heading, style="bold"))
            blocks.extend(Text(f"• {value}") for value in values)
    if pattern.references:
        blocks.extend([Text(), Text("REFERENCES", style="bold cyan")])
        for reference in pattern.references:
            line = Text(f"{reference.label}: ")
            line.append(
                reference.url,
                style=f"underline cyan link {reference.url}",
            )
            blocks.append(line)
    blocks.extend([Text(), Text("RUN PLAN", style="bold cyan")])
    for index, step in enumerate(_run_plan_steps(pattern, action), start=1):
        line = Text(f"{index}. ", style="bold cyan")
        line.append(step)
        blocks.append(line)

    console = Console()
    console.print()
    console.print(Panel(
        Group(*blocks),
        title=f"PATTERN  {pattern.slug}",
        title_align="left",
        border_style="cyan",
        width=min(106, console.width),
    ))


def _cmd_start(args) -> int:
    pattern = load_pattern(args.pattern)
    pattern.require_runnable()
    _print_pattern_plan(pattern, "prepare and keep running")
    _print_started(start_session(pattern, report=_progress, owner="detached"))
    return 0


def _cmd_diagram(args) -> int:
    pattern = load_pattern(args.pattern)
    output_dir = Path(args.output_dir) if args.output_dir else DEFAULT_OUTPUT_DIR
    html_path = build_pattern_site(pattern, output_dir)
    print("ARCHITECTURE")
    print(f"  HTML  {architecture_url(html_path, pattern.slug)}")
    print("  hint  open the diagram in the browser; use Download SVG to export it")
    return 0


def _cmd_explorer(args) -> int:
    from .server.explorer import serve_explorer

    return serve_explorer(port=args.port, open_browser=not args.no_open)


def _cmd_catalog(args) -> int:
    output_path = write_explorer_catalog(Path(args.output))
    print(f"CATALOG  {output_path}")
    return 0


def _cmd_run(args) -> int:
    if not sys.stdin.isatty():
        print(
            "FAIL: `just run` requires an interactive terminal.\n"
            "  hint: Use `just test <pattern>` for non-interactive validation.",
            file=sys.stderr,
        )
        return 2

    def run() -> int:
        pattern = load_pattern(args.pattern)
        existing = sessions.read_session()
        if existing is not None:
            raise sessions.SessionError(
                f"pattern {existing.slug!r} already has a {existing.phase} session; "
                "finish it before starting another run"
            )

        _print_pattern_plan(pattern, "interactive run")
        rc = 1
        preparation_completed = False
        validation_completed = False
        inspectable_failure = False

        try:
            with _foreground_signals():
                try:
                    start_session(pattern, report=_progress, owner="terminal")
                    preparation_completed = True
                    result = validate_session(update=args.update, report=_progress)
                    validation_completed = True
                    rc = _report(result)
                    if result.passed:
                        _record_run_phase(pattern, "validated")
                    else:
                        detail = result.detail.splitlines()[0] if result.detail else "validation failed"
                        _record_run_phase(pattern, "failed", detail)
                except Exception as exc:  # noqa: BLE001 - pause on inspectable failures
                    rc = _explain(exc, pattern.slug)
                    lines = str(exc).splitlines()
                    detail = lines[0] if lines else "no details"
                    summary = f"{type(exc).__name__}: {detail}"
                    _record_run_phase(pattern, "failed", summary)
                    inspectable_failure = type(exc).__name__ != "DockerException"

                active = sessions.read_session()
                status = get_session_status() if active is not None else None
                inspectable = (
                    active is not None
                    and active.slug == pattern.slug
                    and status is not None
                    and status.reachable
                    and (preparation_completed or inspectable_failure)
                )
                if inspectable:
                    _wait_for_finish(active)
                elif active is not None:
                    print("\n  EXPLORE unavailable because the ClickHouse endpoint is not reachable.")
        except _TerminationRequested as exc:
            print(f"\n  FINISH  received signal {exc.signum}; cleaning up")
            if not validation_completed:
                rc = 128 + exc.signum
        except KeyboardInterrupt:
            print("\n  FINISH  interrupted; cleaning up")
            if not validation_completed:
                rc = 130
        finally:
            active = sessions.read_session()
            if active is not None and active.slug == pattern.slug:
                try:
                    stopped = stop_session(report=_progress)
                    print(f"FINISHED  {stopped.slug}")
                except Exception as exc:  # noqa: BLE001 - final cleanup boundary
                    _explain(exc, pattern.slug)
                    rc = 1

        return rc

    return _guard(run, args.pattern)


def _cmd_validate(args) -> int:
    active = sessions.read_session(required=True)
    pattern = sessions.load_session_pattern(active)
    _print_pattern_plan(pattern, "validate live session")
    return _report(validate_session(update=args.update, report=_progress))


def _cmd_reload(_args) -> int:
    active = sessions.read_session(required=True)
    pattern = sessions.load_session_pattern(active)
    _print_pattern_plan(pattern, "rebuild and keep running")
    _print_started(reload_session(report=_progress))
    return 0


def _cmd_stop(_args) -> int:
    active = stop_session(report=_progress)
    print(f"STOPPED  {active.slug}")
    return 0


def _cmd_reset(_args) -> int:
    outcome = reset_environment(report=_progress)
    if outcome["slug"]:
        print(f"RESET    cleared session {outcome['slug']}")
    else:
        print("RESET    no session record was present")
    print("  removed containers, networks, and volumes for compose project 'chp'")
    print("  start fresh with:  just run <pattern>")
    return 0


def _cmd_status(args) -> int:
    status = get_session_status()
    if args.json:
        print(json.dumps({"active": status is not None, **(status.as_dict() if status else {})}))
        return 0
    if status is None:
        print("no active pattern; explore one with:  just run <pattern>")
        return 0

    active = status.session
    print(f"{active.phase.upper()}  {active.slug}")
    print(f"  driver   {active.driver_node} at {active.driver_url}")
    print(f"  profiles {', '.join(active.profiles)}")
    if active.pattern_dir:
        print(f"  files    {active.pattern_dir} ({active.pattern_location})")
    print(f"  reachable {'yes' if status.reachable else 'no'}")
    print(f"  source    {'changed; run `just reload`' if status.source_changed else 'unchanged'}")
    if active.error:
        print(f"  error     {active.error}")
    _print_live_actions(active)
    return 0


def _report(result) -> int:
    if result.passed:
        if result.updated:
            print(f"UPDATED  {result.slug}  ({result.detail})")
        else:
            print(f"PASS  {result.slug}")
        return 0
    print(f"FAIL  {result.slug}\n{result.detail}", file=sys.stderr)
    return 1


def _explain(exc: Exception, pattern: str | None) -> int:
    """Turn a raw failure into a short, actionable message."""
    name = type(exc).__name__
    msg = str(exc)
    low = msg.lower()
    keep_hint = (
        f"Re-run interactively with `just run {pattern}` to inspect the environment "
        "before it is cleaned up." if pattern else ""
    )

    if name == "DockerException":
        head = "infrastructure did not start"
        if "cannot connect to the docker daemon" in low:
            hint = "Docker does not appear to be running. Start Docker and retry."
        elif "port is already allocated" in low or "address already in use" in low or "bind for" in low:
            hint = ("A host port this pattern needs is already in use (another ClickHouse, "
                    "Kafka, or database?). Stop the conflicting service, then retry.")
        elif "manifest unknown" in low or "not found" in low or "pull access" in low:
            hint = "An image tag could not be pulled. Check the pins in compose/stack.yml and your network."
        else:
            hint = "The stack failed to come up. See the compose output above for the failing service."
    elif isinstance(exc, ConvergenceError):
        head = "data did not converge in time"
        hint = f"The query never reached its expected value. {keep_hint}"
    elif isinstance(exc, subprocess.CalledProcessError):
        head = "the load step failed"
        hint = "See the load script output above."
    elif name in {"ValidationError", "PatternManifestError"}:
        head = "pattern.yaml is invalid"
        hint = "Fix the fields reported above (unknown field, unknown profile/node, or missing file)."
        # A manifest error names its own file, which is often not the pattern
        # that was asked for: loading any pattern reads every manifest.
        if name == "PatternManifestError":
            pattern = None
    elif isinstance(exc, FileNotFoundError):
        head = "pattern not found"
        hint = "Run `just list` to see available patterns."
    elif isinstance(exc, FileExistsError):
        head = "clone destination already exists"
        hint = "Choose a new clone name; existing patterns are never overwritten."
    elif isinstance(exc, CloneError):
        head = "clone was not deleted"
        hint = "Only managed, inactive workspace patterns can be deleted."
    elif isinstance(exc, ValueError):
        head = "invalid pattern request"
        hint = "Use a unique lowercase name with words separated by single hyphens."
    elif isinstance(exc, sessions.SessionError):
        head = "session operation failed"
        hint = "Run `just status` to inspect the current session."
    else:
        head = "unexpected error"
        hint = keep_hint

    subject = f"  {pattern}" if pattern else ""
    print(f"FAIL{subject}: {head}", file=sys.stderr)
    if msg:
        print(f"  {name}: {msg.splitlines()[0][:200]}", file=sys.stderr)
    if hint:
        print(f"  hint: {hint}", file=sys.stderr)
    return 1


def _guard(fn, pattern: str | None):
    try:
        return fn()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - top-level UX boundary
        return _explain(exc, pattern)


def _cmd_test(args) -> int:
    def run() -> int:
        pattern = load_pattern(args.pattern)
        action = "test and keep running" if args.keep else "end-to-end test with teardown"
        _print_pattern_plan(pattern, action)
        result = run_pattern(
            pattern,
            keep=args.keep,
            update=args.update,
            report=_progress,
        )
        rc = _report(result)
        if args.keep:
            _print_started(sessions.read_session(required=True))
        return rc

    return _guard(
        run,
        args.pattern,
    )


def _cmd_up_guarded(args) -> int:
    return _guard(lambda: _cmd_up(args), args.pattern)


def _cmd_down_guarded(args) -> int:
    return _guard(lambda: _cmd_down(args), args.pattern)


def _cmd_test_all(_args) -> int:
    rc = 0
    for p in (pattern for pattern in discover_patterns() if pattern.runnable):
        _print_pattern_plan(p, "end-to-end test with teardown")
        rc |= _guard(lambda p=p: _report(run_pattern(p, report=_progress)), p.slug)
    return rc


def _cmd_migrate(args) -> int:
    rewritten = 0
    for path in iter_manifest_paths(args.patterns):
        if migrate_manifest(path):
            rewritten += 1
            print(f"migrated {path}")
        else:
            print(f"already current {path}")
    print(f"{rewritten} manifest(s) rewritten")
    return 0


def _cmd_agent_setup(args) -> int:
    return setup_agents(args.agents, args.skills_dir)
def _cmd_agent_status(args) -> int:
    return status_agents(args.agents)


def main() -> int:
    parser = argparse.ArgumentParser(prog="pattern-explorer")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("agent-setup", help="configure skills for supported agents")
    sp.add_argument("agents", nargs="*", choices=("all", "codex", "claude"))
    sp.add_argument(
        "--skills-dir",
        action="append",
        default=[],
        help="also link the standard skill into this client-specific skills directory",
    )
    sp.set_defaults(func=_cmd_agent_setup)

    sp = sub.add_parser("agent-status", help="show skill and MCP adapter status")
    sp.add_argument("agents", nargs="*", choices=("all", "codex", "claude"))
    sp.set_defaults(func=_cmd_agent_status)

    sp = sub.add_parser("list")
    sp.set_defaults(func=_cmd_list)
    sub.add_parser("describe", help="describe what every pattern does").set_defaults(
        func=_cmd_describe
    )
    sub.add_parser("test-all").set_defaults(func=_cmd_test_all)

    sp = sub.add_parser(
        "migrate",
        help="rewrite pattern.yaml files to the current manifest format",
    )
    sp.add_argument(
        "patterns",
        nargs="*",
        help="patterns to migrate (default: all library and workspace patterns)",
    )
    sp.set_defaults(func=_cmd_migrate)

    sp = sub.add_parser("show")
    sp.add_argument("pattern")
    sp.set_defaults(func=lambda a: _guard(lambda: _cmd_show(a), a.pattern))

    sp = sub.add_parser("new", help="create a documentation-first workspace pattern")
    sp.add_argument("name", help="name for the new workspace pattern")
    sp.set_defaults(func=lambda a: _guard(lambda: _cmd_new(a), a.name))

    sp = sub.add_parser("clone", help="derive an editable workspace pattern")
    sp.add_argument("pattern", help="library or workspace pattern to derive from")
    sp.add_argument("clone", help="name for the derived workspace pattern")
    sp.set_defaults(func=lambda a: _guard(lambda: _cmd_clone(a), a.pattern))

    sp = sub.add_parser("delete", help="delete a managed workspace pattern")
    sp.add_argument("clone", help="name of the workspace pattern to delete")
    sp.set_defaults(func=lambda a: _guard(lambda: _cmd_delete(a), a.clone))

    sp = sub.add_parser("diagram", help="build the browser diagram for a pattern")
    sp.add_argument("pattern")
    sp.add_argument("--output-dir", help="directory for the generated browser site")
    sp.set_defaults(func=lambda a: _guard(lambda: _cmd_diagram(a), a.pattern))

    sp = sub.add_parser("catalog", help="compile pattern manifests for the browser")
    sp.add_argument("--output", required=True, help="path for the generated catalog.js")
    sp.set_defaults(func=lambda a: _guard(lambda: _cmd_catalog(a), None))

    sp = sub.add_parser(
        "explorer",
        help="open the interactive catalog and local pattern control plane",
    )
    sp.add_argument("--port", type=int, default=8765, help="local HTTP port")
    sp.add_argument("--no-open", action="store_true", help="do not open a browser")
    sp.set_defaults(func=lambda a: _guard(lambda: _cmd_explorer(a), None))

    sp = sub.add_parser("start", help="prepare a pattern and leave it running")
    sp.add_argument("pattern")
    sp.set_defaults(func=lambda a: _guard(lambda: _cmd_start(a), a.pattern))

    sp = sub.add_parser(
        "run",
        help="validate a pattern, wait for inspection, then clean up",
    )
    sp.add_argument("pattern")
    sp.add_argument(
        "--update",
        action="store_true",
        help="regenerate expected.txt from verify.sql output",
    )
    sp.set_defaults(func=_cmd_run)

    sp = sub.add_parser("status", help="show the active pattern and MCP endpoint")
    sp.add_argument("--json", action="store_true", help="emit machine-readable session state")
    sp.set_defaults(func=lambda a: _guard(lambda: _cmd_status(a), None))

    sp = sub.add_parser("validate", help="validate the active running pattern")
    sp.add_argument("--update", action="store_true",
                    help="regenerate expected.txt from verify.sql output")
    sp.set_defaults(func=lambda a: _guard(lambda: _cmd_validate(a), None))

    sub.add_parser("reload", help="rebuild the active pattern from source").set_defaults(
        func=lambda a: _guard(lambda: _cmd_reload(a), None)
    )
    sub.add_parser("stop", help="tear down the active pattern").set_defaults(
        func=lambda a: _guard(lambda: _cmd_stop(a), None)
    )
    sub.add_parser(
        "reset",
        help="recovery: force-remove every container and clear session state",
    ).set_defaults(func=_cmd_reset)

    for name in ("up", "down"):
        sp = sub.add_parser(name)
        sp.add_argument("pattern")
        sp.set_defaults(func=_cmd_up_guarded if name == "up" else _cmd_down_guarded)

    sp = sub.add_parser("test")
    sp.add_argument("pattern")
    sp.add_argument(
        "--keep",
        action="store_true",
        help="advanced compatibility mode: leave the stack running",
    )
    sp.add_argument("--update", action="store_true",
                    help="regenerate expected.txt from verify.sql output")
    sp.set_defaults(func=_cmd_test)

    args = parser.parse_args()
    configure_logging()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
