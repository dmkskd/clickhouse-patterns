"""Decision paths that distinguish accounting, configuration and limit behavior."""
import json
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from pattern_explorer.catalog.manifest import Guide, discover_groups
from pattern_explorer.rendering.site import _browser_group

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def group():
    return next(group for group in discover_groups() if group.key == "resource-limits")


def test_memory_admission_does_not_match_background_deferral(group):
    mechanisms = group.guide.mechanisms
    assert not [m for m in mechanisms if all(value in m.facets[facet] for facet, value in
                {"resource": "memory", "scope": "server", "behavior": "wait"}.items())]
    assert any(gap.when == {"resource": "memory", "scope": "server", "behavior": "wait"}
               for gap in group.guide.gaps)
    background = next(m for m in mechanisms if m.id == "merges-memory")
    assert background.facets["behavior"] == ["defer"]
    assert background.facets["activity"] == ["background"]


def test_user_profile_can_configure_per_query_budget(group):
    query = next(m for m in group.guide.mechanisms if m.id == "query-memory")
    assert query.facets["scope"] == ["query"]
    assert "profile" in query.facets["configuration"]
    all_users = next(m for m in group.guide.mechanisms if m.id == "all-users-concurrency")
    assert all_users.facets["scope"] == ["all-users"]


def test_reservation_failures_are_available_to_diagnose(group):
    reservation = next(m for m in group.guide.mechanisms if m.id == "workload-memory")
    assert {"MEMORY_RESERVATION_KILLED", "MEMORY_RESERVATION_FAILED"} <= set(reservation.errors)
    assert "reserve_memory" in reservation.setting_groups["Query settings"]
    assert "workload_admission_timeout_ms" in reservation.setting_groups["Query settings (26.9+)"]


@pytest.mark.parametrize("facet", ["scope", "configuration", "activity", "behavior"])
def test_unknown_facet_values_are_rejected(group, facet):
    data = group.guide.model_dump()
    data["mechanisms"][0]["facets"][facet] = ["misspelled"]
    with pytest.raises(ValidationError, match="unknown"):
        Guide.model_validate(data)


def test_unknown_feature_version_is_rejected(group):
    data = group.guide.model_dump()
    data["mechanisms"][0]["since"] = "latest"
    with pytest.raises(ValidationError, match="invalid guide mechanism version"):
        Guide.model_validate(data)


def test_browser_decision_paths_and_version_switch(group):
    # Exercise the real renderer and handlers with a small DOM adapter. The
    # adapter records rendered controls; it does not reimplement guide filtering.
    script = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const info = JSON.parse(fs.readFileSync(0, 'utf8'));
