// Experiments panel: on-demand workloads declared under spec.experiments in a
// pattern's manifest. One form per experiment, a table of its saved runs with a
// per-run timeline, and Run/Reset actions. session.js creates it once and calls
// render() from its own render pass, passing the session state.
window.PE = window.PE || {};
window.PE.experiments = (() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const apiUrl = (path) => new URL(path.replace(/^\//, ""), document.baseURI).toString();

  function create(deps) {
    // deps: command(path, payload), confirmAction(message, label),
    //       showToast(message, kind), openLogs(), rerender()
    // An experiment that changes a config file also changes the catalog, and
    // the live-revision check reloads the page; keep the panel open across it.
    let experimentsOpen = false;
    try { experimentsOpen = sessionStorage.getItem("experiments-open") === "1"; } catch (_error) { /* storage blocked */ }
    function setExperimentsOpen(open) {
      experimentsOpen = open;
      try { sessionStorage.setItem("experiments-open", open ? "1" : "0"); } catch (_error) { /* storage blocked */ }
    }
    let experimentsPattern = null;  // pattern whose experiment forms are rendered
    let experimentsSeen = null;     // finished_at of the last experiment whose runs were fetched
    let experimentRuns = [];
    const sortState = {};           // experiment name -> { column, direction }

    function setVisible(id, visible) {
      $(id).hidden = !visible;
    }

    // Forms are built once per pattern so a refresh keeps typed values.
    async function loadExperimentRuns(slug) {
      try {
        const response = await fetch(apiUrl(`api/experiments?pattern=${encodeURIComponent(slug)}`), { cache: "no-store" });
        if (!response.ok) return;
        experimentRuns = (await response.json()).runs || [];
      } catch (_error) {
        return;
      }
      renderExperimentResults();
    }

    function renderExperimentForms(pattern) {
      $("experiments-body").replaceChildren(...pattern.experiments.map((experiment) => {
        const section = document.createElement("section");
        section.className = "experiment";
        section.dataset.experiment = experiment.name;
        const title = document.createElement("h4");
        title.textContent = experiment.title;
        const description = document.createElement("p");
        description.textContent = experiment.description;
        const form = document.createElement("form");
        form.className = "experiment-form";
        // Typed values survive the page reload a config change triggers.
        const storageKey = `experiment-values:${pattern.slug}:${experiment.name}`;
        let saved = {};
        try { saved = JSON.parse(sessionStorage.getItem(storageKey) || "{}"); } catch (_error) { saved = {}; }
        form.addEventListener("input", () => {
          try { sessionStorage.setItem(storageKey, JSON.stringify(Object.fromEntries(new FormData(form).entries()))); }
          catch (_error) { /* storage blocked */ }
        });
        experiment.parameters.forEach((parameter) => {
          const label = document.createElement("label");
          const name = document.createElement("span");
          name.textContent = parameter.label || parameter.name;
          const input = document.createElement("input");
          Object.assign(input, { type: "number", min: "1", step: Number.isInteger(parameter.default) ? "1" : "any", name: parameter.name, value: saved[parameter.name] ?? parameter.default, required: true });
          label.append(name, input);
          if (parameter.config) {
            const hint = document.createElement("small");
            hint.textContent = `${parameter.config.file} · a change reloads the session`;
            label.append(hint);
          }
          form.append(label);
        });
        const run = document.createElement("button");
        run.type = "submit";
        run.className = "primary";
        run.textContent = "Run";
        const reset = document.createElement("button");
        reset.type = "button";
        reset.className = "secondary";
        reset.textContent = "Reset";
        reset.title = "Delete the saved runs and restore the default values";
        reset.addEventListener("click", () => resetExperiments(pattern));
        const stop = document.createElement("button");
        stop.type = "button";
        stop.className = "stop";
        stop.textContent = "Stop";
        stop.title = "End the running workload; the config file is restored and the session reloaded";
        stop.hidden = true;
        stop.addEventListener("click", async () => {
          try { await deps.command(apiUrl("api/session/experiment/stop")); }
          catch (error) { deps.showToast(error.message, "error"); }
        });
        form.append(run, stop, reset);
        form.addEventListener("submit", async (event) => {
          event.preventDefault();
          deps.openLogs();
          const parameters = Object.fromEntries(new FormData(form).entries());
          try { await deps.command(apiUrl("api/session/experiment"), { experiment: experiment.name, parameters }); }
          catch (error) { deps.showToast(error.message, "error"); }
        });
        const results = document.createElement("div");
        results.className = "experiment-results";
        section.append(title, description, form, results);
        return section;
      }));
      renderExperimentResults();
    }

    async function resetExperiments(pattern) {
      if (!await deps.confirmAction(`Delete the ${experimentRuns.length} saved runs for ${pattern.slug} and restore the default values?`, "Reset")) return;
      try {
        await deps.command(apiUrl("api/experiments/clear"), { pattern: pattern.slug });
      } catch (error) {
        deps.showToast(error.message, "error");
        return;
      }
      try {
        pattern.experiments.forEach((experiment) =>
          sessionStorage.removeItem(`experiment-values:${pattern.slug}:${experiment.name}`));
      } catch (_error) { /* storage blocked */ }
      experimentRuns = [];
      renderExperimentForms(pattern);
    }

    // Timeline: the run's per-row stages (averages, so they add up to the
    // average latency), then the average ClickHouse INSERT execution, which is
    // per statement and drawn hatched.
    function runTimeline(run) {
      const segments = (run.results.stages || []).map((stage, index) => ({ label: stage.label, ms: Math.max(0, Number(stage.ms) || 0), index }));
      if (segments.length && run.results.insert_avg_ms != null) {
        segments.push({ label: "ClickHouse INSERT execution (avg per statement)", ms: Number(run.results.insert_avg_ms) || 0, index: "insert" });
      }
      return segments;
    }

    function timelineBar(segments, longest) {
      const bar = document.createElement("div");
      bar.className = "timeline-bar";
      if (!segments.length) return bar;
      bar.addEventListener("mouseenter", () => showTimelineTip(bar, segments));
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
    let timelineTip = null;
    function showTimelineTip(bar, segments) {
      if (!timelineTip) {
        timelineTip = document.createElement("div");
        timelineTip.className = "timeline-tip";
        timelineTip.setAttribute("role", "tooltip");
        document.body.append(timelineTip);
      }
      // Shares are of the whole bar: the row latency stages plus the INSERT
      // execution that follows the ClickHouse insert timestamp.
      const latency = segments.filter((segment) => segment.index !== "insert")
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
      const hasInsert = segments.some((segment) => segment.index === "insert");
      const totals = [tipRow("", "Average row latency (write to insert)", latency, null, "total")];
      if (hasInsert) totals.push(tipRow("", "Including INSERT execution", whole, 1, "total-sub"));
      timelineTip.replaceChildren(...rows, ...totals);
      const box = bar.getBoundingClientRect();
      timelineTip.hidden = false;
      const width = timelineTip.offsetWidth;
      const left = Math.max(8, Math.min(window.innerWidth - width - 8, box.right - width));
      const below = box.bottom + 8 + timelineTip.offsetHeight < window.innerHeight;
      timelineTip.style.left = `${left}px`;
      timelineTip.style.top = `${below ? box.bottom + 8 : box.top - timelineTip.offsetHeight - 8}px`;
    }

    function hideTimelineTip() {
      if (timelineTip) timelineTip.hidden = true;
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

    function renderExperimentResults() {
      hideTimelineTip();  // a rebuilt table removes the hovered bar without a mouseleave
      document.querySelectorAll("#experiments-body .experiment").forEach((section) => {
        const experiment = experimentsPattern?.experiments.find((item) => item.name === section.dataset.experiment);
        const target = section.querySelector(".experiment-results");
        const runs = experimentRuns.filter((run) => run.experiment === section.dataset.experiment).reverse();
        if (!experiment || !runs.length) {
          target.textContent = "No saved runs.";
          return;
        }
        const parameterNames = experiment.parameters.map((parameter) => parameter.name);
        // Declared results first, in manifest order, then any extra keys a script reports.
        const declared = new Map((experiment.results || []).map((result) => [result.name, result]));
        const resultNames = [...new Set([...declared.keys(), ...runs.flatMap((run) => Object.keys(run.results))])]
          .filter((name) => name !== "stages");
        // Sort by the chosen column; the default is newest first.
        const sort = sortState[experiment.name] || { column: "time", direction: -1 };
        const sortValue = (run) => {
          if (sort.column === "time") return new Date(run.started_at).getTime();
          if (sort.column === "timeline") return runTimeline(run).reduce((sum, segment) => sum + segment.ms, 0);
          const value = parameterNames.includes(sort.column) ? run.parameters[sort.column] : run.results[sort.column];
          return value == null || value === "" ? null : Number(value);
        };
        runs.sort((a, b) => {
          const x = sortValue(a), y = sortValue(b);
          if (x === null || y === null) return x === y ? 0 : x === null ? 1 : -1;  // empty cells last
          return sort.direction * (x - y);
        });
        const timelines = runs.map(runTimeline);
        const longest = Math.max(1, ...timelines.map((segments) => segments.reduce((sum, segment) => sum + segment.ms, 0)));
        const table = document.createElement("table");
        table.className = "experiment-table";
        const head = table.createTHead().insertRow();
        ["time", ...parameterNames, ...resultNames, "timeline"].forEach((name) => {
          const cell = document.createElement("th");
          cell.textContent = declared.get(name)?.label || name;
          cell.className = "sortable";
          if (sort.column === name) cell.setAttribute("aria-sort", sort.direction === 1 ? "ascending" : "descending");
          cell.addEventListener("click", () => {
            // A new column starts descending (largest first); clicking again reverses.
            sortState[experiment.name] = { column: name, direction: sort.column === name ? -sort.direction : -1 };
            renderExperimentResults();
          });
          if (declared.get(name)?.description) cell.title = declared.get(name).description;
          head.append(cell);
        });
        const body = table.createTBody();
        runs.forEach((run) => {
          const row = body.insertRow();
          row.insertCell().textContent = new Date(run.started_at).toLocaleTimeString();
          parameterNames.forEach((name) => { row.insertCell().textContent = run.parameters[name] ?? ""; });
          resultNames.forEach((name) => { row.insertCell().textContent = run.results[name] ?? ""; });
          row.insertCell().append(timelineBar(timelines[runs.indexOf(run)], longest));
        });
        const caption = table.createCaption();
        const sortLabel = sort.column === "time" && sort.direction === -1 ? "newest first"
          : `sorted by ${declared.get(sort.column)?.label || sort.column}, ${sort.direction === 1 ? "ascending" : "descending"}`;
        caption.textContent = `${runs.length} saved run${runs.length === 1 ? "" : "s"}, ${sortLabel}`;
        const stageLegend = timelineLegend(timelines.find((segments) => segments.length) || []);
        const legend = document.createElement("dl");
        legend.className = "experiment-legend";
        resultNames.filter((name) => declared.get(name)?.description).forEach((name) => {
          const term = document.createElement("dt");
          term.textContent = declared.get(name).label;
          const definition = document.createElement("dd");
          definition.textContent = declared.get(name).description;
          legend.append(term, definition);
        });
        target.replaceChildren(table, ...(stageLegend ? [stageLegend] : []), ...(legend.childElementCount ? [legend] : []));
      });
    }

    function render(selected, active, compact, busy, operation) {
      // Offered once the session is in steady state; an experiment's own
      // config reloads pass through "starting" without hiding the panel.
      const steady = Boolean(active && ["ready", "validated"].includes(active.phase) && !busy);
      const experimenting = busy && operation?.name === "experiment" && operation.pattern === selected?.slug;
      const available = Boolean(selected?.experiments?.length && !compact && (steady || experimenting));
      setVisible("toggle-experiments", available);
      $("toggle-experiments").setAttribute("aria-expanded", String(experimentsOpen));
      setVisible("experiments-panel", available && experimentsOpen);
      if (!available || !experimentsOpen) return;
      if (experimentsPattern?.slug !== selected.slug) {
        experimentsPattern = selected;
        experimentRuns = [];
        renderExperimentForms(selected);
        loadExperimentRuns(selected.slug);
      }
      // While this experiment runs, Run gives way to Stop; Reset waits.
      document.querySelectorAll("#experiments-body .experiment-form").forEach((form) => {
        form.querySelector("button[type=submit]").hidden = experimenting;
        form.querySelector("button.stop").hidden = !experimenting;
        form.querySelector("button.secondary").disabled = busy;
        form.querySelector("button[type=submit]").disabled = busy;
      });
      const finished = operation?.name === "experiment" && operation.status !== "running" ? operation.finished_at : null;
      if (finished && finished !== experimentsSeen) {
        experimentsSeen = finished;
        loadExperimentRuns(selected.slug);
      }
    }

    $("toggle-experiments").addEventListener("click", () => {
      setExperimentsOpen(!experimentsOpen);
      deps.rerender();
    });
    $("close-experiments").addEventListener("click", () => {
      setExperimentsOpen(false);
      deps.rerender();
    });

    return { render };
  }

  return { create };
})();
