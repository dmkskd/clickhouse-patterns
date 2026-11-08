"""Gauge history rendering and replay stay independent of workload implementation."""
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_resource_history_keeps_limits_named_groups_and_sampled_values():
    code = r"""
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
global.window = {};
function element(tag) {return {tag,style:{},children:[],events:{},attrs:{},classList:{add(){}},
  append(...nodes){nodes.forEach(node=>{node.remove?.();node.parent=this;this.children.push(node);});},
  setAttribute(k,v){this.attrs[k]=v;}, getAttribute(k){return this.attrs[k]??null;},
  replaceChildren(...nodes){this.children.forEach(node=>{node.parent=null;});this.children=[];this.append(...nodes);},
  addEventListener(k,v){this.events[k]=v;},
  showModal(){this.open=true;}, close(){this.open=false;this.events.close?.();},
  remove(){if(this.parent){this.parent.children=this.parent.children.filter(node=>node!==this);this.parent=null;}this.removed=true;}};}
const desc=node=>node.children.flatMap(child=>[child,...desc(child)]);
global.document={createElement:element,createElementNS:(_ns,tag)=>element(tag),body:element('body')};
vm.runInThisContext(fs.readFileSync('explorer/chart-tooltip.js','utf8'));
vm.runInThisContext(fs.readFileSync('explorer/experiment-views.js','utf8'));
let requestTipParts;
window.PE.chartTooltip.create=()=>({show(_anchor,...parts){requestTipParts=parts;},hide(){}});
vm.runInThisContext(fs.readFileSync('explorer/experiment-intervals.js','utf8'));
let hoverContent;
window.PE.chartTooltip.create=()=>({show(_anchor,content){hoverContent=content;},hide(){}});
vm.runInThisContext(fs.readFileSync('explorer/experiment-series-plot.js','utf8'));
vm.runInThisContext(fs.readFileSync('explorer/experiment-series.js','utf8'));
const run={results:{attempts:[{role:'read',index:3,start_ms:90,end_ms:110,outcome:'rejected',id:'attempt-3',resource:'named-reader',size:32},{role:'read',index:4,start_ms:90,end_ms:115,outcome:'completed',id:'attempt-4',resource:'named-reader',size:8},{role:'read',index:5,start_ms:90,end_ms:112,outcome:'failed',resource:'named-reader',size:16,server:{event:'ran'}}],gauges:[
 {group:'named-reader',group_label:'Readers',label:'Reserved',unit:'MiB',limit:64,
  events:[{id:'attempt-3',ms:110,label:'Request 3 rejected',kind:'rejected',details:[['Reason','Admission timed out'],['Requested','32 MiB']],note:'A sampled state is not an admission decision.'}],
  points:[{ms:200,value:0},{ms:0,value:0},{ms:100,value:64},{ms:NaN,value:2},{ms:100,value:-1}]},
 {group:'named-reader',group_label:'Readers',label:'Pending',unit:'requests',limit:16,
  points:[{ms:0,value:0},{ms:100,value:3},{ms:200,value:0}]},
 {group:'named-writer',group_label:'Writers',label:'Reserved',unit:'MiB',limit:null,
  points:[{ms:0,value:0},{ms:100,value:16},{ms:200,value:0}]}
]}};
const config={views:[{type:'time-series',source:'gauges',label:'Usage',intervals:{source:'attempts',label:'Requests',group_field:'resource',id_field:'id',size_field:'size',size_unit:'MiB',admitted_field:'server.event',admitted_values:['ran'],lanes:{read:'Workers'}}}]};
const prepared=window.PE.experimentViews.prepare(config,[run]);
assert.equal(prepared.columns.length,1);
const column=prepared.columns[0];
assert.equal(column.value(run),64);
const preview=column.render(run);
assert.equal(preview.attrs['aria-haspopup'],'dialog');
assert.equal(preview.children.length,1);
assert(desc(preview.children[0]).some(n=>n.attrs.class==='resource-series-limit'));
const line=desc(preview.children[0]).find(n=>n.attrs.class==='resource-series-line');
assert(line.attrs.d.includes('H')); // gauge steps, no fabricated smooth curve
preview.events.click();
const dialog=document.body.children.at(-1), header=dialog.children[0];
assert.equal(dialog.open,true);
const select=header.children[1], name=dialog.children[1], plots=dialog.children[2];
const controls=dialog.children[3], slider=controls.children[1];
assert.equal(name.textContent,'named-reader');
assert.equal(plots.children.length,1);
assert(plots.children[0].children[1].children[0].children[1].textContent.includes('At limit'));
assert.equal(plots.children[0].children[3].hidden,true,'No empty request inspector or dropdown');
const marker=desc(plots.children[0].children[2]).find(n=>n.attrs.class==='resource-request-box rejected');
assert(desc(plots.children[0].children[2]).some(n=>n.attrs.class==='resource-series-secondary'));
assert(desc(plots.children[0].children[2]).some(n=>n.attrs.class==='resource-series-secondary-limit'));
assert(marker);
const small=desc(plots.children[0].children[2]).find(n=>n.attrs.class==='resource-request-box completed');
assert.equal(marker.attrs['data-admission'],'outside-stack');
assert.equal(small.attrs['data-admission'],'admitted');
const failed=desc(plots.children[0].children[2]).find(n=>n.attrs.class==='resource-request-box failed');
assert.equal(failed.attrs['data-admission'],'admitted');
assert(Number(failed.attrs.y)>=25,'Confirmed execution failures remain inside the memory plot');
assert(Number(marker.attrs.y)+Number(marker.attrs.height)<Number(small.attrs.y),'Rejected demand stacks directly on the admitted blocks');
assert(!desc(plots.children[0].children[2]).some(n=>n.attrs.class==='request-demand-budget'));
assert(!desc(plots.children[0].children[2]).some(n=>n.attrs.class==='resource-request-band'));
const arrival=desc(plots.children[0].children[2]).find(n=>n.attrs.class==='resource-request-arrival');
const plotLimit=desc(plots.children[0].children[2]).find(n=>n.attrs.class==='resource-series-limit');
// Both admitted and rejected demand use the same MiB axis; admitted requests start at zero.
assert.equal(Number(small.attrs.y)+Number(small.attrs.height)+1,252);
assert(Math.abs((252-Number(plotLimit.attrs.y1))/64-(Number(small.attrs.height)+1)/8)<1e-8);
marker.events.click();
assert.equal(arrival.attrs.visibility,'visible');
assert.equal(Number(arrival.attrs.x1),Number(marker.attrs.x));
assert.equal(slider.value,110);
const snapshot=plots.children[0].children[1];
assert.equal(snapshot.children[2].children[1].textContent,'1 at 0.11 s');
assert.equal(snapshot.children[3].children[1].textContent,'0 at 0.11 s');
slider.value=95; slider.events.input();
assert.equal(snapshot.children[2].children[1].textContent,'1 at 0.1 s');
assert.equal(snapshot.children[3].children[1].textContent,'1 at 0.1 s');
assert.equal(snapshot.children[4].children[1].textContent,'1 at 0.1 s');
const inspector=plots.children[0].children[3];
assert.equal(inspector.hidden,false);
assert.equal(inspector.children[0].children[0].children[0].textContent,'Request 3 rejected');
assert.equal(inspector.children[0].children[0].children[1].children[1].textContent,'Admission timed out');
slider.value=200; slider.events.input();
assert.equal(snapshot.children[2].children[1].textContent,'0 at 0.2 s');
assert.equal(snapshot.children[3].children[1].textContent,'0 at 0.2 s');
assert.equal(snapshot.children[4].children[1].textContent,'0 at 0.2 s');
assert.equal(plots.children[0].children.length,4,'Resource values stay together above the graph');
assert(plots.children[0].children[1].children[1].children[1].textContent.startsWith('0 requests'));
assert(plots.children[0].children[1].children[0].children[1].textContent.startsWith('0 MiB'));
assert(!plots.children[0].children[1].children[0].children[1].textContent.includes('At limit'));
slider.value=150; slider.events.input();
assert(plots.children[0].children[1].children[0].children[1].textContent.startsWith('64 MiB')); // last observation, not interpolation
// Both metric scales and the request share the same SVG time coordinate.
const svgChart=plots.children[0].children[2];
assert.equal(Number(marker.attrs.x),48+90/200*804);
assert.equal(Number(marker.attrs.width),20/200*804);

marker.events.mouseenter();
const textOf=(node)=>[node.textContent||'',...(node.children||[]).map(textOf)].join(' ');
const requestText=requestTipParts.map(textOf).join(' ');
assert(requestText.includes('Admission timed out'),'Hover explains the recorded rejection reason');
assert(requestText.includes('32 MiB'),'Hover includes the requested size');
assert(requestText.includes('sampled headroom before response'));
assert(requestText.includes('not the admission state'));
marker.events.mouseleave();
svgChart.getBoundingClientRect=()=>({left:0,top:0,width:900,height:310});
const hit=desc(svgChart).find(n=>n.attrs.class==='resource-series-hit');
hit.events.mousemove({clientX:48+804*.75,clientY:100});
assert.equal(hoverContent.children[0].textContent,'Time 0.15 s');
assert.equal(hoverContent.children[1].children[1].textContent,'64 MiB / 64 MiB · sample 0.1 s');
assert.equal(hoverContent.children[1].children[3].textContent,'3 requests / 16 requests · sample 0.1 s');
hit.events.mousemove({clientX:852,clientY:100});
assert(hoverContent.children[1].children[3].textContent.startsWith('0 requests'));
hit.events.mouseleave();
assert.equal(desc(svgChart).find(n=>n.attrs.class==='resource-series-hover').attrs.visibility,'hidden');
assert(plots.children[0].children[1].children[1].children[1].textContent.includes('3 requests'));
select.value='named-writer'; select.events.change();
assert.equal(name.textContent,'named-writer');
assert.equal(plots.children.length,1);
assert(plots.children[0].children[1].children[0].children[1].textContent.includes('No configured limit'));

let stopped=false; dialog.events.keydown({key:'Escape',stopPropagation(){stopped=true;}});
assert(stopped);
header.children[2].events.click(); assert(dialog.removed);
assert.equal(column.render({results:{}}).textContent,'Not recorded');
assert.equal(window.PE.experimentViews.prepare(config,[{results:{}}]).columns.length,0);
// Painting order is explicit, and each DOM node has one parent.
assert.deepEqual(svgChart.children.map(layer=>layer.getAttribute('data-layer')),
 ['background','requests','metrics','events','interaction']);
assert(desc(svgChart.children[1]).includes(marker));
assert(desc(svgChart.children[2]).includes(plotLimit));
const parent=element('g'), secondParent=element('g'), child=element('path');
parent.append(child);secondParent.append(child);secondParent.append(child);
assert.equal(parent.children.length,0);assert.equal(secondParent.children.length,1);
// Shared previews retain comparison scaling; modal playback ends with its run.
const longer=JSON.parse(JSON.stringify(run));
longer.results.gauges.forEach(metric=>metric.points.forEach(point=>point.ms*=10));
window.PE.experimentViews.prepare(config,[run,longer]).columns[0].render(run).events.click();
const shortDialog=document.body.children.at(-1);
assert.equal(shortDialog.children[3].children[1].max,200);
shortDialog.close();
// Every metric is rendered; a third metric gets another panel.
const third=JSON.parse(JSON.stringify(run));
third.results.gauges.push({group:'named-reader',label:'Third metric',unit:'units',limit:10,
 points:[{ms:0,value:0},{ms:200,value:8}]});
window.PE.experimentViews.prepare(config,[third]).columns[0].render(third).events.click();
const panels=document.body.children.at(-1).children[2].children;
assert.equal(panels.length,2);
assert.equal(panels[1].children[0].textContent,'Third metric');
assert(panels[1].children[1].children[0].children[1].textContent.includes('units'));
// Metric-only views identify execution failures without implying request stacks.
document.body.children.at(-1).close();
const failedRun=JSON.parse(JSON.stringify(run));
failedRun.results.gauges[0].events[0].kind='failed';
failedRun.results.gauges[0].events[0].label='Memory limit failure';
window.PE.experimentViews.prepare({views:[{type:'time-series',source:'gauges'}]},[failedRun]).columns[0].render(failedRun).events.click();
const failureDialog=document.body.children.at(-1);
const failureMarker=desc(failureDialog).find(node=>node.attrs.class==='resource-series-event failed');
assert(failureMarker);
assert(failureMarker.attrs['aria-label'].includes('event'));
const keys=failureDialog.children[4].children[0].children;
assert(keys.some(key=>key.textContent==='Execution failed'));
assert(!keys.some(key=>key.textContent==='Completed'));

"""
    result = subprocess.run(['node', '-e', code], cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_admitted_stack_excludes_rejections_and_unconfirmed_failures():
    code = r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
global.window={PE:{chartTooltip:{create:()=>({show(){},hide(){}})},experimentViews:{register(){}}}};
global.document={};
vm.runInThisContext(fs.readFileSync('explorer/experiment-intervals.js','utf8'));
const layout=window.PE.intervalTimeline.requestLayout;
const view={size_field:'size',admitted_field:'evidence.event',admitted_values:['ran']};
const requests=[
 {index:0,role:'read',start_ms:0,end_ms:10,size:256,outcome:'rejected'},
 {index:1,role:'read',start_ms:0,end_ms:10,size:8,outcome:'completed'},
 {index:2,role:'read',start_ms:0,end_ms:10,size:32,outcome:'completed'},
 {index:3,role:'read',start_ms:0,end_ms:10,outcome:'not_sent'},
 {index:4,role:'write',start_ms:0,end_ms:10,size:16,outcome:'failed',evidence:{event:'ran'}},
 {index:5,role:'read',start_ms:0,end_ms:10,size:128,outcome:'failed'},
 {index:6,role:'read',start_ms:10,end_ms:20,size:64,outcome:'completed'},
 {index:7,role:'read',start_ms:20,end_ms:19,size:999,outcome:'completed'}
];
const result=layout(requests,view);
assert(result.sized,'Unsent requests with no size cannot disable admitted sizing');
assert.equal(result.extent,64,'Huge rejected/unknown demands do not increase the memory scale');
assert.deepEqual(result.admitted.map(r=>r.index),[1,2,4,6]);
assert.deepEqual(result.unadmitted.map(r=>r.index),[0,3,5]);
assert.deepEqual(result.admitted.map(r=>result.placements.get(r).bottom),[0,8,40,0]);
assert.equal(result.placements.size,4);
assert.equal(result.admitted.at(-1).lane,0,'Released capacity is reused at the bottom');
assert(requests.every(r=>!Object.hasOwn(r,'lane')),'Layout cannot mutate saved requests');
assert.equal(layout([requests[0]],view).extent,1);
assert.equal(layout([requests[0]],view).sized,false);
const rejected=layout([
 {start_ms:0,end_ms:10,size:8,outcome:'completed'},
 {start_ms:0,end_ms:10,size:32,outcome:'rejected'},
 {start_ms:0,end_ms:10,size:8,outcome:'rejected'},
 {start_ms:10,end_ms:20,size:16,outcome:'rejected'}
],view);
assert(rejected.rejectedSized);
assert.equal(rejected.stackExtent,48);
assert.deepEqual(rejected.rejected.map(r=>rejected.rejectedPlacements.get(r).bottom),[8,40,0]);
assert.equal(rejected.extent,8);
assert.equal(layout([],view).packed.length,0);
const unsized=layout([{role:'read',start_ms:0,end_ms:10,outcome:'completed'}],view);
assert(!unsized.sized);assert.equal(unsized.admitted.length,1);
"""
    result = subprocess.run(['node', '-e', code], cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
