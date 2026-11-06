"""Traffic arrival semantics."""
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def script():
    path = ROOT / 'patterns/resource-limits/protect-inserts-from-selects/experiments/protect_writes.py'
    spec = importlib.util.spec_from_file_location('protect_writes', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_arrivals_are_open_loop_and_bursts_keep_requested_count():
    module = script()
    assert module.schedule(4, 2, 'steady') == [0, .25, .5, .75, 1, 1.25, 1.5, 1.75]
    assert module.schedule(4, 2, 'burst') == [0, 0, 0, 0, 1, 1, 1, 1]
    assert module.percentile([], .95) is None
    assert module.percentile([1, 2, 100], .95) == 100


def test_changing_query_slots_preserves_other_settings_and_constraints():
    module = script()
    settings = 'max_concurrent_queries_for_user = 2 CONST, max_threads = 1 CONST, max_execution_time = 5 CONST, max_memory_usage = 134217728 CONST, log_queries = 1 CONST'
    create = 'CREATE USER traffic_reader IDENTIFIED WITH no_password SETTINGS ' + settings
    changed = module.reader_settings_sql(create, 0)
    assert changed == 'ALTER USER traffic_reader SETTINGS ' + settings.replace('queries_for_user = 2', 'queries_for_user = 0')
    assert module.reader_settings_sql(create) == 'ALTER USER traffic_reader SETTINGS ' + settings


def memory_policy(admin, **overrides):
    from types import SimpleNamespace
    path = ROOT / 'patterns/resource-limits/protect-inserts-from-selects/experiments/memory_admission.py'
    spec = importlib.util.spec_from_file_location('memory_admission', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    values = dict(read_memory_mib=64, read_reserve_mib=32, reservation_mix='mixed',
                  read_rate=8, duration=5, admission_wait_ms=20)
    values.update(overrides)
    return module.MemoryAdmission(admin, 'test-run', SimpleNamespace(**values))


def test_memory_policy_uses_byte_reservations_and_samples_the_leaf_queue():
    from types import SimpleNamespace

    class Admin:
        def query(self, sql, parameters=None):
            return SimpleNamespace(result_rows=[
                ('/protect_testrun/limit/fair/protect_testrun_reads', 'workload', 123, 4, None, 5, None, 0),
                ('/protect_testrun/limit/fair/protect_testrun_reads/limit/queue', 'allocation_queue', 48*1024*1024, 3, 1, 5, 2, 0),
                ('/protect_testrun/limit/fair/protect_testrun_writes/limit/queue', 'allocation_queue', 16*1024*1024, 1, 0, 5, 0, 0),
            ])

    policy = memory_policy(Admin())
    assert policy.request_settings('read', 0)['reserve_memory'] == 8*1024*1024
    assert policy.request_settings('read', 1)['reserve_memory'] == 32*1024*1024
    assert policy.request_settings('write', 0)['reserve_memory'] == 16*1024*1024
    assert policy.request_settings('read', 0)['workload'] != policy.request_settings('write', 0)['workload']
    sample = policy.sample()
    assert sample['reader'] == {'reserved_bytes': 48*1024*1024, 'pending': 1}
    assert sample['writer'] == {'reserved_bytes': 16*1024*1024, 'pending': 0}
    history = policy.history([{'ms': 10, 'memory_ms': 12, 'memory': sample}])
    assert len(history) == 4
    assert history[0]['limit'] == 64
    assert history[1]['limit'] is None  # pending count is observed, not a rejection threshold
    assert history[0]['points'] == [{'ms': 12, 'value': 48}]
    assert history[2]['points'] == [{'ms': 12, 'value': 16}]
    assert policy.history([{'ms': 10, 'memory': {}}])[0]['points'] == []
    rejected = {'role': 'read', 'index': 3, 'outcome': 'rejected', 'error_code': 1020,
                'error_name': 'MEMORY_RESERVATION_ACQUISITION_TIMEOUT', 'reservation_mib': 32,
                'start_ms': 10, 'end_ms': 35, 'query_id': 'read-3'}
    event = policy.history([{'ms': 12, 'memory': sample}], [rejected])[0]['events'][0]
    assert event['ms'] == 35
    assert event['label'] == 'SELECT 3 rejected'
    details = dict(event['details'])
    assert '20 ms wait limit' in details['Reason']
    assert details['Requested reservation'] == '32 MiB'
    assert details['Headroom at sample'] == '16 MiB'
    assert 'not the exact' in event['note']
    uniform = memory_policy(Admin(), reservation_mix='uniform')
    assert uniform.request_settings('read', 0)['reserve_memory'] == uniform.request_settings('read', 1)['reserve_memory']


def test_memory_policy_preserves_existing_scheduler_and_cleans_partial_setup():
    from types import SimpleNamespace
    import pytest

    class Admin:
        existing = 1

        def __init__(self):
            self.commands = []

        def query(self, *_args, **_kwargs):
            return SimpleNamespace(result_rows=[(self.existing,)])

        def command(self, sql):
            self.commands.append(sql)
            if sql.startswith('CREATE WORKLOAD') and '_reads ' in sql:
                raise RuntimeError('injected setup failure')

    admin = Admin()
    policy = memory_policy(admin)
    with pytest.raises(RuntimeError, match='without existing RESOURCE'):
        policy.setup()
    policy.close()
    assert admin.commands == []
    admin.existing = 0
    policy = memory_policy(admin)
    with pytest.raises(RuntimeError, match='injected setup failure'):
        policy.setup()
    assert 'max_waiting_queries = 40' in admin.commands[-1]  # all 8/s × 5s scheduled reads fit
    policy.close()
    assert admin.commands[-2:] == ['DROP WORKLOAD protect_testrun', 'DROP RESOURCE protect_testrun_memory']


def test_fixed_concurrency_history_keeps_reader_limit_writer_samples_and_errors():
    path = ROOT / 'patterns/resource-limits/protect-inserts-from-selects/experiments/concurrency_history.py'
    spec = importlib.util.spec_from_file_location('concurrency_history', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    samples = [{'ms': 20, 'active': {'traffic_reader': 2, 'traffic_writer': 1}},
               {'ms': 120, 'active': {}}]
    requests = [{'role': 'read', 'index': 3, 'outcome': 'rejected', 'end_ms': 22,
                 'query_id': 'read-3', 'error_code': 202,
                 'error_name': 'TOO_MANY_SIMULTANEOUS_QUERIES'},
                {'role': 'write', 'index': 1, 'outcome': 'completed', 'end_ms': 30}]
    history = module.concurrency_history(samples, requests, 2)
    assert history[0]['limit'] == 2
    assert history[1]['limit'] is None
    assert history[0]['points'] == [{'ms': 20, 'value': 2}, {'ms': 120, 'value': 0}]
    assert history[1]['points'][0]['value'] == 1
    assert history[0]['events'][0]['id'] == 'read-3'
    assert dict(history[0]['events'][0]['details'])['Reader query limit'] == '2'
    assert [request['admission_units'] for request in requests] == [1, 1]
    assert module.concurrency_history(samples, [], 0)[0]['limit'] is None


def test_generator_sends_a_full_burst_while_earlier_requests_are_busy():
    from concurrent.futures import ThreadPoolExecutor
    import queue
    import threading

    module = script()
    capacity = module.generator_capacity(16, 1)
    assert capacity == 16
    pool = queue.Queue()
    for _ in range(capacity):
        pool.put(object())
    started, release, stop = threading.Event(), threading.Event(), threading.Event()
    lock = threading.Lock()
    seen, errors = [], []

    def execute(role, index, client):
        with lock:
            seen.append((role, index))
            if len(seen) == 16:
                started.set()
        try:
            assert release.wait(3)
        finally:
            pool.put(client)

    with ThreadPoolExecutor(max_workers=capacity) as executor:
        def dispatch():
            try:
                module.dispatch_requests('read', 16, 1, 'burst', 0, stop, pool, executor, execute)
            except BaseException as exc:
                errors.append(exc)

        worker = threading.Thread(target=dispatch)
        worker.start()
        try:
            assert started.wait(3), 'The complete burst must reach workers before any request finishes'
        finally:
            release.set()
            worker.join(3)
        assert not worker.is_alive()
    assert not errors
    assert sorted(seen) == [('read', index) for index in range(16)]
    assert pool.qsize() == capacity


def test_generator_fails_instead_of_dropping_a_scheduled_request():
    import queue
    from types import SimpleNamespace
    import threading
    import pytest

    module = script()
    pool = queue.Queue()
    client = object()
    pool.put(client)
    executor = SimpleNamespace(submit=lambda *_args: SimpleNamespace(result=lambda: None))
    with pytest.raises(RuntimeError, match='read generator capacity exhausted at request 2'):
        module.dispatch_requests('read', 2, 1, 'burst', 0, threading.Event(), pool, executor, lambda *_: None)

    class BrokenExecutor:
        def submit(self, *_args):
            raise RuntimeError('cannot create worker')

    pool.put(client)
    with pytest.raises(RuntimeError, match='cannot create worker'):
        module.dispatch_requests('read', 1, 1, 'burst', 0, threading.Event(), pool, BrokenExecutor(), lambda *_: None)
    assert pool.get_nowait() is client
