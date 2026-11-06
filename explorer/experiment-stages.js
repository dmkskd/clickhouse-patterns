// Duration stages: shared by experiments that report ordered measured phases.
window.PE = window.PE || {};
(() => {
  "use strict";
  // Timeline: the run's per-row stages (averages, so they add up to the
  // average latency).
  // Segments in the order the script reports them; each takes the next
  // palette slot, so neighbours are always a validated pair. `extra`
  // segments are drawn but not summed.
  function runTimeline(run, source) {
    return (run.results[source] || []).map((stage, index) => ({
      label: stage.label, ms: Math.max(0, Number(stage.ms) || 0), index, extra: Boolean(stage.extra),
    }));
  }

  function timelineBar(segments, longest, totalLabel) {
    const bar = document.createElement("div");
    bar.className = "timeline-bar";
    if (!segments.length) return bar;
    bar.addEventListener("mouseenter", () => showTimelineTip(bar, segments, totalLabel));
    bar.addEventListener("mouseleave", hideTimelineTip);
    segments.forEach((segment) => {
      const piece = document.createElement("span");
      piece.className = `timeline-stage stage-${segment.index}`;
      piece.style.width = `${(segment.ms / longest) * 100}%`;
      bar.append(piece);
    });
    return bar;
  }

  // One shared tooltip for every bar: each stage with its colour, time and
  // share of the row latency, then the total.
  const tooltip = window.PE.chartTooltip.create("timeline-tip");
  function showTimelineTip(bar, segments, totalLabel) {
    // Shares are of the whole bar, extra segments included.
    const total = segments.filter((segment) => !segment.extra)
      .reduce((sum, segment) => sum + segment.ms, 0);
    const whole = segments.reduce((sum, segment) => sum + segment.ms, 0);
    const tipRow = (swatchClass, text, ms, share, extraClass = "") => {
      const row = document.createElement("div");
      row.className = `timeline-tip-row ${extraClass}`.trim();
      const swatch = document.createElement("i");
      if (swatchClass) swatch.className = swatchClass;
      const label = document.createElement("span");
      label.textContent = text;
      const value = document.createElement("b");
      value.textContent = `${ms.toFixed(1)} ms`;
      const percent = document.createElement("small");
      percent.textContent = share == null ? "" : `${Math.round(share * 100)}%`;
      row.append(swatch, label, value, percent);
      return row;
    };
    const rows = segments.map((segment) =>
      tipRow(`timeline-stage stage-${segment.index}`, segment.label, segment.ms, whole ? segment.ms / whole : null));
    const extras = segments.filter((segment) => segment.extra);
    const totals = [tipRow("", totalLabel, total, null, "total")];
    if (extras.length) {
      totals.push(tipRow("", `Including ${extras.map((segment) => segment.label).join(", ")}`, whole, 1, "total-sub"));
    }
    tooltip.show(bar, ...rows, ...totals);
  }

  function hideTimelineTip() {
    tooltip.hide();
  }

  function timelineLegend(segments) {
    if (!segments.length) return null;
    const legend = document.createElement("div");
    legend.className = "timeline-legend";
    segments.forEach((segment) => {
      const item = document.createElement("span");
      const swatch = document.createElement("i");
      swatch.className = `timeline-stage stage-${segment.index}`;
      item.append(swatch, segment.label);
      legend.append(item);
    });
    return legend;
  }

  window.PE.experimentViews.register("stages", {
    reset: hideTimelineTip,
    prepare(view, runs, experiment) {
      const segments = (run) => runTimeline(run, view.source);
      if (!runs.some((run) => segments(run).length)) return null;
      const longest = Math.max(1, ...runs.map((run) => segments(run).reduce((sum, segment) => sum + segment.ms, 0)));
      const labels = [...new Set(runs.flatMap((run) => segments(run).map((segment) => segment.label)))];
      return {
        column: {
          label: view.label || "where time goes",
          value: (run) => segments(run).reduce((sum, segment) => sum + segment.ms, 0),
          render: (run) => timelineBar(segments(run), longest, experiment.timeline_total || "Total"),
          exportColumns: labels.map((label) => ({
            label: `${label} (ms)`,
            value: (run) => segments(run).find((segment) => segment.label === label)?.ms.toFixed(1) ?? "",
          })),
        },
        legend: timelineLegend(segments(runs.find((run) => segments(run).length))),
      };
    },
  });
})();
