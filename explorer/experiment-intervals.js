// Client intervals: lane packing, outcomes and a shared scale across saved runs.
// Domain labels and tooltip fields come from the experiment's view declaration.
window.PE = window.PE || {};
(() => {
  "use strict";
  const tooltip = window.PE.chartTooltip.create("timeline-tip request-tip");

  function showRequestTip(bar, label, request, outcome, details) {
    const header = document.createElement("div");
    header.className = "request-tip-header";
    const name = document.createElement("strong");
    name.textContent = `${label} ${request.index ?? ""}`.trim();
    const status = document.createElement("span");
    status.className = `request-tip-status ${outcome}`;
    status.textContent = outcome.replaceAll("_", " ");
    header.append(name, status);
    const timing = document.createElement("dl");
    timing.className = "request-tip-timing";
    for (const [label, value] of [
      ["Request duration", request.end_ms - request.start_ms],
      ["Start", request.start_ms], ["End", request.end_ms],
    ]) {
      const term = document.createElement("dt");
      term.textContent = label;
      const number = document.createElement("dd");
      number.textContent = `${value.toFixed(2)} ms`;
      timing.append(term, number);
    }
    const evidence = document.createElement("dl");
    evidence.className = "request-tip-details";
    details.forEach(([label, value]) => {
      const term = document.createElement("dt");
      term.textContent = label;
      const detail = document.createElement("dd");
      detail.textContent = String(value);
      evidence.append(term, detail);
    });
    tooltip.show(bar, header, timing, ...(details.length ? [evidence] : []));
  }
  function requestLanes(requests, role) {
    const ends = [];
    return (requests || []).filter((request) => request.role === role &&
      Number.isFinite(request.start_ms) && Number.isFinite(request.end_ms) &&
      request.start_ms >= 0 && request.end_ms >= request.start_ms)
      .slice().sort((a, b) => a.start_ms - b.start_ms).map((request) => {
        let lane = ends.findIndex((end) => end <= request.start_ms);
        if (lane < 0) lane = ends.length;
        ends[lane] = Math.max(request.end_ms, request.start_ms + 1);
        return { ...request, lane };
      });
  }

  function requestTimeline(requests, scale, view, expanded = false) {
    const chart = document.createElement("div");
    chart.className = "request-gantt";
    const labels = { ...view.lanes };
    requests.forEach((request) => { labels[request.role] ??= request.role; });
    for (const [role, label] of Object.entries(labels)) {
      const row = document.createElement("div");
      row.className = "request-gantt-row";
      const name = document.createElement("span");
      name.textContent = label;
      const track = document.createElement("div");
      track.className = "request-gantt-track";
      const laneRequests = requestLanes(requests, role);
      const lanes = Math.max(1, ...laneRequests.map((request) => request.lane + 1));
      const pitch = expanded ? 12 : 4;
      track.style.height = `${Math.max(expanded ? 10 : 6, lanes * pitch)}px`;
      laneRequests.forEach((request) => {
        const bar = document.createElement("span");
        const outcome = ["completed", "rejected", "failed", "not_sent"].includes(request.outcome) ? request.outcome : "failed";
        bar.className = `request-gantt-bar ${outcome}`;
        bar.style.left = `${Math.min(100, request.start_ms / scale * 100)}%`;
        bar.style.width = `${Math.max(0, Math.min(request.end_ms, scale) - request.start_ms) / scale * 100}%`;
        bar.style.top = `${request.lane * pitch}px`;
        const details = Object.entries(view.details || {}).flatMap(([name, path]) => {
          const value = path.split(".").reduce((object, key) => object?.[key], request);
          return value == null ? [] : [[name, value]];
        });
        bar.setAttribute("aria-label", [
          `${label} ${request.index ?? ""}: ${outcome}`,
          `Client: ${request.start_ms.toFixed(1)}–${request.end_ms.toFixed(1)} ms`,
          `Elapsed: ${(request.end_ms - request.start_ms).toFixed(1)} ms`,
          ...details.map(([name, value]) => `${name}: ${value}`),
        ].join("\n"));
        const show = () => showRequestTip(bar, label, request, outcome, details);
        bar.addEventListener("mouseenter", show);
        bar.addEventListener("mouseleave", tooltip.hide);
        if (expanded) {
          bar.tabIndex = 0;
          bar.addEventListener("focus", show);
          bar.addEventListener("blur", tooltip.hide);
        }
        track.append(bar);
      });
      row.append(name, track);
      chart.append(row);
    }
    return chart;
  }

  function requestLegend(requests, expanded = false) {
    const legend = document.createElement("div");
    legend.className = "request-gantt-legend";
    const keys = document.createElement("div");
    keys.className = "resource-history-legend-keys";
    const outcomes = [["completed", "Completed"], ["rejected", "Rejected"], ["failed", "Failed"]];
    if (requests.some((request) => request.outcome === "not_sent")) outcomes.push(["not_sent", "Not sent"]);
    outcomes.forEach(([kind, label]) => {
      const key = document.createElement("span");
      key.className = `resource-history-key ${kind}`;
      key.textContent = label;
      keys.append(key);
    });
    const hint = document.createElement("p");
    hint.textContent = expanded
      ? "Hover for request details. Zoom and scroll to explore shorter intervals."
      : "Request durations include network and server time.";
    legend.append(keys, hint);
    return legend;
  }

  function requestLayout(requests, view) {
    const field = (object, path) => path ? path.split(".").reduce((value, key) => value?.[key], object) : null;
    const packed = (requests || []).filter((request) => Number.isFinite(request.start_ms) &&
      Number.isFinite(request.end_ms) && request.start_ms >= 0 && request.end_ms >= request.start_ms)
      .map((request, order) => ({...request, order}))
      .sort((a, b) => a.start_ms - b.start_ms || a.order - b.order);
    const isAdmitted = (request) => request.outcome === "completed" ||
      (request.outcome === "failed" && view.admitted_field &&
        (view.admitted_values || []).includes(field(request, view.admitted_field)));
    const admitted = packed.filter(isAdmitted), unadmitted = packed.filter((request) => !isAdmitted(request));
    const lanesFor = (items) => {
      const ends = [];
      items.forEach((request) => {
        let lane = ends.findIndex((end) => end <= request.start_ms);
        if (lane < 0) lane = ends.length;
        request.lane = lane;
        ends[lane] = Math.max(request.end_ms, request.start_ms + 1);
      });
      return Math.max(1, ends.length);
    };
    const lanes = lanesFor(admitted), bandLanes = lanesFor(unadmitted);
    const pitch = Math.min(10, 64 / lanes);
    // Missing sizes on unsent/rejected attempts must not disable admitted sizing.
    const sized = Boolean(view.size_field && admitted.length && admitted.every((request) =>
      Number.isFinite(field(request, view.size_field)) && field(request, view.size_field) > 0));
    const stack = (items) => {
      let extent = 1;
      const active = [], placements = new Map();
      items.forEach((request) => {
        for (let i = active.length - 1; i >= 0; i--) if (active[i].end <= request.start_ms) active.splice(i, 1);
        active.sort((a, b) => a.bottom - b.bottom);
        const size = field(request, view.size_field);
        let bottom = 0;
        for (const occupied of active) {
          if (bottom + size <= occupied.bottom) break;
          bottom = Math.max(bottom, occupied.bottom + occupied.size);
        }
        placements.set(request, {bottom, size});
        active.push({bottom, size, end: Math.max(request.end_ms, request.start_ms + 1)});
        extent = Math.max(extent, bottom + size);
      });
      return {extent, placements};
    };
    const {extent, placements} = stack(sized ? admitted : []);
    const rejected = unadmitted.filter((request) => request.outcome === "rejected");
    const other = unadmitted.filter((request) => request.outcome !== "rejected");
    const rejectedSized = Boolean(view.size_field && rejected.length && rejected.every((request) =>
      Number.isFinite(field(request,view.size_field)) && field(request,view.size_field)>0));
    const rejectedPlacements = new Map();
    let stackExtent = extent;
    if (rejectedSized) rejected.forEach((request) => {
      const overlaps = (item) => item.start_ms < Math.max(request.end_ms,request.start_ms+1) &&
        Math.max(item.end_ms,item.start_ms+1) > request.start_ms;
      // Position rejected demand above all admitted blocks in this interval.
      let bottom = Math.max(0,...admitted.filter(overlaps).map((item) => {
        const placed=placements.get(item);
        return placed ? placed.bottom+placed.size : 0;
      }));
      const size=field(request,view.size_field);
      const occupied=rejected.filter((item)=>rejectedPlacements.has(item) && overlaps(item))
        .map((item)=>rejectedPlacements.get(item)).sort((a,b)=>a.bottom-b.bottom);
      for (const placed of occupied) {
        if (bottom+size<=placed.bottom) break;
        bottom=Math.max(bottom,placed.bottom+placed.size);
      }
      rejectedPlacements.set(request,{bottom,size});
      stackExtent=Math.max(stackExtent,bottom+size);
    });
    return {packed, admitted, unadmitted, rejected, other, placements, sized, extent, stackExtent,
      rejectedSized, rejectedPlacements, field, lanes, bandLanes, pitch};
  }

  // Reuse interval lanes inside correlated views without their standalone dialog.
  window.PE.intervalTimeline = {
    requestLayout,
    overlay(chart, requests, scale, view, bounds, onSelect, hooks = {}) {
      const make = (tag, attrs) => {
        const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
        Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
        return node;
      };
      const {admitted, unadmitted, placements, sized, field, pitch, bandLanes, rejectedSized, rejectedPlacements, other, stackExtent:measuredExtent} = requestLayout(requests,view);
      const band = bounds.attemptBand || {top: bounds.top - 70, height: 50};
      const bandPitch = Math.min(10, band.height / bandLanes);
      if (other.length) {
        chart.append(make("rect", {x:bounds.left, y:band.top, width:bounds.width, height:band.height,
          class:"resource-request-band", "pointer-events":"none"}));
        const label = make("text", {x:bounds.left, y:band.top - 7, class:"resource-request-band-label"});
        label.textContent = "Unsent / admission unknown";
        chart.append(label);
      }
      const extent = bounds.ceiling || measuredExtent;
      [...admitted, ...unadmitted].forEach((request) => {
        const accepted = admitted.includes(request);
        const placement = accepted && sized ? placements.get(request) : rejectedSized ? rejectedPlacements.get(request) : null;
        const outcome = ["completed", "rejected", "failed", "not_sent"].includes(request.outcome) ? request.outcome : "failed";
        const bar = make("rect", {x:bounds.left + request.start_ms / scale * bounds.width,
          y:placement ? bounds.top+bounds.height-(placement.bottom+placement.size)/extent*bounds.height : !accepted ? band.top+band.height-(request.lane+1)*bandPitch : bounds.top+bounds.height-(request.lane+1)*pitch,
          // Give brief requests a readable footprint in the full-run overview.
          width:Math.max(14, (request.end_ms - request.start_ms) / scale * bounds.width),
          height:placement ? Math.max(1,placement.size/extent*bounds.height-1) : !accepted ? Math.max(.5,bandPitch-1) : Math.max(2,pitch-2),rx:1,tabindex:0,role:"button",
          "data-admission":accepted ? "admitted" : "outside-stack",
          class:`resource-request-box ${outcome}`,
          "aria-label":`${view.lanes?.[request.role] || request.role} ${request.index ?? ""}: ${outcome}`});
        const details = Object.entries(view.details || {}).flatMap(([name, path]) => {
          const value = path.split(".").reduce((object, key) => object?.[key], request);
          return value == null ? [] : [[name, value]];
        });
        const show = () => showRequestTip(bar, view.lanes?.[request.role] || request.role, request, outcome,
          [["Admission", accepted ? "Completed or confirmed execution failure" : outcome === "rejected" ? "Rejected demand above admitted requests" : outcome === "not_sent" ? "Not sent" : "Unknown; no execution evidence"],
            ["Interval", "Client request interval; reservation acquire/release times are not recorded"],
            ...details, ...(Number.isFinite(field(request,view.size_field)) ? [[view.size_label || "Requested size", `${field(request,view.size_field)} ${view.size_unit || ""}`.trim()]] : []),
            ...(accepted && sized ? [["Block height", "Declared demand, not measured allocated memory"]] : []), ...(hooks.hover?.(request) || [])]);
        const hide = () => {tooltip.hide(); hooks.hover?.(null);};
        const activate = () => {tooltip.hide(); onSelect(request);};
        bar.addEventListener("mouseenter", show);
        bar.addEventListener("mouseleave", hide);
        bar.addEventListener("focus", show);
        bar.addEventListener("blur", hide);
        bar.addEventListener("click", activate);
        bar.addEventListener("keydown", (event) => {
          if (event.key === "Enter" || event.key === " ") {event.preventDefault(); activate();}
        });
        chart.append(bar);
      });
      return {hideTooltip:tooltip.hide};
    },

  };

  function openTimeline(preview, requests, scale, view, run) {
    const dialog = document.createElement("dialog");
    dialog.className = "request-timeline-dialog";
    dialog.setAttribute("aria-label", view.label || "Request timeline");
    const header = document.createElement("header");
    const title = document.createElement("strong");
    title.textContent = view.label || "Request timeline";
    const time = document.createElement("span");
    time.textContent = run.started_at ? new Date(run.started_at).toLocaleTimeString() : "";
    const controls = document.createElement("div");
    controls.className = "request-timeline-controls";
    const button = (label, action, text = label) => {
      const element = document.createElement("button");
      element.type = "button";
      element.textContent = text;
      element.setAttribute("aria-label", label);
      element.addEventListener("click", action);
      controls.append(element);
      return element;
    };
    let zoom = 1;
    const zoomOut = button("Zoom out", () => resize(zoom / 2), "−");
    const fit = button("Fit timeline", () => resize(1), "Fit");
    const zoomIn = button("Zoom in", () => resize(zoom * 2), "+");
    button("Close timeline", () => dialog.close(), "×");
    header.append(title, time, controls);
    const viewport = document.createElement("div");
    viewport.className = "request-timeline-viewport";
    const chart = requestTimeline(requests, scale, view, true);
    const ruler = document.createElement("div");
    ruler.className = "request-timeline-ruler";
    for (let index = 0; index <= 8; index++) {
      const tick = document.createElement("span");
      tick.style.left = `${index / 8 * 100}%`;
      tick.textContent = `${(scale / 1000 * index / 8).toFixed(2)} s`;
      ruler.append(tick);
    }
    chart.prepend(ruler);
    viewport.append(chart);
    const note = requestLegend(requests, true);
    dialog.append(header, viewport, note);
    function resize(next) {
      tooltip.hide();
      zoom = Math.max(1, Math.min(16, next));
      chart.style.width = `${Math.max(640, viewport.clientWidth - 32) * zoom}px`;
      zoomOut.disabled = zoom === 1;
      zoomIn.disabled = zoom === 16;
      fit.textContent = zoom === 1 ? "Fit" : `${zoom}× · Fit`;
    }
    const onResize = () => resize(zoom);
    dialog.addEventListener("close", () => {
      tooltip.hide();
      window.removeEventListener("resize", onResize);
      dialog.remove();
      if (preview.isConnected) preview.focus();
    });
    dialog.addEventListener("keydown", (event) => {
      if (event.key === "Escape") event.stopPropagation();
    });
    dialog.addEventListener("click", (event) => {
      if (event.target !== dialog) return;
      const box = dialog.getBoundingClientRect();
      if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) dialog.close();
    });
    document.body.append(dialog);
    dialog.showModal();
    resize(1);
    window.addEventListener("resize", onResize);
  }

  function timelinePreview(requests, scale, view, run) {
    const preview = document.createElement("button");
    preview.type = "button";
    preview.className = "request-timeline-preview";
    preview.setAttribute("aria-haspopup", "dialog");
    preview.setAttribute("aria-label", `Expand ${view.label || "request timeline"}`);
    preview.append(requestTimeline(requests, scale, view));
    preview.addEventListener("click", () => openTimeline(preview, requests, scale, view, run));
    return preview;
  }

  window.PE.experimentViews.register("intervals", {
    reset() {
      if (!tooltip.anchor?.closest("dialog")) tooltip.hide();
    },
    prepare(view, runs) {
      const requests = (run) => Array.isArray(run.results[view.source]) ? run.results[view.source] : [];
      if (!runs.some((run) => requests(run).length)) return null;
      const duration = (run) => requests(run).reduce((end, request) =>
        Number.isFinite(request.end_ms) ? Math.max(end, request.end_ms) : end,
        Number(run.results.duration_ms) || 0);
      const scale = runs.reduce((longest, run) => Math.max(longest, duration(run)), 1);
      const legend = requestLegend(runs.flatMap(requests));
      return {
        column: {
          label: view.label || "Request timeline",
          title: "Request durations from dispatch to response, including network and server time.",
          value: duration,
          render: (run) => timelinePreview(requests(run), scale, view, run),
          exportColumns: [{label: `${view.label || "Request timeline"} duration (ms)`, value: duration}],
        },
        legend,
      };
    },
  });
})();
