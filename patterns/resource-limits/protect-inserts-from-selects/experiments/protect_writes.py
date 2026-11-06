"""Generate bounded read/write traffic and collect client and server evidence."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import math
import queue
import re
import signal
import threading
import time
from uuid import uuid4

import clickhouse_connect

from pattern_explorer.orchestration.nodes import connect
from pattern_explorer.orchestration.probe import result_line


def percentile(values, q):
    if not values:
        return None
    values = sorted(values)
    return round(values[max(0, math.ceil(q * len(values)) - 1)], 2)


def schedule(rate, duration, shape):
    """Requested offsets, independent of response latency."""
    return [i // rate if shape == 'burst' else i / rate for i in range(rate * duration)]


def reader_settings_sql(create_user, slots=None):
    """Preserve the full settings clause when changing one admission setting."""
    match = re.search(r'\bSETTINGS\s+(.+)$', create_user, re.DOTALL)
    if not match:
        raise RuntimeError('traffic_reader has no explicit settings to preserve')
    settings = match[1]
    if slots is not None:
        settings, count = re.subn(r'\bmax_concurrent_queries_for_user\s*=\s*\d+',
            f'max_concurrent_queries_for_user = {int(slots)}', settings, count=1)
        if count != 1:
            raise RuntimeError('traffic_reader has no explicit query-count limit')
    return 'ALTER USER traffic_reader SETTINGS ' + settings


def main(policy_kind='fixed'):
    parser = argparse.ArgumentParser()
    if policy_kind == 'fixed':
        parser.add_argument('--read-slots', type=int, choices=[0, 1, 2, 4], default=2)
    else:
        parser.set_defaults(read_slots=0)
        parser.add_argument('--read-memory-mib', type=int, choices=[0, 32, 64, 128, 256], default=64)
        parser.add_argument('--read-reserve-mib', type=int, choices=[16, 32, 64], default=32)
        parser.add_argument('--reservation-mix', choices=['uniform', 'mixed'], default='mixed')
        parser.add_argument('--waiting-queries', type=int, choices=[1, 4, 16], default=16)
        parser.add_argument('--admission-wait-ms', type=int, choices=[5, 20, 100, 500], default=20)
    parser.add_argument('--read-clients', type=int, choices=[4, 8, 16], default=8)
    parser.add_argument('--read-rate', type=int, choices=[4, 8, 16], default=8)
    parser.add_argument('--read-shape', choices=['steady', 'burst'], default='burst')
    parser.add_argument('--read-rows', type=int, choices=[1000000, 10000000, 50000000], default=50000000)
    parser.add_argument('--write-rate', type=int, choices=[2, 5, 10, 20], default=5)
    parser.add_argument('--batch-rows', type=int, choices=[100, 1000, 10000], default=1000)
    parser.add_argument('--duration', type=int, choices=[5, 10, 20], default=5)
    args = parser.parse_args()
    admin = connect('ch')
    run_id = str(uuid4())
    stop = threading.Event()
    records, samples = [], []
    record_lock = threading.Lock()
    pools = {}
    clients = []
    start = None
    policy_applied = False
    memory_policy = None
    generator_errors = []

    def cancel(_signum=None, _frame=None):
        stop.set()

    signal.signal(signal.SIGTERM, cancel)
    signal.signal(signal.SIGINT, cancel)

    def apply_slots(slots):
        admin.command(reader_settings_sql(before, slots))

    def generate(role, rate, shape, executor):
        pending = []
        # Only ready clients receive work. Missed dispatches are reported
        # separately from server rejection, never queued invisibly in Python.
        for index, offset in enumerate(schedule(rate, args.duration, shape)):
            if stop.wait(max(0, start + offset - time.monotonic())):
                break
            if pools[role].empty():
                now = round((time.monotonic() - start) * 1000, 2)
                with record_lock:
                    records.append({'role': role, 'index': index, 'start_ms': now,
                                    'end_ms': now, 'outcome': 'not_sent'})
                continue
            # Reserve before submission; otherwise a burst can enqueue more
            # requests than ready clients before workers take their clients.
            client = pools[role].get_nowait()
            pending.append(executor.submit(execute_request, role, index, client))
        for future in pending:
            future.result()
        stop.wait(max(0, start + args.duration - time.monotonic()))

    def produce(*args):
        try:
            generate(*args)
        except Exception as exc:
            generator_errors.append(exc)
            stop.set()

    def execute_request(role, index, client):
        query_id = f'protect-{run_id}-{role}-{index}'
        record = {'query_id': query_id, 'role': role, 'index': index,
                  'start_ms': round((time.monotonic() - start) * 1000, 2)}
        settings = {'query_id': query_id}
        if memory_policy:
            settings.update(memory_policy.request_settings(role, index))
            record['reservation_mib'] = settings['reserve_memory'] // (1024 * 1024)
            record['workload'] = settings['workload']
        try:
            if role == 'read':
                client.query(f'SELECT sum(cityHash64(number)) FROM numbers({args.read_rows})', settings=settings)
            else:
                client.command('INSERT INTO demo.events SELECT '
                    f"toUUID('{run_id}'), {index}, number, number FROM numbers({args.batch_rows})", settings=settings)
            record['outcome'] = 'completed'
        except Exception as exc:
            match = re.search(r'Code:\s*(\d+)', str(exc))
            code = int(match[1]) if match else None
            record.update(outcome='rejected' if code in (202, 745, 1020) else 'failed', error_code=code, error=str(exc)[:500])
            record['error_name'] = {202: 'TOO_MANY_SIMULTANEOUS_QUERIES', 745: 'SERVER_OVERLOADED',
                                    1020: 'MEMORY_RESERVATION_ACQUISITION_TIMEOUT',
                                    777: 'MEMORY_RESERVATION_KILLED', 778: 'MEMORY_RESERVATION_FAILED'}.get(code, '')
        finally:
            record['end_ms'] = round((time.monotonic() - start) * 1000, 2)
            with record_lock:
                records.append(record)
            pools[role].put(client)

    try:
        before = admin.query("SHOW CREATE USER traffic_reader").result_rows[0][0]
        restore_reader = reader_settings_sql(before)
        effective_version = admin.query('SELECT version()').result_rows[0][0]
        apply_slots(args.read_slots)
        policy_applied = True
        if policy_kind == 'memory':
            from memory_admission import MemoryAdmission
            memory_policy = MemoryAdmission(admin, run_id, args)
            memory_policy.setup()
        for role, count in [('read', args.read_clients), ('write', 2)]:
            pools[role] = queue.Queue()
            for _ in range(count):
                client = clickhouse_connect.get_client(host='localhost', port=8123,
                    username='traffic_reader' if role == 'read' else 'traffic_writer', password='',
                    query_retries=0, connect_timeout=3, send_receive_timeout=10, autogenerate_session_id=False)
                clients.append(client)
                pools[role].put(client)
        reader_settings = dict(clients[0].query(
            "SELECT name, value FROM system.settings WHERE name IN "
            "('max_concurrent_queries_for_user', 'max_threads', 'max_execution_time', 'max_memory_usage')"
        ).result_rows)
        if int(reader_settings['max_concurrent_queries_for_user']) != args.read_slots:
            raise RuntimeError('reader concurrency setting differs from requested policy')
        start = time.monotonic()
        with ThreadPoolExecutor(max_workers=args.read_clients) as reads, ThreadPoolExecutor(max_workers=2) as writes:
            generators = [threading.Thread(target=produce, args=('read', args.read_rate, args.read_shape, reads)),
                          threading.Thread(target=produce, args=('write', args.write_rate, 'steady', writes))]
            for generator in generators:
                generator.start()
            try:
                while any(generator.is_alive() for generator in generators):
                    if stop.is_set():
                        admin.command("KILL QUERY WHERE startsWith(query_id, {prefix:String}) SYNC",
                                      parameters={'prefix': f'protect-{run_id}-'})
                    rows = admin.query('SELECT user, count() FROM system.processes '
                        'WHERE startsWith(query_id, {prefix:String}) GROUP BY user',
                        parameters={'prefix': f'protect-{run_id}-'}).result_rows
                    sample = {'ms': round((time.monotonic() - start) * 1000, 2), 'active': dict(rows)}
                    if memory_policy:
                        sample['memory'] = memory_policy.sample()
                        sample['memory_ms'] = round((time.monotonic() - start) * 1000, 2)
                    samples.append(sample)
                    time.sleep(.02)
            finally:
                if any(generator.is_alive() for generator in generators):
                    stop.set()
                    admin.command("KILL QUERY WHERE startsWith(query_id, {prefix:String}) SYNC",
                                  parameters={'prefix': f'protect-{run_id}-'})
                for generator in generators:
                    generator.join()
        if generator_errors:
            raise RuntimeError('traffic generator failed') from generator_errors[0]
        elapsed = time.monotonic() - start
        admin.command('SYSTEM FLUSH LOGS')
        log_rows = admin.query("SELECT query_id, toString(type), exception_code, query_duration_ms, memory_usage, ProfileEvents "
            "FROM system.query_log WHERE startsWith(query_id, {prefix:String}) "
            "AND type IN ('QueryFinish', 'ExceptionBeforeStart', 'ExceptionWhileProcessing')",
            parameters={'prefix': f'protect-{run_id}-'}).result_rows
        evidence = {row[0]: {'event': row[1], 'error_code': row[2], 'duration_ms': row[3],
                            'memory_bytes': row[4], 'profile_events': row[5]} for row in log_rows}
        stored_rows = admin.query('SELECT count() FROM demo.events WHERE run_id = {run:UUID}', parameters={'run': run_id}).result_rows[0][0]
        result = {'run_id': run_id, 'server_version': effective_version,
                  'duration_ms': round(elapsed * 1000, 2), 'stored_rows': stored_rows,
                  'log_matches': len(evidence), 'samples': samples,
                  'policy': {'reader': 'traffic_reader', 'writer': 'traffic_writer',
                             'reader_settings': reader_settings, 'server_slots': 32}}
        if memory_policy:
            memory_policy.sample()
            result['policy'].update(memory_policy.summary())
            result['resource_history'] = memory_policy.history(samples, records)
            result['peak_reserved_mib'] = round(max((s.get('memory', {}).get('reserved_bytes', 0) for s in samples), default=0) / (1024 * 1024), 2)
            result['peak_pending'] = max((s.get('memory', {}).get('pending', 0) for s in samples), default=0)
            result['read_overloaded'] = sum(r.get('error_code') == 745 for r in records if r['role'] == 'read')
            result['read_admission_timeout'] = sum(r.get('error_code') == 1020 for r in records if r['role'] == 'read')
        else:
            from concurrency_history import concurrency_history
            result['resource_history'] = concurrency_history(samples, records, args.read_slots)
        for role in ['read', 'write']:
            subset = [r for r in records if r['role'] == role]
            counts = Counter(r['outcome'] for r in subset)
            for outcome in ['completed', 'rejected', 'failed', 'not_sent']:
                result[f'{role}_{outcome}'] = counts[outcome]
            result[f'{role}_p95_ms'] = percentile([r['end_ms'] - r['start_ms'] for r in subset if r['outcome'] == 'completed'], .95)
        result['write_rows_per_second'] = round(stored_rows / elapsed, 1)
        result['peak_reads'] = max((s['active'].get('traffic_reader', 0) for s in samples), default=0)
        result['expected_rows'] = result['write_completed'] * args.batch_rows
        result['row_check'] = 'matched' if stored_rows == result['expected_rows'] else 'mismatch'
        result['error_codes'] = dict(Counter(str(r['error_code']) for r in records if r.get('error_code')))
        for record in records:
            if record.get('query_id') in evidence:
                record['server'] = evidence[record['query_id']]
        result['requests'] = sorted(records, key=lambda r: r['start_ms'])
        for role in ['write', 'read']:
            print(f"{role}: completed={result[role + '_completed']} rejected={result[role + '_rejected']} "
                  f"failed={result[role + '_failed']} not_sent={result[role + '_not_sent']} p95_ms={result[role + '_p95_ms']}")
        print(f"stored_rows={stored_rows} expected_rows={result['expected_rows']} logs={len(evidence)} peak_reads={result['peak_reads']}")
        if stop.is_set():
            raise RuntimeError('experiment stopped; active requests cancelled')
        if result['row_check'] != 'matched':
            raise RuntimeError('stored row count does not match acknowledged inserts')
        print(result_line(result))
    finally:
        stop.set()
        for client in clients:
            client.close()
        try:
            if memory_policy:
                memory_policy.close()
        finally:
            try:
                if policy_applied:
                    admin.command(restore_reader)
            finally:
                admin.close()


if __name__ == '__main__':
    main()
