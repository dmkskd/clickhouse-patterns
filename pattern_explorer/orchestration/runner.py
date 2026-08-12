"""Orchestrate one pattern end to end. Shared by the CLI and pytest."""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

_REPO_ROOT = Path(__file__).resolve().parents[2]

from ..catalog.manifest import Pattern, check_clickhouse_version
from .nodes import connect
from .sql import query_as_text, run_sql_file
from .stack import stack
from .tsv import format_tsv_table, tsv_diff, tsv_equal
from .wait import wait_for

Reporter = Callable[[str], None]


@dataclass
class Result:
    slug: str
    passed: bool
    detail: str = ""
    checks: list[str] = field(default_factory=list)
    updated: bool = False    # verify reference was (re)generated via --update


def _run_load(pattern: Pattern, report: Reporter | None = None) -> None:
    path = pattern.path(pattern.load)
    if path is None:
        return
    if path.suffix == ".sql":
        run_sql_file(connect(pattern.driver_node), path)
    elif path.suffix == ".py":
        # Expose the repo root so load scripts can import shared orchestration helpers.
        env = {
            **os.environ,
            "PYTHONPATH": str(_REPO_ROOT),
            "PYTHONUNBUFFERED": "1",
        }
        if report is None:
            subprocess.run(
                [sys.executable, str(path)], cwd=pattern.dir, check=True, env=env
            )
        else:
            process = subprocess.Popen(
                [sys.executable, str(path)],
                cwd=pattern.dir,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            assert process.stdout is not None
            for line in process.stdout:
                message = line.rstrip()
                if message:
                    _emit(report, f"LOAD    {message}")
            return_code = process.wait()
            if return_code:
                raise subprocess.CalledProcessError(
                    return_code, [sys.executable, str(path)]
                )
    else:
        raise ValueError(f"don't know how to run load step {path.name}")


def _run_schema(pattern: Pattern, driver) -> None:
    if pattern.schema_sql and pattern.path(pattern.schema_sql).exists():
        run_sql_file(driver, pattern.path(pattern.schema_sql))


def _emit(report: Reporter | None, message: str) -> None:
    if report:
        report(message)


def _check_clickhouse_version(pattern: Pattern, driver, report: Reporter | None = None) -> None:
    """Fail fast with a clear message if the running server is out of the pattern's
    declared ClickHouse range, instead of a cryptic error mid-schema."""
    req = pattern.requires
    if not (req.clickhouse_min or req.clickhouse_max):
        return
    running = str(driver.query("SELECT version()").result_rows[0][0]).strip()
    problem = check_clickhouse_version(running, req.clickhouse_min, req.clickhouse_max)
    if problem:
        hint = f" ({req.note})" if req.note else ""
        raise RuntimeError(f"pattern {pattern.slug!r} {problem}{hint}")
    _emit(report, f"VERSION {running} satisfies requires")


def prepare_pattern(pattern: Pattern, report: Reporter | None = None) -> None:
    """Apply schema and load data to infrastructure that is already running."""
    pattern.require_runnable()
    driver = connect(pattern.driver_node)
    _check_clickhouse_version(pattern, driver, report)
    if pattern.schema_sql and pattern.path(pattern.schema_sql).exists():
        _emit(report, f"SCHEMA  {pattern.schema_sql} -> {pattern.driver_node}")
    _run_schema(pattern, driver)

    if pattern.load:
        _emit(report, f"LOAD    {pattern.load} -> {pattern.driver_node}")
    _run_load(pattern, report=report)
    if pattern.load:
        _emit(report, "LOAD    complete")


def validate_pattern(
    pattern: Pattern,
    update: bool = False,
    report: Reporter | None = None,
) -> Result:
    """Run convergence and output checks against an already-running pattern."""
    pattern.require_runnable()
    checks: list[str] = []
    driver = connect(pattern.driver_node)

    for exp in pattern.ready_when:
        node = exp.node or pattern.driver_node
        _emit(report, f"WAIT    {node}: {exp.query} == {exp.value} ({exp.timeout}s)")
        client = connect(exp.node) if exp.node else driver
        wait_for(client, exp.query, exp.value, timeout=exp.timeout)
        check = f"{node}: {exp.query} == {exp.value}"
        checks.append(check)
        _emit(report, f"CHECK   {check}")

    if pattern.verify.sql and pattern.path(pattern.verify.sql).exists():
        _emit(report, f"VERIFY  {pattern.verify.sql} == {pattern.verify.expected}")
        got = query_as_text(driver, pattern.path(pattern.verify.sql)).strip()
        expected_path = pattern.path(pattern.verify.expected)

        if update:
            expected_path.write_text(got + "\n")
            _emit(report, f"UPDATE  {expected_path.name} ({len(got.splitlines())} row(s))")
            _emit(report, "RESULT\n" + "\n".join(
                f"          {line}" for line in format_tsv_table(got).splitlines()
            ))
            return Result(pattern.slug, True, checks=checks, updated=True,
                          detail=f"wrote {len(got.splitlines())} row(s) to {expected_path.name}")

        want = expected_path.read_text().strip() if expected_path.exists() else ""
        if not tsv_equal(got, want):
            _emit(report, "VERIFY  mismatch")
            return Result(pattern.slug, False,
                          detail="verify mismatch:\n" + tsv_diff(got, want),
                          checks=checks)
        row_count = len(got.splitlines()) if got else 0
        _emit(report, f"VERIFY  matched ({row_count} row(s))")
        _emit(report, "RESULT\n" + "\n".join(
            f"          {line}" for line in format_tsv_table(got).splitlines()
        ))

    return Result(pattern.slug, True, checks=checks)


def run_pattern(
    pattern: Pattern,
    keep: bool = False,
    update: bool = False,
    report: Reporter | None = None,
) -> Result:
    """Prepare and validate a pattern, normally in an ephemeral clean stack."""
    pattern.require_runnable()
    if keep:
        from .lifecycle import start_session

        start_session(pattern, report=report)
        return validate_pattern(pattern, update=update, report=report)

    with stack(pattern.profiles, report=report):
        prepare_pattern(pattern, report=report)
        return validate_pattern(pattern, update=update, report=report)
