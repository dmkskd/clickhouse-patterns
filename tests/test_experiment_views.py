"""Shared view contracts, independent of workload generation and ClickHouse."""
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_views_keep_lane_geometry_scale_exports_and_legacy_stages():
    code = r"""
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
global.window = {innerWidth:1000, innerHeight:800};
function element() { return {style:{}, children:[], events:{}, clientWidth:1000, offsetWidth:360, offsetHeight:200,
  append(...nodes) {this.children.push(...nodes); nodes.forEach(node=>{if(typeof node==='object') node.parent=this;});},
  prepend(...nodes) {this.children.unshift(...nodes);}, replaceChildren(...nodes) {this.children=[]; this.append(...nodes);},
  closest(tag) {return this.tag===tag ? this : this.parent?.closest(tag) || null;},
  getBoundingClientRect() {return {left:900,right:906,top:750,bottom:756};},
  setAttribute(name,value) {this[name]=value;}, addEventListener(name,fn) {this.events[name]=fn;},
  showModal() {this.open=true;}, close() {this.open=false; this.events.close?.();}, remove() {this.removed=true;}}; }
global.document = {createElement:tag=>Object.assign(element(),{tag}), body:element(), addEventListener(){}};
window.addEventListener = () => {}; window.removeEventListener = () => {};
for (const name of ['chart-tooltip', 'experiment-views', 'experiment-stages', 'experiment-intervals']) {
  vm.runInThisContext(fs.readFileSync(`explorer/${name}.js`, 'utf8'));
}
const views = window.PE.experimentViews;
const run = {results: {duration_ms:20, attempts: [
  {role:'worker', index:0, start_ms:0, end_ms:10, outcome:'completed', evidence:{name:'task-0'}},
  {role:'worker', index:1, start_ms:1, end_ms:2, outcome:'rejected'},
  {role:'worker', index:2, start_ms:2, end_ms:3, outcome:'completed'},
  {role:'worker', index:3, start_ms:10, end_ms:20, outcome:'completed'},
  {role:'sink', index:0, start_ms:2, end_ms:4, outcome:'completed'},
  {role:'worker', start_ms:20, end_ms:19, outcome:'failed'},
]}};
const view = {type:'intervals', source:'attempts', label:'Task intervals',
  lanes:{worker:'Workers', sink:'Sink'}, details:{'Task ID':'evidence.name'}};
const prepared = views.prepare({views:[view]}, [run]);
assert.equal(prepared.columns.length, 1);
assert.equal(prepared.legends.length, 1);
const column = prepared.columns[0], preview = column.render(run), chart = preview.children[0];
assert.equal(preview["aria-haspopup"], "dialog");
assert.equal(preview.children.length, 1);
assert.equal(column.label, 'Task intervals');
assert.equal(column.value(run), 20);
assert.equal(column.exportColumns[0].value(run), 20);
assert.equal(chart.children.length, 2);
assert.equal(chart.children[0].children[0].textContent, 'Workers');
const track = chart.children[0].children[1];
assert.equal(track.children.length, 4); // invalid interval excluded
assert.deepEqual(track.children.map(bar => bar.style.top), ['0px','4px','4px','0px']);
assert.equal(track.children[0].style.width, '50%');
assert(track.children[0]['aria-label'].includes('Task ID: task-0'));
assert(!track.children[0]['aria-label'].includes('query_log'));
assert.equal(track.children[1].className, 'request-gantt-bar rejected');
assert.equal(chart.children[1].children[0].textContent, 'Sink');
// Styled tooltips use text nodes and stay inside the viewport.
assert.equal(track.children[0].title, undefined);
track.children[0].events.mouseenter();
const tip = document.body.children.at(-1);
assert.equal(tip.role, 'tooltip');
assert.equal(tip.hidden, false);
assert.equal(tip.style.left, '546px');
assert.equal(tip.style.top, '542px');
assert.equal(tip.children[0].children[1].textContent, 'completed');
assert.equal(tip.children[1].children[1].textContent, '10.00 ms');
assert.equal(tip.children[2].children[1].textContent, 'task-0');
track.children[0].events.mouseleave(); assert.equal(tip.hidden, true);
// Expansion and zoom live entirely in the interval adapter.
preview.events.click();
const dialog = document.body.children.at(-1);
assert.equal(dialog.open, true);
let stopped = false;
dialog.events.keydown({key:'Escape', stopPropagation(){stopped=true;}});
assert.equal(stopped, true); // Escape must not reach pattern-page navigation
const controls = dialog.children[0].children[2].children;
const expanded = dialog.children[1].children[0];
assert.equal(expanded.style.width, '968px');
assert.equal(controls[0].disabled, true);
const expandedBar = expanded.children[1].children[1].children[0];
expandedBar.events.focus();
assert.equal(dialog.children.at(-1), tip); // top-layer dialog owns the tooltip
assert.equal(tip.hidden, false);
views.reset(); assert.equal(tip.hidden, false); // polling preserves modal hover
expandedBar.events.blur(); assert.equal(tip.hidden, true);
controls[2].events.click();
assert.equal(expanded.style.width, '1936px');
assert.equal(controls[0].disabled, false);
for (let i=0;i<8;i++) controls[2].events.click();
assert.equal(expanded.style.width, `${968*16}px`);
assert.equal(controls[2].disabled, true);
controls[1].events.click();
assert.equal(expanded.style.width, '968px');
controls[3].events.click();
assert.equal(dialog.removed, true);
// Every run uses the longest run's scale, including when run order changes.
const longer = {results:{duration_ms:40, attempts:run.results.attempts}};
const shared = views.prepare({views:[view]}, [longer,run]).columns[0];
assert.equal(shared.render(run).children[0].children[0].children[1].children[0].style.width, '25%');
assert.equal(shared.render({results:{}}).children[0].children[0].children[1].children.length, 0);
assert.equal(views.prepare({views:[view]}, [{results:{}}]).columns.length, 0);
// Structured payloads do not opt an experiment into a view implicitly.
assert.equal(views.prepare({}, [{results:{requests:run.results.attempts}}]).columns.length, 0);
const stageRun = {results:{stages:[{label:'A',ms:10},{label:'B',ms:5,extra:true}]}};
const stages = views.prepare({}, [stageRun]);
assert.equal(stages.columns.length, 1); // compatibility for workspace manifests
assert.equal(stages.columns[0].value(stageRun), 15);
assert.equal(stages.columns[0].render(stageRun).children.length, 2);
assert.deepEqual(stages.columns[0].exportColumns.map(c=>[c.label,c.value(stageRun)]),
  [['A (ms)','10.0'],['B (ms)','5.0']]);
assert.equal(views.prepare({views:[]}, [stageRun]).columns.length, 0);
const both = views.prepare({views:[view,{type:'stages',source:'stages'}]},
  [{results:{...stageRun.results,...run.results}}]);
assert.equal(new Set(both.columns.map(c=>c.key)).size, 2);
let resets = 0;
views.register('test', {reset(){resets++;}, prepare(){return {column:{label:'Custom',value:()=>1,render:()=>null}};}});
assert.equal(views.prepare({views:[{type:'test'}]}, [run]).columns[0].label, 'Custom');
views.reset(); assert.equal(resets, 1);
assert.throws(()=>views.register('test',{}), /Duplicate/);
assert.throws(()=>views.prepare({views:[{type:'missing'}]},[run]), /Unknown/);
"""
    result = subprocess.run(['node', '-e', code], cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
