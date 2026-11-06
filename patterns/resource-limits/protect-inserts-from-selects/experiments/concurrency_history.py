"""Per-user concurrency observations for the fixed read/write experiment."""


def concurrency_history(samples, requests, read_slots):
    """Describe per-user samples and client errors for the shared chart views."""
    series = []
    for role, user, label, limit in [
        ('read', 'traffic_reader', 'Active SELECTs', read_slots or None),
        ('write', 'traffic_writer', 'Active INSERTs', None),
    ]:
        points = [{'ms': sample['ms'], 'value': sample['active'].get(user, 0)}
                  for sample in samples]
        events = []
        for request in requests:
            if request['role'] != role:
                continue
            request['admission_units'] = 1
            if request['outcome'] != 'rejected':
                continue
            details = [['Reason', 'A concurrent-query limit rejected the request.'],
                       ['Error', request.get('error_name') or str(request.get('error_code'))],
                       ['query_id', request.get('query_id', '')]]
            if limit:
                details.append(['Reader query limit', str(limit)])
            events.append({'id': request.get('query_id'), 'ms': request['end_ms'],
                           'label': f"{'SELECT' if role == 'read' else 'INSERT'} {request['index']} rejected",
                           'kind': 'rejected', 'details': details,
                           'note': 'Active-query counts are sampled from system.processes.'})
        series.append({'group': role, 'group_label': 'Reader user' if role == 'read' else 'Writer user',
                       'label': label, 'unit': 'queries', 'limit': limit,
                       'points': points, 'events': events})
    return series
