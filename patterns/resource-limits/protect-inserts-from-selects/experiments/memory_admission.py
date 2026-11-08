"""Memory-reservation admission policy for the read/write traffic experiment."""
from __future__ import annotations

MIB = 1024 * 1024


class MemoryAdmission:
    """Create run-local workloads and remove only the objects this run created."""

    def __init__(self, admin, run_id, args):
        self.admin, self.args = admin, args
        self.root = 'protect_' + run_id.replace('-', '')
        self.reader, self.writer = self.root + '_reads', self.root + '_writes'
        self.resource = self.root + '_memory'
        self.created = []
        self.resource_created = False
        self.rows = []
        # Queue every scheduled read so queue length is not a second rejection policy.
        self.queue_capacity = args.read_rate * args.duration

    def setup(self):
        # Resource creation enables scheduling server-wide. Refuse a pre-existing
        # scheduling hierarchy: this lab example must not reconfigure other work.
        if self.admin.query('SELECT count() FROM system.resources').result_rows[0][0]:
            raise RuntimeError('memory experiment requires a lab without existing RESOURCE objects')
        if self.admin.query('SELECT count() FROM system.workloads').result_rows[0][0]:
            raise RuntimeError('memory experiment requires a lab without existing WORKLOAD objects')
        self.admin.command(f'CREATE RESOURCE {self.resource} (MEMORY RESERVATION)')
        self.resource_created = True
        for name, parent, settings in [
            (self.root, '', f'max_memory = {(self.args.read_memory_mib + 64) * MIB if self.args.read_memory_mib else 0}'),
            (self.reader, self.root, f'max_memory = {self.args.read_memory_mib * MIB}, max_waiting_queries = {self.queue_capacity}'),
            (self.writer, self.root, f'max_memory = {64 * MIB}'),
        ]:
            self.admin.command(f'CREATE WORKLOAD {name}' + (f' IN {parent}' if parent else '') + f' SETTINGS {settings}')
            self.created.append(name)

    def request_settings(self, role, index):
        reservation = 16 if role == 'write' else self.args.read_reserve_mib
        if role == 'read' and self.args.reservation_mix == 'mixed' and index % 2 == 0:
            reservation = 8
        return {'workload': self.reader if role == 'read' else self.writer,
                'reserve_memory': reservation * MIB,
                'workload_admission_timeout_ms': self.args.admission_wait_ms}

    def request_metadata(self, role, settings):
        return {'reservation_mib': settings['reserve_memory'] // MIB,
                'workload': self.reader if role == 'read' else self.writer}

    def read_query(self):
        return f'SELECT sum(cityHash64(number)) FROM numbers({self.args.read_rows})'

    def sample(self):
        columns = ['path', 'type', 'allocated', 'allocations', 'pending', 'admits', 'rejects', 'victims']
        rows = self.admin.query('SELECT ' + ', '.join(columns) + ' FROM system.scheduler WHERE resource = {resource:String}',
                                parameters={'resource': self.resource}).result_rows
        self.rows = [dict(zip(columns, row)) for row in rows]
        # Each workload has several nodes. Report the leaf allocation_queue once.
        def leaf_sample(workload):
            leaf = next((r for r in self.rows if '/' + workload + '/' in r['path'] and r['type'] == 'allocation_queue'), None)
            return {'reserved_bytes': leaf['allocated'] if leaf else None,
                    'pending': leaf['pending'] if leaf else None}
        reader, writer = leaf_sample(self.reader), leaf_sample(self.writer)
        return {**reader, 'reader': reader, 'writer': writer}

    def history(self, samples, requests=()):
        """Normalize scheduler observations for the generic time-series view."""
        series = []
        for role, workload, budget, queue_limit in [
            ('reader', self.reader, self.args.read_memory_mib, None),
            ('writer', self.writer, 64, None),
        ]:
            for field, label, unit, divisor, limit in [
                ('reserved_bytes', 'Reserved memory', 'MiB', MIB, budget or None),
                ('pending', 'Pending reservations', 'requests', 1, queue_limit),
            ]:
                points = []
                for sample in samples:
                    value = sample.get('memory', {}).get(role, {}).get(field)
                    if value is not None:
                        points.append({'ms': sample.get('memory_ms', sample['ms']), 'value': value / divisor})
                events = []
                if field == 'reserved_bytes':
                    for request in requests:
                        if request['role'] != ('read' if role == 'reader' else 'write') or request['outcome'] != 'rejected':
                            continue
                        code = request.get('error_code')
                        reason = {
                            1020: f'Memory reservation was not admitted within the {self.args.admission_wait_ms} ms wait limit.',
                            745: f'The pending-reservation queue was full (limit {self.queue_capacity}).',
                            202: 'A concurrent-query admission limit was reached.',
                        }.get(code, request.get('error_name') or 'Admission rejected the request.')
                        details = [['Reason', reason], ['Error', request.get('error_name') or str(code)],
                                   ['Requested reservation', f"{request.get('reservation_mib', '?')} MiB"],
                                   ['Request interval', f"{request['start_ms']:.2f}–{request['end_ms']:.2f} ms"],
                                   ['query_id', request.get('query_id', '')]]
                        earlier = [point for point in points if point['ms'] <= request['end_ms']]
                        if earlier:
                            observed = earlier[-1]
                            details += [['Earlier sample', f"{observed['ms']:.2f} ms"],
                                        ['Reserved at sample', f"{observed['value']:g} MiB"]]
                            if limit:
                                details.append(['Headroom at sample', f"{max(0, limit - observed['value']):g} MiB"])
                        command = 'SELECT' if role == 'reader' else 'INSERT'
                        events.append({'id': request.get('query_id'), 'ms': request['end_ms'], 'label': f"{command} {request['index']} rejected",
                                       'kind': 'rejected', 'details': details,
                                       'note': 'Marker time is the client error response. The earlier sample is not the exact admission-decision state.'})
                series.append({'group': workload, 'group_label': role.capitalize() + ' workload',
                               'label': label, 'unit': unit, 'limit': limit, 'points': points, 'events': events})
        return series

    def summary(self):
        return {'kind': 'workload-memory', 'reader_workload': self.reader, 'writer_workload': self.writer,
                'reader_budget_mib': self.args.read_memory_mib, 'reservation_mix': self.args.reservation_mix,
                'large_reservation_mib': self.args.read_reserve_mib, 'small_reservation_mib': 8,
                'writer_reservation_mib': 16, 'writer_budget_mib': 64,
                'max_waiting_queries': self.queue_capacity,
                'workload_admission_timeout_ms': self.args.admission_wait_ms,
                'scheduler': self.rows}

    def close(self):
        # Workers have drained before these objects are removed. Continue cleanup
        # after a failed DROP, and report the failure instead of hiding it.
        errors = []
        for name in reversed(self.created):
            try:
                self.admin.command(f'DROP WORKLOAD {name}')
            except Exception as exc:
                errors.append(exc)
        if self.resource_created:
            try:
                self.admin.command(f'DROP RESOURCE {self.resource}')
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise RuntimeError('could not remove experiment scheduling objects') from errors[0]
