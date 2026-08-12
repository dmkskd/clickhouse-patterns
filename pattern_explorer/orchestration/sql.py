"""Run SQL files used by pattern preparation and validation."""
from __future__ import annotations

import re
from pathlib import Path

from clickhouse_connect.driver.client import Client

_COMMENT = re.compile(r"--[^\n]*")


def split_statements(text: str) -> list[str]:
    text = _COMMENT.sub("", text)
    return [s.strip() for s in text.split(";") if s.strip()]


def run_sql_file(client: Client, path: Path) -> None:
    for stmt in split_statements(path.read_text()):
        client.command(stmt)


def query_as_text(client: Client, path: Path) -> str:
    """Run the (single-statement) file and render rows as tab-separated text."""
    stmts = split_statements(path.read_text())
    result = client.query(stmts[-1])
    lines = ["\t".join("" if v is None else str(v) for v in row) for row in result.result_rows]
    return "\n".join(lines)
