// Sampled gauges and limits over time. Resource names and units are result data;
// this renderer has no knowledge of workload policies or ClickHouse tables.
window.PE = window.PE || {};
(() => {
  "use strict";
  const {number, pointAt} = window.PE.seriesPlot;
  function eventContent(event, count = 1) {
    const content = document.createElement("div");
    const heading = document.createElement("strong");
    heading.textContent = count > 1 ? `${count} events · ${event.label}` : event.label;
    const details = document.createElement("dl");
    (event.details || []).forEach(([label, value]) => {
      const term = document.createElement("dt"); term.textContent = label;
      const text = document.createElement("dd"); text.textContent = String(value);
      details.append(term, text);
    });
    const note = document.createElement("p"); note.textContent = event.note || "";
    content.append(heading, details, note);
    return content;
  }
  function seriesFor(run, source) {
    return (Array.isArray(run.results[source]) ? run.results[source] : []).map((series) => ({
      ...series,
      limit: Number.isFinite(series.limit) && series.limit > 0 ? series.limit : null,
      points: (series.points || []).filter((point) => Number.isFinite(point.ms) && point.ms >= 0 &&
        Number.isFinite(point.value) && point.value >= 0).slice().sort((a, b) => a.ms - b.ms),
      events: (series.events || []).filter((event) => Number.isFinite(event.ms) && event.ms >= 0)
        .slice().sort((a, b) => a.ms - b.ms),
    })).filter((series) => series.points.length);
  }
  function createSnapshot(metrics, groupRequests) {
    const summary = document.createElement("div"); summary.className = "resource-history-snapshot";
    summary.setAttribute("role","group"); summary.setAttribute("aria-label","Resource values at replay time");
    const readings = metrics.map((item,index) => {
      const cell = document.createElement("div"); cell.className=`resource-history-metric ${index===0 ? "primary" : "secondary"}`;
      const label = document.createElement("strong"); label.textContent = item.label;
      const value = document.createElement("div");
      cell.append(label,value); summary.append(cell);
      return {item,value};
    });
    const requestCounts = [];
    if (groupRequests.length) {
      for (const [outcome,label] of [["completed","Successful requests"],["rejected","Rejected requests"],["failed","Failed requests"]]) {
        if (outcome==="failed" && !groupRequests.some((request)=>request.outcome==="failed")) continue;
        const cell=document.createElement("div"); cell.className=`resource-history-count ${outcome}`;
        const heading=document.createElement("strong"); heading.textContent=label;
        const value=document.createElement("div"); value.className="resource-history-value";
        cell.setAttribute("title","Requests overlapping the replay cursor, grouped by their recorded outcome");
        cell.append(heading,value); summary.append(cell);
        requestCounts.push({outcome,value});
      }
    }
    return {element:summary, readings, requestCounts, groupRequests};
  }
  function updateSnapshot({readings, requestCounts, groupRequests}, ms) {
    requestCounts.forEach(({outcome,value}) => {
      const count=groupRequests.filter((request) => request.outcome===outcome && Number.isFinite(request.start_ms) && Number.isFinite(request.end_ms) && request.start_ms<=ms && ms<request.end_ms).length;
      value.textContent=`${count} at ${number(ms/1000)} s`;
    });
    readings.forEach(({item,value}) => {
      const point = pointAt(item.points,ms);
      const limit = item.limit;
      const capped = point && limit != null && point.value >= limit;
      value.className = capped ? "resource-history-value at-limit" : "resource-history-value";
      value.textContent = point ? `${number(point.value)} ${item.unit}` +
        (limit != null ? ` / ${number(limit)} ${item.unit}${capped ? " · At limit" : ""}` : " · No configured limit") +
        ` · sample ${number(point.ms / 1000)} s` : "No sample yet";
    });
  }
  function openHistory(preview, series, duration, label, overlay, requests = []) {
    const dialog = document.createElement("dialog");
    dialog.className = "resource-history-dialog";
    dialog.setAttribute("aria-label", label);
    const header = document.createElement("header");
    const title = document.createElement("strong"); title.textContent = label;
    const select = document.createElement("select");
    select.setAttribute("aria-label", "Named resource");
    const groups = [...new Set(series.map((item) => item.group))];
    groups.forEach((group) => {
      const option = document.createElement("option"); option.value = group;
      option.textContent = series.find((item) => item.group === group).group_label || group;
      select.append(option);
    });
    const close = document.createElement("button"); close.type = "button"; close.textContent = "×";
    close.setAttribute("aria-label", "Close usage history");
    close.addEventListener("click", () => dialog.close());
    let zoom = 1;
    const zoomSelect = document.createElement("select");
    zoomSelect.setAttribute("aria-label","Time scale");
    [1,4,16,64].forEach((value) => {
      const option=document.createElement("option"); option.value=String(value);
      option.textContent=value===1 ? "Full run" : `${value}× zoom`;
      zoomSelect.append(option);
    });
    zoomSelect.value="1";
    header.append(title, select, close, zoomSelect);
    const name = document.createElement("code"); name.className = "resource-history-name";
    const body = document.createElement("div"); body.className = "resource-history-plots";
    const controls = document.createElement("div"); controls.className = "resource-history-controls";
    const play = document.createElement("button"); play.type = "button"; play.textContent = "Play";
    const slider = document.createElement("input");
    Object.assign(slider, {type:"range",min:0,max:duration,step:0.01,value:0});
    slider.setAttribute("aria-label", "Replay time");
    const time = document.createElement("output");
    controls.append(play, slider, time);
    const note = document.createElement("div"); note.className="resource-history-legend";
    dialog.append(header, name, body, controls, note);
    let charts = [], timer = null, intervalGraphic = null;
    const inspectors = new Map();
    const field = (object, path) => path ? path.split(".").reduce((value, key) => value?.[key], object) : null;
    function selectRequest(request) {
      pause();
      const event = series.flatMap((item) => item.events).find((event) => event.id === field(request, overlay.id_field));
      const inspect = event && inspectors.get(event.id);
      if (inspect) inspect();
      else {slider.value = request.end_ms; update();}
    }
    function pause() { clearInterval(timer); timer = null; play.textContent = "Play"; }
    function update() {
      const ms = Number(slider.value); time.textContent = `${number(ms / 1000)} s`;
      
      charts.forEach(({graphic, snapshot}) => {
        graphic.select(ms);
        updateSnapshot(snapshot,ms);
      });
    }
    function showGroup() {
      pause(); name.textContent = select.value;
      inspectors.clear(); window.PE.seriesPlot.hideTooltip(); intervalGraphic?.hideTooltip();
      const items = series.filter((item) => item.group === select.value);
      const keys = document.createElement("div"); keys.className="resource-history-legend-keys";
      const legendItems = [["completed","Completed"],["rejected","Rejected"],["failed","Execution failed"],
        ["primary",items[0].label]];
      const secondary = items[1];
      if (secondary) legendItems.push(["secondary",secondary.label]);
      legendItems.forEach(([kind,label]) => {
        const key=document.createElement("span"); key.className=`resource-history-key ${kind}`;
        key.textContent=label; keys.append(key);
      });
      const explanation=document.createElement("p");
      explanation.textContent=overlay?.size_field ? `Block heights show ${(overlay.size_label || "requested sizes").toLowerCase()}. Lines show recorded samples.` : "Lines show recorded samples.";
      const hint=document.createElement("p"); hint.textContent="Hover for details. Click a request to inspect it.";
      note.replaceChildren(keys,explanation,hint);

      const pairs = [];
      for (let index=0;index<items.length;index+=2) pairs.push(items.slice(index,index+2));
      charts = pairs.map((metrics, index) => {
        const item = metrics[0];
        const panel = document.createElement("section");
        const heading = document.createElement("h4"); heading.textContent = metrics.map((metric) => metric.label).join(" · ");
        const groupRequests = overlay && index===0 ? requests.filter((request) => field(request, overlay.group_field) === select.value) : [];
        const snapshot = createSnapshot(metrics,groupRequests);
        const inspector = document.createElement("div"); inspector.className = "resource-event-inspector";
        const explanation = document.createElement("div");
        const inspect = (event) => {
          pause(); inspector.hidden=false;
          slider.value = event.ms; explanation.replaceChildren(eventContent(event)); update();
        };
        metrics.flatMap((metric)=>metric.events).forEach((event) => { if (event.id) inspectors.set(event.id, () => inspect(event)); });
        inspector.append(explanation);
        inspector.hidden = true;
        const demand = overlay ? window.PE.intervalTimeline.requestLayout(groupRequests,overlay) : null;
        const graphic = window.PE.seriesPlot.create({series:item, duration, inspect,
          secondary:metrics[1], withRequests:groupRequests.length>0, zoom,
          requestExtent:demand?.stackExtent || 0, withAttemptBand:Boolean(demand?.other.length), eventContent});
        graphic.chart.style.width=`${zoom*100}%`;
        if (groupRequests.length) {
          intervalGraphic = window.PE.intervalTimeline.overlay(graphic.requestLayer, groupRequests, duration, overlay,
            graphic.bounds, (request) => {graphic.highlight(request); selectRequest(request);}, {
              hover(request) {
                graphic.highlight(request);
                if (!request) return [];
                const event = metrics.flatMap((metric) => metric.events).find((event) => event.id === field(request, overlay.id_field));
                return [...(event?.details || []), ...metrics.flatMap((metric) => {
                  const observed = metric.points.filter((point) => point.ms >= request.start_ms && point.ms <= request.end_ms);
                  const peak = observed.length ? observed.reduce((a,b) => b.value > a.value ? b : a) : null;
                  const before = pointAt(metric.points, request.end_ms);
                  return [peak ? [`${metric.label} · sampled peak`,`${number(peak.value)} ${metric.unit} at ${number(peak.ms / 1000)} s`] : [`${metric.label} during request`, "No sample in this interval"],
                    ...(before && metric.limit != null ? [[`${metric.label} · sampled headroom before response`, `${number(Math.max(0, metric.limit-before.value))} ${metric.unit} at ${number(before.ms/1000)} s; not the admission state`]] : [])];
                })];
              },
            });
        }
        panel.append(heading, snapshot.element, graphic.chart, inspector);
        return {graphic, snapshot, panel};
      });
      body.replaceChildren(...charts.map((chart) => chart.panel));
      update();
    }
    zoomSelect.addEventListener("change",() => {
      zoom=Number(zoomSelect.value); showGroup();
      body.scrollLeft=Math.max(0,Number(slider.value)/duration*body.scrollWidth-body.clientWidth/2);
    });
    select.addEventListener("change", showGroup);
    slider.addEventListener("input", () => { pause(); update(); });
    play.addEventListener("click", () => {
      if (timer) { pause(); return; }
      if (Number(slider.value) >= duration) slider.value = 0;
      play.textContent = "Pause";
      let previous = performance.now();
      timer = setInterval(() => {
        const now = performance.now();
        slider.value = Math.min(duration, Number(slider.value) + now - previous);
        previous = now; update();
        if (Number(slider.value) >= duration) pause();
      }, 40);
    });
    dialog.addEventListener("keydown", (event) => { if (event.key === "Escape") event.stopPropagation(); });
    dialog.addEventListener("close", () => { pause(); window.PE.seriesPlot.hideTooltip(); intervalGraphic?.hideTooltip(); dialog.remove(); if (preview.isConnected) preview.focus(); });
    document.body.append(dialog);
    select.value = groups[0];
    // Open at the first metric's sampled peak, making pressure visible at once.
    slider.value = series[0].points.reduce((peak, point) => point.value > peak.value ? point : peak).ms;
    showGroup(); dialog.showModal();
  }
  window.PE.experimentViews.register("time-series", {
    reset() { window.PE.seriesPlot.reset(); },
    prepare(view, runs) {
      const data = (run) => seriesFor(run, view.source);
      const all = runs.flatMap(data);
      if (!all.length) return null;
      const intervals = (run) => view.intervals && Array.isArray(run.results[view.intervals.source]) ? run.results[view.intervals.source] : [];
      const runDuration = (run) => Math.max(1, Number(run.results.duration_ms) || 0,
        ...data(run).flatMap((item) => [...item.points, ...item.events].map((point) => point.ms)),
        ...intervals(run).filter((request) => Number.isFinite(request.end_ms)).map((request) => request.end_ms));
      const duration = Math.max(...runs.map(runDuration));
      return {column:{
        group:"Resources", label:view.label || "Resource usage",
        value:(run) => { const first = data(run)[0]; return first ? Math.max(...first.points.map((point) => point.value)) : null; },
        exportColumns:[],
        render(run) {
          const series = data(run);
          if (!series.length) { const empty = document.createElement("span"); empty.textContent = "Not recorded"; return empty; }
          const first = series[0], peak = Math.max(...first.points.map((point) => point.value));
          const preview = document.createElement("button"); preview.type = "button";
          preview.className = "resource-history-preview";
          preview.setAttribute("aria-haspopup", "dialog");
          preview.setAttribute("aria-label", `Expand ${view.label || "resource usage"}`);
          const caption = document.createElement("span");
          caption.textContent = `Peak ${number(peak)}${first.limit != null ? ` / ${number(first.limit)}` : ""} ${first.unit}`;
          preview.append(window.PE.seriesPlot.create({series:first,duration,compact:true}).chart, caption);
          preview.addEventListener("click", () => openHistory(preview, series, runDuration(run), view.label || "Resource usage", view.intervals, intervals(run)));
          return preview;
        },
      }};
    },
  });
})();
