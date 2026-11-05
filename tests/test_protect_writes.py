"""Traffic arrival semantics and request timeline geometry."""
import importlib.util
from pathlib import Path
import subprocess


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


def test_request_gantt_keeps_parallel_attempts_in_separate_lanes():
    code = r"""
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
global.window = {};
vm.runInThisContext(fs.readFileSync('explorer/experiments.js', 'utf8'));
const lanes = window.PE.experiments.requestLanes([
  {role:'read', start_ms:0, end_ms:10, outcome:'completed'},
  {role:'read', start_ms:1, end_ms:2, outcome:'rejected'},
  {role:'read', start_ms:2, end_ms:3, outcome:'completed'},
  {role:'read', start_ms:10, end_ms:20, outcome:'completed'},
  {role:'write', start_ms:0, end_ms:100, outcome:'completed'},
  {role:'read', start_ms:20, end_ms:19, outcome:'failed'},
], 'read');
assert.deepEqual(lanes.map(r => r.lane), [0, 1, 1, 0]);
assert.deepEqual(lanes.map(r => r.outcome), ['completed', 'rejected', 'completed', 'completed']);
assert.deepEqual(window.PE.experiments.requestLanes([], 'read'), []);
global.document = {createElement: () => ({style: {}, children: [], append(...nodes) {this.children.push(...nodes);}})};
const chart = window.PE.experiments.requestTimeline({results: {requests: [
  {role:'read', index:0, query_id:'read-0', start_ms:0, end_ms:10, outcome:'completed',
   server:{event:'QueryFinish', duration_ms:9, memory_bytes:100}},
  {role:'read', index:1, start_ms:1, end_ms:2, outcome:'rejected', error_code:202},
  {role:'write', index:0, start_ms:2, end_ms:4, outcome:'completed'},
]}}, 20);
assert.equal(chart.children.length, 3); // SELECT, INSERT and the shared axis
assert.equal(chart.children[0].children[0].textContent, 'SELECT');
const track = chart.children[0].children[1];
assert.equal(track.children[0].style.width, '50%');
assert(track.children[0].title.includes('query_id: read-0'));
assert(track.children[0].title.includes('query_log: QueryFinish'));
assert.equal(track.children[1].className, 'request-gantt-bar rejected');
assert.equal(chart.children[1].children[0].textContent, 'INSERT');
"""
    result = subprocess.run(['node', '-e', code], cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
