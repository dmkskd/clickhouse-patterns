"""Server-assigned workloads, memory enforcement evidence and restoration."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


def policy(monkeypatch, admin):
    directory = Path(__file__).resolve().parents[1] / 'patterns/resource-limits/protect-inserts-from-selects/experiments'
    monkeypatch.syspath_prepend(str(directory))
    spec = importlib.util.spec_from_file_location('usage_policy', directory / 'memory_usage.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.MemoryUsage(admin, 'test-run', SimpleNamespace(
        read_rate=8, duration=5, read_memory_mib=64, read_rows=1000000))


class Admin:
    def __init__(self, fail=False):
        self.commands = []
        self.fail = fail

    def query(self, sql):
        if sql.startswith('SHOW CREATE USER'):
            user = sql.split()[-1]
            return SimpleNamespace(result_rows=[(f'CREATE USER {user} SETTINGS max_memory_usage = 134217728 CONST, log_queries = 1 CONST',)])
        return SimpleNamespace(result_rows=[(0,)])

    def command(self, sql):
        self.commands.append(sql)
        if self.fail and 'MODIFY SETTINGS' in sql:
            raise RuntimeError('injected user configuration failure')


def test_memory_usage_is_assigned_and_constrained_by_the_server(monkeypatch):
    admin = Admin()
    usage = policy(monkeypatch, admin)
    usage.setup()
    assert "ALTER USER traffic_reader ADD SETTINGS workload = 'protect_testrun_reads' CONST, reserve_memory = 0 CONST" in admin.commands
    assert "ALTER USER traffic_writer ADD SETTINGS workload = 'protect_testrun_writes' CONST, reserve_memory = 0 CONST" in admin.commands
    assert usage.request_settings('read', 0) == {}
    assert usage.request_settings('write', 0) == {}
    assert usage.request_metadata('read', {}) == {'workload': 'protect_testrun_reads'}
    assert usage.read_query() == 'SELECT uniqExact(cityHash64(number)) FROM numbers(1000000)'
    assert usage.summary()['reserve_memory'] == 0
    usage.close()
    restored = next(i for i, sql in enumerate(admin.commands) if sql.startswith('ALTER USER traffic_writer SETTINGS'))
    dropped = next(i for i, sql in enumerate(admin.commands) if sql.startswith('DROP WORKLOAD'))
    assert restored < dropped
    assert 'ALTER USER traffic_reader SETTINGS max_memory_usage = 134217728 CONST, log_queries = 1 CONST' in admin.commands


def test_partial_setup_restores_both_users_and_drops_only_run_objects(monkeypatch):
    admin = Admin(fail=True)
    usage = policy(monkeypatch, admin)
    with pytest.raises(RuntimeError, match='injected'):
        usage.setup()
    usage.close()
    assert len([sql for sql in admin.commands if sql.startswith(('ALTER USER traffic_reader SETTINGS', 'ALTER USER traffic_writer SETTINGS'))]) == 2
    assert admin.commands[-4:] == [
        'DROP WORKLOAD protect_testrun_writes', 'DROP WORKLOAD protect_testrun_reads',
        'DROP WORKLOAD protect_testrun', 'DROP RESOURCE protect_testrun_memory']


def test_usage_history_reports_execution_failures_and_measured_memory(monkeypatch):
    usage = policy(monkeypatch, Admin())
    samples = [{'ms': 10, 'memory_ms': 12, 'active': {'traffic_reader': 2},
                'memory': {'reader': {'reserved_bytes': 48 * 1024 * 1024}, 'writer': {'reserved_bytes': 0}}}]
    requests = [{'role': 'read', 'query_id': 'read-1', 'index': 1, 'end_ms': 15,
                 'outcome': 'failed', 'error_code': 776, 'error_name': 'RESOURCE_LIMIT_EXCEEDED',
                 'error': 'workload memory exceeded', 'server': {'memory_bytes': 32 * 1024 * 1024}}]
    history = usage.history(samples, requests)
    assert history[0]['points'] == [{'ms': 12, 'value': 48}]
    assert history[0]['limit'] == 64
    assert history[1]['points'] == [{'ms': 10, 'value': 2}]
    event = history[0]['events'][0]
    assert event['kind'] == 'failed'
    assert dict(event['details'])['Query-log memory'] == '32.00 MiB'
    assert 'reservation_mib' not in usage.request_metadata('read', {})
