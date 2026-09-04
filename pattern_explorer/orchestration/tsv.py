"""TSV-aware comparison and readable diffs for validation output.

Modelled on ClickHouse's own `tests/integration/helpers/test_tools.py:TSV`:
compare results as rows-of-columns (not raw strings) and, on mismatch, show a
line-by-line diff instead of two opaque blobs.

Lines starting with '#' in the expected file are annotations (typically a
column header naming the verify.sql aliases). ClickHouse output never contains
them, so they label the columns without taking part in the comparison, and the
explorer renders them as a header row above the values.
"""
from __future__ import annotations

import difflib


def _rows(text: str) -> list[list[str]]:
    # Lines starting with '#' are annotations (typically a column header);
    # ClickHouse output never contains them, so they play no part in the
    # comparison.
    return [
        line.split("\t")
        for line in text.strip().splitlines()
        if not line.startswith("#")
    ]


def tsv_equal(got: str, want: str) -> bool:
    return _rows(got) == _rows(want)


def tsv_diff(got: str, want: str) -> str:
    """Unified diff of `want` vs `got`, normalised through TSV parsing."""
    want_lines = ["\t".join(r) for r in _rows(want)]
    got_lines = ["\t".join(r) for r in _rows(got)]
    diff = difflib.unified_diff(
        want_lines, got_lines, fromfile="expected", tofile="got", lineterm=""
    )
    return "\n".join(diff) or "(results differ only in trailing whitespace)"


def format_tsv_table(text: str, max_rows: int = 20) -> str:
    """Render verification TSV as a compact, aligned terminal table."""
    rows = _rows(text) if text.strip() else []
    if not rows:
        return "(no rows)"

    shown = rows[:max_rows]
    column_count = max(len(row) for row in shown)
    widths = [
        max(len(row[index]) if index < len(row) else 0 for row in shown)
        for index in range(column_count)
    ]

    lines = []
    for row in shown:
        cells = [row[index] if index < len(row) else "" for index in range(column_count)]
        lines.append("  ".join(
            cell.ljust(widths[index]) if index < column_count - 1 else cell
            for index, cell in enumerate(cells)
        ))

    omitted = len(rows) - len(shown)
    if omitted:
        lines.append(f"... {omitted} more row(s)")
    return "\n".join(lines)