class Control {
  constructor(attrs) {
    this.attrs = attrs;
    this.dataset = Object.fromEntries(Object.entries(attrs).filter(([key]) => key.startsWith('data-'))
      .map(([key, value]) => [key.slice(5), value]));
    this.handlers = {};
  }
  addEventListener(kind, fn) { this.handlers[kind] = fn; }
  click() { assert(this.handlers.click); this.handlers.click({currentTarget: this}); }
}
const slot = {
  controls: [],
  writes: 0,
  set innerHTML(html) {
    this.writes++;
    this.html = html;
    this.controls = [...html.matchAll(/<(?:button|select)\b([^>]*)>/g)].map((match) =>
      new Control(Object.fromEntries([...match[1].matchAll(/([\w-]+)="([^"]*)"/g)].map(m => [m[1], m[2]]))));
  },
  querySelectorAll(selector) {
    const name = selector.match(/^\.([\w-]+)/)?.[1];
    return this.controls.filter(c => (c.attrs.class || '').split(' ').includes(name)
      && (!selector.includes('[data-') || selector.includes('[data-topology]') && c.dataset.topology
        || selector.includes('[data-view]') && c.dataset.view));
  },
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
};
global.window = {PE: {util: {esc: value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;'),
  displayTitle: p => p.title}}};
global.document = {getElementById: id => id === 'catalog-group-guide' ? slot : null};
vm.runInThisContext(fs.readFileSync('explorer/guide.js', 'utf8'));
const ui = window.PE.guide.create({patterns: [], openPattern() {}});
const control = (name, facet, value) => {
  const c = slot.controls.find(c => (c.attrs.class || '').split(' ').includes(name)
    && (!facet || c.dataset[facet] === value));
  assert(c, `missing ${name}: ${facet}=${value}`);
  return c;
};
const pick = (facet, value) => {
  const c = slot.controls.find(c => c.dataset.facet === facet && c.dataset.value === value);
  assert(c, `missing ${facet}=${value}`); c.click();
};
ui.render(info);
assert.equal([...slot.html.matchAll(/class="guide-question-block"/g)].length, 1);
assert(!slot.html.includes('class="guide-mechanisms"')); // progressive disclosure
control('guide-tab', 'entry', 'enforce').click();
pick('resource', 'memory');
pick('scope', 'server');
pick('behavior', 'wait');
assert(slot.html.includes('Foreground admission queueing by memory requires'));
assert(slot.html.includes('defers background work'));
assert(!slot.html.includes('merges-memory"') || slot.html.includes('Closest options:'));
control('guide-reset').click();
pick('resource', 'memory');
pick('scope', 'query');
pick('behavior', 'spill');
assert(!slot.html.includes('id="guide-m-spill-set"'));
assert(slot.html.includes('id="guide-m-spill-distinct"'));
const selector = control('guide-version-select');
selector.value = '26.10';
selector.handlers.change({currentTarget: selector});
assert(!slot.html.includes('class="guide-mechanisms"')); // old picks cleared
pick('resource', 'memory'); pick('scope', 'query'); pick('behavior', 'spill');
assert(slot.html.includes('id="guide-m-spill-set"'));
assert(slot.html.includes('<dt>Configuration</dt>'));
assert(slot.html.includes('<dt>Scope</dt>'));
assert(!slot.html.includes('Accounts for'));
assert(slot.html.includes('<ul class="guide-configurations">'));
assert(slot.html.includes('<li data-configuration="profile">User or profile settings</li>'));
assert(slot.html.includes('<li data-configuration="query">Query or session settings</li>'));
assert(!slot.html.includes('Configured through'));
assert(slot.html.includes('<summary>How to observe</summary>'));
const writes = slot.writes;
// Opening a native details element changes the DOM, not the guide's filters.
slot.html = slot.html.replace('<details class="guide-evidence">', '<details open class="guide-evidence">');
ui.render(info); // the same call made by a periodic session refresh
assert.equal(slot.writes, writes);
assert(slot.html.includes('<details open class="guide-evidence">'));
control('guide-map-toggle').click();
const stage = slot.controls.find(c => c.dataset.node === 'a' && c.dataset.stage === 'execution');
assert(stage); stage.click();
assert(slot.html.includes('Node A · Execution'));
assert(!slot.html.includes('class="guide-mechanism selected"'));
assert(!slot.html.includes('class="guide-stage-tag selected"'));
assert(slot.html.includes('guide-field-identifiers'));
assert(slot.html.includes('_<wbr>'));
control('guide-tab', 'entry', 'diagnose').click();
pick('behavior', 'kill');
pick('errors', 'MEMORY_RESERVATION_KILLED');
assert(slot.html.includes('id="guide-m-workload-memory"'));
assert(slot.html.includes('Query settings (26.9+)'));
assert(slot.html.includes('<code class="guide-inline-code">system.scheduler</code>'));
assert(slot.html.includes('<code class="guide-inline-code">query_id</code>'));
const ids = version => window.PE.guide.forVersion(info.guide, version).mechanisms.map(m => m.id);
assert(!ids('26.9').includes('workload-spill'));
assert(ids('26.10').includes('workload-spill'));
assert(ids('26.10.1').includes('workload-spill'));
assert.equal(ids('').length, info.guide.mechanisms.length);
"""
    result = subprocess.run(["node", "-e", script], input=json.dumps(_browser_group(group)),
                            cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
