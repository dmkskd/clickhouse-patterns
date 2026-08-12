from types import SimpleNamespace

import pytest

from pattern_explorer.catalog.manifest import Requires
from pattern_explorer.orchestration.runner import _run_load, _check_clickhouse_version


class _FakeDriver:
    def __init__(self, version):
        self._version = version

    def query(self, _sql):
        return SimpleNamespace(result_rows=[[self._version]])


def _pattern_requiring(**bounds):
    return SimpleNamespace(slug="demo", requires=Requires(**bounds))


def test_version_gate_passes_within_range():
    _check_clickhouse_version(_pattern_requiring(clickhouse_min="26.8"), _FakeDriver("26.8.1.918"))
    _check_clickhouse_version(_pattern_requiring(clickhouse_max="25.3"), _FakeDriver("25.3.14.14"))
    # No bounds declared: nothing is queried or checked.
    _check_clickhouse_version(_pattern_requiring(), _FakeDriver("1.0"))


def test_version_gate_rejects_too_new():
    with pytest.raises(RuntimeError, match="needs ClickHouse <= 25.3"):
        _check_clickhouse_version(_pattern_requiring(clickhouse_max="25.3"), _FakeDriver("26.6.1.1193"))


def test_version_gate_rejects_too_old_and_includes_note():
    with pytest.raises(RuntimeError, match="needs ClickHouse >= 26.8.*experimental"):
        _check_clickhouse_version(
            _pattern_requiring(clickhouse_min="26.8", note="experimental"),
            _FakeDriver("26.7.3.19"),
        )


def test_python_load_output_is_streamed_to_reporter(tmp_path):
    script = tmp_path / "load.py"
    script.write_text(
        'print("initial ingest complete: 8000 rows")\n'
        'print("offsets reset; connector reprocessing from 0")\n'
        'print("reprocessing done (committed offset 8000)")\n'
    )
    pattern = SimpleNamespace(
        load="load.py",
        dir=tmp_path,
        path=lambda name: tmp_path / name,
    )
    messages = []

    _run_load(pattern, report=messages.append)

    assert messages == [
        "LOAD    initial ingest complete: 8000 rows",
        "LOAD    offsets reset; connector reprocessing from 0",
        "LOAD    reprocessing done (committed offset 8000)",
    ]
