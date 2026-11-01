// Experiments panel: on-demand workloads declared under spec.experiments in a
// pattern's manifest. One form per experiment, a table of its saved runs with a
// per-run timeline, and Run/Reset actions. session.js creates it once and calls
// render() from its own render pass, passing the session state.
window.PE = window.PE || {};
window.PE.experiments = (() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const apiUrl = (path) => new URL(path.replace(/^\//, ""), document.baseURI).toString();
  const icon = (paths) => `<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;
  const ICON_DUPLICATE = icon('<path d="M8 3v10M3 8h10"/>');
  const ICON_REMOVE = icon('<path d="M4 4l8 8M12 4l-8 8"/>');
  const ICON_COPY = icon('<rect x="5.5" y="5.5" width="8" height="8" rx="1.5"/><path d="M10.5 3.5v-.5a1.5 1.5 0 0 0-1.5-1.5H4A1.5 1.5 0 0 0 2.5 3v5A1.5 1.5 0 0 0 4 9.5h.5"/>');

  function create(deps) {
    // deps: command(path, payload), confirmAction(message, label),
    //       showToast(message, kind), openLogs(), rerender()
    // The open panel and typed values survive a page reload (an edit to the
    // pattern's source reloads the page through the live-revision check).
    let experimentsOpen = false;
    try { experimentsOpen = sessionStorage.getItem("experiments-open") === "1"; } catch (_error) { /* storage blocked */ }
    function setExperimentsOpen(open) {
      experimentsOpen = open;
      try { sessionStorage.setItem("experiments-open", open ? "1" : "0"); } catch (_error) { /* storage blocked */ }
    }
    let experimentsPattern = null;  // pattern whose experiment forms are rendered
    let experimentsSeen = null;     // last finished operation or finished run whose runs were fetched
    let experimentRuns = [];
    let appliedValues = null;       // experiment config values the running session uses; null until fetched
    const sortState = {};           // experiment name -> { column, direction }

    function setVisible(id, visible) {
      $(id).hidden = !visible;
    }

    // Forms are built once per pattern so a refresh keeps typed values.
    async function loadExperimentRuns(slug) {
      try {
        const response = await fetch(apiUrl(`api/experiments?pattern=${encodeURIComponent(slug)}`), { cache: "no-store" });
        if (!response.ok) return;
        const data = await response.json();
        // A slow response for a pattern the reader has left must not replace the current runs.
        if (experimentsPattern?.slug !== slug) return;
        experimentRuns = data.runs || [];
        const applied = data.applied || {};
        if (JSON.stringify(applied) !== JSON.stringify(appliedValues)) {
          appliedValues = applied;
          showSessionConfig();
        }
      } catch (_error) {
        return;
      }
      renderExperimentResults();
    }

    // A config field shows the value the session runs with: the experiment
    // value when one is applied, otherwise the pattern's committed default. A
    // new session starts from the committed files, so its fields go back to
    // the defaults. Script arguments keep what was typed, and so does a list
    // of several rows.
    function showSessionConfig() {
      document.querySelectorAll("#experiments-body .experiment").forEach((section) => {
        const experiment = experimentsPattern?.experiments.find((item) => item.name === section.dataset.experiment);
        const form = section.querySelector(".experiment-form");
        const rows = form?.querySelectorAll(".experiment-row") || [];
        if (!experiment || rows.length !== 1) return;
        experiment.parameters.filter((parameter) => parameter.config).forEach((parameter) => {
          const input = rows[0].querySelector(`[name="${parameter.name}"]`);
          if (input) input.value = String(appliedValues[parameter.name] ?? parameter.default);
        });
        form.dispatchEvent(new Event("input"));  // saves the shown values
      });
    }

    function rowValue(row) {
      return Object.fromEntries([...row.querySelectorAll("input, select")].map((input) => [input.name, input.value]));
    }

    function rowValues(form) {
      return [...form.querySelectorAll(".experiment-row")].map(rowValue);
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
        // One row per run; Run submits them in order. Typed rows survive a page reload.
        const rows = document.createElement("div");
        rows.className = "experiment-rows";
        const storageKey = `experiment-values:${pattern.slug}:${experiment.name}`;
        let saved = [];
        try { saved = JSON.parse(sessionStorage.getItem(storageKey) || "[]"); } catch (_error) { saved = []; }
        if (!Array.isArray(saved)) saved = [saved];  // one object before rows existed
        const saveRows = () => {
          try { sessionStorage.setItem(storageKey, JSON.stringify(rowValues(form))); }
          catch (_error) { /* storage blocked */ }
        };
        form.addEventListener("input", saveRows);
        const updateRows = () => {
          const count = rows.children.length;
          rows.querySelectorAll("button.remove-row").forEach((button) => { button.hidden = count === 1; });
          run.title = count === 1 ? "" : `Run all ${count} in order`;
          saveRows();
        };
        const addRow = (values, after = null) => {
          const row = document.createElement("div");
          row.className = "experiment-row";
          experiment.parameters.forEach((parameter) => {
            const label = document.createElement("label");
            const name = document.createElement("span");
            name.textContent = parameter.label || parameter.name;
            const value = values[parameter.name] ?? parameter.default;
            let input;
            if (parameter.choices?.length) {
              input = document.createElement("select");
              parameter.choices.forEach((choice) => input.add(new Option(String(choice), String(choice))));
              input.value = String(value);
            } else {
              input = document.createElement("input");
              Object.assign(input, { type: "number", step: Number.isInteger(parameter.default) ? "1" : "any", value, required: true });
              if (parameter.min != null) input.min = String(parameter.min);
            }
            input.name = parameter.name;
            label.append(name, input);
            if (parameter.config) {
              label.title = `Set in ${parameter.config.file}. A new value restarts the session before the run.`;
            }
            row.append(label);
          });
          const duplicate = document.createElement("button");
          duplicate.type = "button";
          duplicate.className = "row-action duplicate-row";
          duplicate.innerHTML = ICON_DUPLICATE;
          duplicate.title = "Add run";
          duplicate.setAttribute("aria-label", "Add run");
          duplicate.addEventListener("click", () => addRow(rowValue(row), row));
          const remove = document.createElement("button");
          remove.type = "button";
          remove.className = "row-action remove-row";
          remove.innerHTML = ICON_REMOVE;
          remove.title = "Remove run";
          remove.setAttribute("aria-label", "Remove run");
          remove.addEventListener("click", () => { row.remove(); updateRows(); });
          const status = document.createElement("span");
          status.className = "row-status";
          row.append(duplicate, remove, status);
          if (after) after.after(row);
          else rows.append(row);
          updateRows();
        };
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
        stop.title = "End the running workload; the session keeps its experiment config";
        stop.hidden = true;
        stop.addEventListener("click", async () => {
          try { await deps.command(apiUrl("api/session/experiment/stop")); }
          catch (error) { deps.showToast(error.message, "error"); }
        });
        const actions = document.createElement("div");
        actions.className = "experiment-actions";
        actions.append(run, stop, reset);
        (saved.length ? saved : [{}]).forEach((values) => addRow(values));
        form.append(rows, actions);
        form.addEventListener("submit", async (event) => {
          event.preventDefault();
          deps.openLogs();
          try { await deps.command(apiUrl("api/session/experiment"), { experiment: experiment.name, runs: rowValues(form) }); }
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
    // average latency).
    // Segments in the order the script reports them; each takes the next
    // palette slot, so neighbours are always a validated pair. `extra`
    // segments are drawn but not summed.
    function runTimeline(run) {
      return (run.results.stages || []).map((stage, index) => ({
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
    let timelineTip = null;
    function showTimelineTip(bar, segments, totalLabel) {
      if (!timelineTip) {
        timelineTip = document.createElement("div");
        timelineTip.className = "timeline-tip";
        timelineTip.setAttribute("role", "tooltip");
        document.body.append(timelineTip);
      }
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

    // Config parameters are applied through copies of the pattern's files, and
    // the session keeps them after a run. Say so, and offer the way back.
    function renderAppliedValues() {
      const note = $("experiments-applied");
      const entries = Object.entries(appliedValues || {});
      note.hidden = !entries.length;
      if (!entries.length) return;
      const parameters = (experimentsPattern?.experiments || []).flatMap((experiment) => experiment.parameters);
      const describe = ([name, value]) => {
        const parameter = parameters.find((item) => item.name === name);
        return `${parameter?.label || name} = ${value}`;
      };
      note.querySelector("span").textContent = `Session runs with experiment values: ${entries.map(describe).join(", ")}.`;
    }

    function renderExperimentResults() {
      hideTimelineTip();  // a rebuilt table removes the hovered bar without a mouseleave
      renderAppliedValues();
      document.querySelectorAll("#experiments-body .experiment").forEach((section) => {
        const experiment = experimentsPattern?.experiments.find((item) => item.name === section.dataset.experiment);
        const target = section.querySelector(".experiment-results");
        const runs = experimentRuns.filter((run) => run.experiment === section.dataset.experiment).reverse();
        if (!experiment || !runs.length) {
          target.textContent = "No saved runs.";
          return;
        }
        // Columns, grouped under a header row by pipeline stage (source, tool,
        // ClickHouse, end to end), in the order the manifest's `groups` gives.
        const declared = new Map((experiment.results || []).map((result) => [result.name, result]));
        // Declared results only: runs saved before a manifest change can hold
        // keys the experiment no longer reports.
        const resultNames = [...declared.keys()].filter((name) => name !== "stages");
        const columns = [
          { key: "time", label: "time", group: "Run", value: (run) => new Date(run.started_at).getTime(),
            text: (run) => new Date(run.started_at).toLocaleTimeString() },
          ...experiment.parameters.map((parameter) => ({
            key: parameter.name, label: parameter.short || parameter.name, title: parameter.label,
            group: parameter.group || (parameter.config ? "Settings" : "Workload"),
            value: (run) => run.parameters[parameter.name],
          })),
          ...resultNames.map((name) => ({
            key: name, label: declared.get(name)?.label || name, title: declared.get(name)?.description,
            group: declared.get(name)?.group || "Results", value: (run) => run.results[name],
          })),
          // Only when some run reports stages.
          ...(runs.some((run) => run.results.stages?.length) ? [{
            key: "timeline", label: "where time goes", group: "Timeline",
            value: (run) => runTimeline(run).reduce((sum, segment) => sum + segment.ms, 0),
          }] : []),
        ];
        const declaredOrder = experiment.groups || [];
        const groupOrder = [...new Set(["Run", ...declaredOrder, ...columns.map((column) => column.group)])]
          .filter((group) => group !== "Timeline" && columns.some((column) => column.group === group))
          .concat(columns.some((column) => column.group === "Timeline") ? ["Timeline"] : []);
        columns.sort((a, b) => groupOrder.indexOf(a.group) - groupOrder.indexOf(b.group));  // stable: keeps order within a group

        // Sort rows by the chosen column; the default is newest first.
        const sort = sortState[experiment.name] || { column: "time", direction: -1 };
        const sortColumn = columns.find((column) => column.key === sort.column) || columns[0];
        // Numbers sort numerically, text (a verdict, a mode) alphabetically; empty cells last.
        const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });
        const sortValue = (run) => {
          const value = sortColumn.value(run);
          return value == null || value === "" ? null : value;
        };
        runs.sort((a, b) => {
          const x = sortValue(a), y = sortValue(b);
          if (x === null || y === null) return x === y ? 0 : x === null ? 1 : -1;
          const numeric = typeof x === "number" && typeof y === "number";
          return sort.direction * (numeric ? x - y : collator.compare(String(x), String(y)));
        });
        const timelines = runs.map(runTimeline);
        const longest = Math.max(1, ...timelines.map((segments) => segments.reduce((sum, segment) => sum + segment.ms, 0)));

        const table = document.createElement("table");
        table.className = "experiment-table";
        const thead = table.createTHead();
        const groupRow = thead.insertRow();
        groupRow.className = "group-row";
        groupOrder.forEach((group, index) => {
          const cell = document.createElement("th");
          cell.colSpan = columns.filter((column) => column.group === group).length;
          cell.textContent = group === "Run" ? "" : group;
          if (index > 0) cell.className = "group-start";
          groupRow.append(cell);
        });
        const head = thead.insertRow();
        columns.forEach((column, index) => {
          const cell = document.createElement("th");
          cell.textContent = column.label;
          cell.className = "sortable";
          if (index > 0 && columns[index - 1].group !== column.group) cell.classList.add("group-start");
          if (column.title) cell.title = column.title;
          if (sort.column === column.key) cell.setAttribute("aria-sort", sort.direction === 1 ? "ascending" : "descending");
          cell.addEventListener("click", () => {
            // A new column starts descending (largest first); clicking again reverses.
            sortState[experiment.name] = { column: column.key, direction: sort.column === column.key ? -sort.direction : -1 };
            renderExperimentResults();
          });
          head.append(cell);
        });
        const body = table.createTBody();
        runs.forEach((run, runIndex) => {
          const row = body.insertRow();
          columns.forEach((column, index) => {
            const cell = row.insertCell();
            if (index > 0 && columns[index - 1].group !== column.group) cell.className = "group-start";
            if (column.key === "timeline") cell.append(timelineBar(timelines[runIndex], longest, experiment.timeline_total || "Total"));
            else cell.textContent = column.text ? column.text(run) : (column.value(run) ?? "");
          });
        });
        const caption = table.createCaption();
        const sortLabel = sort.column === "time" && sort.direction === -1 ? "newest first"
          : `sorted by ${sortColumn.group === "Run" ? "" : `${sortColumn.group} `}${sortColumn.label}, ${sort.direction === 1 ? "ascending" : "descending"}`;
        caption.textContent = `${runs.length} saved run${runs.length === 1 ? "" : "s"}, ${sortLabel}`;
        const copy = document.createElement("button");
        copy.type = "button";
        copy.className = "copy-table";
        copy.innerHTML = ICON_COPY;
        copy.title = "Copy table";
        copy.setAttribute("aria-label", "Copy table");
        copy.addEventListener("click", () => copyTable(experiment, columns, runs));
        caption.append(copy);
        const stageLegend = timelineLegend(timelines.find((segments) => segments.length) || []);
        const legend = document.createElement("dl");
        legend.className = "experiment-legend";
        resultNames.filter((name) => declared.get(name)?.description).forEach((name) => {
          const term = document.createElement("dt");
          const group = declared.get(name).group;
          term.textContent = group ? `${group}: ${declared.get(name).label}` : declared.get(name).label;
          const definition = document.createElement("dd");
          definition.textContent = declared.get(name).description;
          legend.append(term, definition);
        });
        target.replaceChildren(table, ...(stageLegend ? [stageLegend] : []), ...(legend.childElementCount ? [legend] : []));
      });
    }

    // Copies the runs in the table's order, as HTML (pastes as a table into
    // docs and spreadsheets) and tab-separated text. The timeline becomes one
    // column per stage, in ms.
    async function copyTable(experiment, columns, runs) {
      const stageLabels = [...new Set(runs.flatMap((run) => runTimeline(run).map((segment) => segment.label)))];
      const plain = new Set(["Run", "Settings", "Workload"]);
      const header = [
        ...columns.filter((column) => column.key !== "timeline")
          .map((column) => plain.has(column.group) ? column.title || column.label : `${column.group} ${column.label}`),
        ...stageLabels.map((label) => `${label} (ms)`),
      ];
      const rows = runs.map((run) => {
        const stages = new Map(runTimeline(run).map((segment) => [segment.label, segment.ms.toFixed(1)]));
        return [
          ...columns.filter((column) => column.key !== "timeline")
            .map((column) => String(column.text ? column.text(run) : (column.value(run) ?? ""))),
          ...stageLabels.map((label) => stages.get(label) ?? ""),
        ];
      });
      const text = [header, ...rows].map((cells) => cells.join("\t")).join("\n");
      const escape = (value) => value.replace(/&/g, "&amp;").replace(/</g, "&lt;");
      const html = `<table><thead><tr>${header.map((cell) => `<th>${escape(cell)}</th>`).join("")}</tr></thead><tbody>${
        rows.map((cells) => `<tr>${cells.map((cell) => `<td>${escape(cell)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
      try {
        if (window.ClipboardItem) {
          await navigator.clipboard.write([new ClipboardItem({
            "text/html": new Blob([html], { type: "text/html" }),
            "text/plain": new Blob([text], { type: "text/plain" }),
          })]);
        } else {
          await navigator.clipboard.writeText(text);
        }
        deps.showToast(`Copied ${runs.length} ${experiment.title} run${runs.length === 1 ? "" : "s"}`, "ok");
      } catch (error) {
        deps.showToast(`Copy failed: ${error.message}`, "error");
      }
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
        appliedValues = null;
        renderExperimentForms(selected);
        loadExperimentRuns(selected.slug);
      }
      // While this experiment runs, Run gives way to Stop; Reset waits.
      $("restore-config").disabled = busy;
      document.querySelectorAll("#experiments-body .experiment-form").forEach((form) => {
        form.querySelector("button[type=submit]").hidden = experimenting;
        form.querySelector("button.stop").hidden = !experimenting;
        form.querySelector("button.secondary").disabled = busy;
        form.querySelector("button[type=submit]").disabled = busy;
        form.querySelectorAll("button.row-action").forEach((button) => { button.disabled = busy; });
        // Each row shows its run's status while the list runs and after it ends,
        // as long as the rows still match the list that was submitted.
        const rows = form.querySelectorAll(".experiment-row");
        const statuses = operation?.name === "experiment" && operation.experiment === form.parentElement.dataset.experiment
          && operation.runs?.length === rows.length && rows.length > 1 ? operation.runs : [];
        rows.forEach((row, index) => {
          const status = statuses[index] || "";
          row.querySelector(".row-status").textContent = status;
          row.dataset.status = status;
        });
      });
      // Any finished operation can change the session's config: an experiment
      // or a reload applies values, a stop and a new start drop them. Each
      // finished run in a list adds a saved run.
      const finished = operation && operation.status !== "running" ? operation.finished_at : null;
      const runsFinished = (operation?.runs || []).filter((status) => !["queued", "running"].includes(status)).length;
      const seen = finished || (runsFinished ? `${operation.started_at}:${runsFinished}` : null);
      if (seen && seen !== experimentsSeen) {
        experimentsSeen = seen;
        loadExperimentRuns(selected.slug);
      }
    }

    $("restore-config").addEventListener("click", async () => {
      deps.openLogs();
      try { await deps.command(apiUrl("api/session/experiment/restore")); }
      catch (error) { deps.showToast(error.message, "error"); }
    });
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
