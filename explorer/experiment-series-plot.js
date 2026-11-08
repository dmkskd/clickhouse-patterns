// SVG geometry, painting layers and pointer inspection for sampled metrics.
window.PE = window.PE || {};
(() => {
  "use strict";
  const eventTip = window.PE.chartTooltip.create("timeline-tip resource-event-tip");
  const svg = (tag, attributes = {}, text) => {
    const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
    Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, value));
    if (text != null) node.textContent = text;
    return node;
  };
  const number = (value) => Number(value.toFixed(2)).toString();
  function pointAt(points, ms) {
    let found = null;
    for (const point of points) {
      if (point.ms > ms) break;
      found = point;
    }
    return found;
  }
  function create({series, duration, compact = false, inspect = () => {}, secondary = null, withRequests = false, zoom = 1, requestExtent = 0, withAttemptBand = false, eventContent}) {
    const hasEvents = !compact && !withRequests && series.events.length > 0;
    const width = compact ? 180 : 900 * zoom, height = compact ? 40 : withRequests && withAttemptBand ? 360 : withRequests ? 280 : secondary ? 280 : hasEvents ? 200 : 170;
    const left = compact ? 2 : 48, right = compact ? 2 : secondary ? 48 : 12;
    const top = compact ? 4 : withRequests && withAttemptBand ? 110 : hasEvents ? 55 : 25, bottom = compact ? 2 : 28;
    const ceiling = Math.max(1, series.limit || 0, requestExtent, ...series.points.map((point) => point.value)) * 1.15;
    const x = (ms) => left + ms / duration * (width - left - right);
    const y = (value) => height - bottom - value / ceiling * (height - top - bottom);
    const chart = svg("svg", {viewBox:`0 0 ${width} ${height}`, role:"img",
      "aria-label":`${series.group_label || series.group}: ${series.label} over time in ${series.unit}`});
    chart.classList.add("resource-series-plot");
    // DOM order defines painting order. Request blocks never obscure metric lines.
    const layers = {};
    for (const name of ["background", "requests", "metrics", "events", "interaction"]) {
      layers[name] = svg("g", {"data-layer":name});
      chart.append(layers[name]);
    }
    if (!compact) {
      for (let tick = 0; tick <= 4; tick++) {
        const ms = duration * tick / 4;
        layers.metrics.append(svg("line", {x1:x(ms), x2:x(ms), y1:top, y2:withRequests ? height-28 : height-bottom, class:"resource-series-grid"}),
          svg("text", {x:x(ms), y:height-7, "text-anchor":tick === 4 ? "end" : "middle"}, `${number(ms / 1000)} s`));
      }
      layers.metrics.append(svg("text", {x:left-8, y:height-bottom, "text-anchor":"end"}, "0"),
        svg("text", {x:left-8, y:top+4, "text-anchor":"end"}, number(ceiling)),
        svg("text", {x:left, y:14}, secondary ? `${series.label} (${series.unit})` : series.unit));
    }
    if (series.limit != null) {
      layers.metrics.append(svg("line", {x1:left,x2:width-right,y1:y(series.limit),y2:y(series.limit),class:"resource-series-limit"}));
      if (!compact) layers.metrics.append(svg("text", {x:secondary ? left+8 : width-right,y:y(series.limit)-6,"text-anchor":secondary ? "start" : "end"}, `Limit ${number(series.limit)} ${series.unit}`));
    }
    let path = "";
    series.points.forEach((point, index) => {
      path += index ? `H${x(point.ms)}V${y(point.value)}` : `M${x(point.ms)},${y(point.value)}`;
    });
    const first = series.points[0], last = series.points.at(-1);
    layers.background.append(svg("path", {d:`${path}L${x(last.ms)},${y(0)}H${x(first.ms)}Z`,class:"resource-series-area"}));
    layers.metrics.append(svg("path", {d:path,class:"resource-series-line"}));
    if (secondary) {
      const max = Math.max(1, secondary.limit || 0, ...secondary.points.map((point) => point.value)) * 1.15;
      const sy = (value) => height - bottom - value / max * (height - top - bottom);
      let secondaryPath = "";
      secondary.points.forEach((point, index) => {
        secondaryPath += index ? `H${x(point.ms)}V${sy(point.value)}` : `M${x(point.ms)},${sy(point.value)}`;
      });
      layers.metrics.append(svg("path", {d:secondaryPath,class:"resource-series-secondary"}),
        svg("text",{x:width-right+8,y:top+4,"text-anchor":"start",class:"resource-series-secondary-label"},number(max)),
        svg("text",{x:width-right+8,y:height-bottom,"text-anchor":"start"},"0"),
        svg("text",{x:width-right,y:14,"text-anchor":"end",class:"resource-series-secondary-label"},`${secondary.label} (${secondary.unit})`));
      if (secondary.limit != null) layers.metrics.append(
        svg("line",{x1:left,x2:width-right,y1:sy(secondary.limit),y2:sy(secondary.limit),class:"resource-series-secondary-limit"}),
        svg("text",{x:width-right-4,y:sy(secondary.limit)-5,"text-anchor":"end",class:"resource-series-secondary-label"},`Limit ${number(secondary.limit)} ${secondary.unit}`));
    }
    if (hasEvents) {
      layers.metrics.append(svg("text", {x:left,y:31}, "Events"));
      const buckets = [];
      series.events.forEach((event) => {
        const last = buckets.at(-1);
        if (last && last[0].kind === event.kind && x(event.ms) - x(last[0].ms) < 12) last.push(event);
        else buckets.push([event]);
      });
      buckets.forEach((events) => {
        const first = events[0];
        const marker = svg("g", {class:`resource-series-event${first.kind === "failed" ? " failed" : ""}`,role:"button",tabindex:0,
          "aria-label":`${events.length} event${events.length > 1 ? "s" : ""} at ${number(first.ms/1000)} s. ${first.label}`});
        marker.append(svg("rect",{x:x(first.ms)-7,y:34,width:24,height:18,fill:"transparent"}),
          svg("circle",{cx:x(first.ms),cy:43,r:4}),
          svg("text",{x:x(first.ms)+7,y:47},String(events.length)));
        const show = () => eventTip.show(marker, eventContent(first, events.length));
        marker.addEventListener("mouseenter",show);
        marker.addEventListener("mouseleave",eventTip.hide);
        marker.addEventListener("focus",show);
        marker.addEventListener("blur",eventTip.hide);
        marker.addEventListener("click",() => {eventTip.hide(); inspect(first);});
        marker.addEventListener("keydown",(event) => {
          if (event.key === "Enter" || event.key === " ") {event.preventDefault(); eventTip.hide(); inspect(first);}
        });
        layers.events.append(marker);
      });
    }
    const emphasis = svg("rect", {y:top,height:height-bottom-top,class:"resource-request-window",visibility:"hidden"});
    const arrival = svg("line", {y1:top,y2:height-28,class:"resource-request-arrival",visibility:"hidden"});
    if (withRequests) layers.background.append(emphasis, arrival);
    const cursor = svg("line", {y1:top,y2:withRequests ? height-28 : height-bottom,class:"resource-series-cursor",visibility:"hidden"});
    const dot = svg("circle", {r:4,class:"resource-series-dot",visibility:"hidden"});
    if (!compact) {
      // A hit surface covers the metric area, leaving request boxes interactive.
      const hit = svg("rect", {x:left,y:top,width:width-left-right,height:height-bottom-top,
        fill:"transparent",class:"resource-series-hit"});
      const hoverLine = svg("line",{y1:top,y2:height-bottom,class:"resource-series-hover",visibility:"hidden"});
      const anchor = svg("rect",{width:1,height:1,fill:"transparent","pointer-events":"none"});
      hit.addEventListener("mousemove", (event) => {
        const box = chart.getBoundingClientRect();
        const px = (event.clientX-box.left)/box.width*width;
        const ms = Math.max(0,Math.min(duration,(px-left)/(width-left-right)*duration));
        hoverLine.setAttribute("x1",x(ms)); hoverLine.setAttribute("x2",x(ms));
        hoverLine.setAttribute("visibility","visible");
        anchor.setAttribute("x",x(ms));
        anchor.setAttribute("y",(event.clientY-box.top)/box.height*height);
        const content = document.createElement("div");
        const heading = document.createElement("strong"); heading.textContent = `Time ${number(ms/1000)} s`;
        const values = document.createElement("dl");
        [series,secondary].filter(Boolean).forEach((metric) => {
          const point = pointAt(metric.points,ms);
          const term = document.createElement("dt"); term.textContent = metric.label;
          const value = document.createElement("dd");
          value.textContent = point ? `${number(point.value)} ${metric.unit}` +
            (metric.limit != null ? ` / ${number(metric.limit)} ${metric.unit}` : "") +
            ` · sample ${number(point.ms/1000)} s` : "No sample yet";
          values.append(term,value);
        });
        const note = document.createElement("p"); note.textContent = "Most recent recorded samples at or before this time.";
        content.append(heading,values,note);
        eventTip.show(anchor,content);
      });
      hit.addEventListener("mouseleave",() => {hoverLine.setAttribute("visibility","hidden"); eventTip.hide();});
      layers.background.append(hit);
      layers.interaction.append(cursor,dot,hoverLine,anchor);
    }
    return {chart, requestLayer:layers.requests, bounds:{left,width:width-left-right,top,height:height-bottom-top,capacity:series.limit,ceiling,attemptBand:{top:35,height:52}}, highlight(request) {
      emphasis.setAttribute("visibility",request ? "visible" : "hidden");
      arrival.setAttribute("visibility",request ? "visible" : "hidden");
      if (!request) return;
      emphasis.setAttribute("x",x(request.start_ms));
      emphasis.setAttribute("width",Math.max(3,x(request.end_ms)-x(request.start_ms)));
      arrival.setAttribute("x1",x(request.start_ms)); arrival.setAttribute("x2",x(request.start_ms));
    }, select(ms) {
      const point = pointAt(series.points, ms);
      cursor.setAttribute("x1", x(ms)); cursor.setAttribute("x2", x(ms));
      cursor.setAttribute("visibility", point ? "visible" : "hidden");
      dot.setAttribute("visibility", point ? "visible" : "hidden");
      if (point) { dot.setAttribute("cx", x(point.ms)); dot.setAttribute("cy", y(point.value)); }
      return point;
    }};
  }
  window.PE.seriesPlot = {create, number, pointAt, hideTooltip:eventTip.hide,
    reset() { if (!eventTip.anchor?.closest("dialog")) eventTip.hide(); }};
})();
