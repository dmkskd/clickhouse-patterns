"""Enforce workload budgets against tracked query memory, with zero reservation floors."""
from __future__ import annotations

import re

from memory_admission import MemoryAdmission, MIB


class MemoryUsage(MemoryAdmission):
    def __init__(self, admin, run_id, args):
        super().__init__(admin, run_id, args)
        self.restore_users = []

    def setup(self):
        super().setup()
        for user, workload in [('traffic_reader', self.reader), ('traffic_writer', self.writer)]:
            create = self.admin.query(f'SHOW CREATE USER {user}').result_rows[0][0]
            match = re.search(r'\bSETTINGS\s+(.+)$', create, re.DOTALL)
            if not match:
                raise RuntimeError(f'{user} has no explicit settings to preserve')
            self.restore_users.append(f'ALTER USER {user} SETTINGS {match[1]}')
            self.admin.command(f"ALTER USER {user} ADD SETTINGS workload = '{workload}' CONST, reserve_memory = 0 CONST")
        # Keep the per-query safety cap above the largest workload budget. The
        # workload, rather than schema.sql's 128 MiB query cap, governs this example.
        self.admin.command('ALTER USER traffic_reader MODIFY SETTINGS max_memory_usage = 536870912 CONST')

    def request_settings(self, role, index):
        # Neither workload assignment nor memory requirements are supplied by clients.
        return {}

    def request_metadata(self, role, settings):
        return {'workload': self.reader if role == 'read' else self.writer}

    def read_query(self):
        # One scalar result; the exact distinct set consumes memory as it grows.
        return f'SELECT uniqExact(cityHash64(number)) FROM numbers({self.args.read_rows})'

    def history(self, samples, requests=()):
        # With reserve_memory fixed at zero, scheduler allocations follow tracked
        # memory. See MemoryReservation::syncWithMemoryTracker in ClickHouse 26.9.
        series = []
        for role, user, workload, budget in [
            ('read', 'traffic_reader', self.reader, self.args.read_memory_mib),
            ('write', 'traffic_writer', self.writer, 64),
        ]:
            sample_role = 'reader' if role == 'read' else 'writer'
            points = [{'ms': sample.get('memory_ms', sample['ms']), 'value': value / MIB}
                      for sample in samples
                      if (value := sample.get('memory', {}).get(sample_role, {}).get('reserved_bytes')) is not None]
            events = []
            for request in requests:
                if request['role'] != role or request.get('error_code') not in (776, 777, 778):
                    continue
                events.append({'id': request['query_id'], 'ms': request['end_ms'], 'kind': 'failed',
                    'label': f"{'SELECT' if role == 'read' else 'INSERT'} {request['index']} memory limit failure",
                    'details': [['Error', request.get('error_name', '')], ['Reason', request.get('error', '')],
                                ['Workload budget', f'{budget} MiB' if budget else 'Unlimited'],
                                ['Query-log memory', f"{request.get('server', {}).get('memory_bytes', 0) / MIB:.2f} MiB"],
                                ['query_id', request['query_id']]],
                    'note': 'Event time is the client error response. The memory line shows scheduler samples.'})
            series.extend([
                {'group': workload, 'group_label': sample_role.capitalize() + ' workload',
                 'label': 'Tracked query memory', 'unit': 'MiB', 'limit': budget or None, 'points': points, 'events': events},
                {'group': workload, 'group_label': sample_role.capitalize() + ' workload',
                 'label': 'Active queries', 'unit': 'queries', 'limit': None, 'events': [],
                 'points': [{'ms': sample['ms'], 'value': sample['active'].get(user, 0)} for sample in samples]},
            ])
        return series

    def summary(self):
        return {'kind': 'workload-memory-usage', 'reader_workload': self.reader, 'writer_workload': self.writer,
                'reader_budget_mib': self.args.read_memory_mib, 'writer_budget_mib': 64,
                'reserve_memory': 0, 'assignment': 'server-user-settings', 'scheduler': self.rows}

    def close(self):
        errors = []
        for statement in reversed(self.restore_users):
            try:
                self.admin.command(statement)
            except Exception as exc:
                errors.append(exc)
        try:
            super().close()
        except Exception as exc:
            errors.append(exc)
        if errors:
            raise RuntimeError('could not restore workload memory experiment state') from errors[0]
