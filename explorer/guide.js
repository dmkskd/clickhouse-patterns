// Group guide: the Diagnose / Enforce questions, the query execution map and
// the matching limits for a group that has a guide.yaml. catalog-view.js calls
// render(info) while drawing a group page; the per-group answers live here.
window.PE = window.PE || {};
window.PE.guide = (() => {
  "use strict";
  const { esc, displayTitle } = window.PE.util;
  const $ = (id) => document.getElementById(id);

  function create(deps) {
    // deps: patterns, openPattern(slug)
    const { patterns } = deps;
    // A group's guide.yaml: two entry points (Diagnose, Enforce) that filter one
    // list of mechanism records by facet. Each step is a row of answers; an
    // answer with no mechanism is disabled, unless a gap explains what to use
    // instead. The state is per group, so leaving and coming back keeps it.
    const BEHAVIOR_ORDER = ["wait", "reject", "throttle", "downscale", "spill", "break", "kill"];
    const guideState = new Map();

    function guideValues(mechanism, facet) {
      return facet === "errors" ? mechanism.errors || [] : (mechanism.facets || {})[facet] || [];
    }

    function guideMatches(mechanism, picks) {
      return Object.entries(picks).every(([facet, value]) => guideValues(mechanism, facet).includes(value));
    }

    function guideGap(guide, picks) {
      return (guide.gaps || []).find((gap) =>
        Object.entries(gap.when).every(([facet, value]) => picks[facet] === value));
    }

    function guideMechanismCard(mechanism, scopeLabels, stages, selection) {
      const pattern = mechanism.pattern && patterns.find((item) => item.slug === mechanism.pattern);
      const behaviors = guideTags(guideBehaviors(mechanism));
      const scopes = guideValues(mechanism, "scope").map((value) => esc(scopeLabels[value] || value)).join(", ");
      const errors = (mechanism.errors || []).map((code) => `<code>${esc(code)}</code>`).join(" ");
      const settings = (mechanism.settings || []).map((name) => `<code>${esc(name)}</code>`).join(" ");
      const selected = selection && (selection.id === mechanism.id || (mechanism.stage || []).includes(selection.stage));
      const stageTags = stages.filter((stage) => (mechanism.stage || []).includes(stage.key)).map((stage) =>
        `<span class="guide-stage-tag${selection?.stage === stage.key ? " selected" : ""}" title="Query stage: ${esc(stage.label)}">${esc(stage.label)}</span>`).join("");
      const action = pattern
        ? `<button type="button" class="guide-run" data-slug="${esc(pattern.slug)}" title="${esc(displayTitle(pattern))}">Open pattern</button>`
        : `<span class="guide-no-pattern">No pattern yet</span>`;
      return `<article class="guide-mechanism${selected ? " selected" : ""}" id="guide-m-${esc(mechanism.id)}">` +
        (stageTags ? `<div class="guide-stage-tags">${stageTags}</div>` : "") +
        `<header><h4>${esc(mechanism.title)}</h4><div class="guide-behaviors">${behaviors}</div></header>` +
        `<dl>` +
        `<dt>Scope</dt><dd>${scopes}${mechanism.since ? ` <span class="guide-since">since ${esc(mechanism.since)}</span>` : ""}</dd>` +
        (errors ? `<dt>Error</dt><dd>${errors}</dd>` : "") +
        (settings ? `<dt>Settings</dt><dd class="guide-settings">${settings}</dd>` : "") +
        `</dl>` +
        (mechanism.note ? `<p>${esc(mechanism.note)}</p>` : "") +
        `<footer>${action}${mechanism.docs ? `<a href="${esc(mechanism.docs)}" target="_blank" rel="noopener noreferrer">Docs</a>` : ""}</footer>` +
        `</article>`;
    }

    function guideBehaviors(mechanism) {
      return guideValues(mechanism, "behavior").slice()
        .sort((a, b) => BEHAVIOR_ORDER.indexOf(a) - BEHAVIOR_ORDER.indexOf(b));
    }

    // What a limit does to a query, in words, colored by outcome: the query
    // fails, is delayed, or completes with a degraded result.
    const BEHAVIOR_TAGS = {
      wait: ["waits", "delayed"], reject: ["rejects", "fails"], throttle: ["slows down", "delayed"],
      downscale: ["fewer threads", "delayed"], spill: ["spills to disk", "degraded"],
      break: ["partial result", "degraded"], kill: ["stops the query", "fails"],
    };
    const guideTags = (values) => values.map((value) => {
      const [label, tone] = BEHAVIOR_TAGS[value] || [value, ""];
      return `<span class="guide-tag t-${tone}">${esc(label)}</span>`;
    }).join("");

    // Diagnose: the stages a query passes through, left to right, with every
    // mechanism placed where it acts. Execution is the crowded stage, so its
    // nodes are grouped by resource.
    function guidePipeline(guide, lit, focus, resourceLabels) {
      const stages = guide.stages.map((stage) => {
        const items = guide.mechanisms.filter((item) => (item.stage || []).includes(stage.key));
        const node = (item) => {
          const state = focus ? (item.id === focus ? " lit" : " dim") : lit ? (lit.has(item.id) ? " lit" : " dim") : "";
          return `<button type="button" class="guide-node${state}" data-id="${esc(item.id)}">` +
            `<span class="guide-node-title">${esc(item.title)}</span>` +
            `<span class="guide-node-tags">${guideTags(guideBehaviors(item))}</span></button>`;
        };
        let nodes;
        if (stage.wide && items.length > 8) {
          const byResource = new Map();
          items.forEach((item) => {
            const key = guideValues(item, "resource")[0] || "";
            if (!byResource.has(key)) byResource.set(key, []);
            byResource.get(key).push(item);
          });
          nodes = [...byResource].map(([key, group]) =>
            `<div class="guide-node-group"><span>${esc(resourceLabels[key] || key)}</span>${group.map(node).join("")}</div>`).join("");
        } else {
          nodes = items.map(node).join("");
        }
        return `<li class="guide-stage${stage.wide ? " wide" : ""}">` +
          `<div class="guide-stage-head"><strong>${esc(stage.label)}</strong>` +
          (stage.note ? `<small>${esc(stage.note)}</small>` : "") + `</div>` +
          `<div class="guide-stage-nodes">${nodes}</div></li>`;
      }).join("");
      return `<p class="guide-caption">Limits are grouped by query stage. Select a limit to display its settings.</p>` +
        `<div class="guide-visual"><ol class="guide-pipeline">${stages}</ol></div>`;
    }

    // Enforce: the first two steps' facets as a grid. A cell shows what the
    // mechanisms there do at the limit; a dashed cell is a known gap.
    function guideMatrix(guide, entry, picks) {
      const [rowStep, colStep, ...rest] = entry.steps;
      const restPicks = Object.fromEntries(Object.entries(picks)
        .filter(([facet]) => facet !== rowStep.facet && facet !== colStep.facet));
      const head = `<tr><th></th>${Object.entries(colStep.options).map(([, label]) => `<th scope="col">${esc(label)}</th>`).join("")}</tr>`;
      const rows = Object.entries(rowStep.options).map(([row, rowLabel]) => {
        const cells = Object.keys(colStep.options).map((col) => {
          const cellPicks = { [rowStep.facet]: row, [colStep.facet]: col };
          const items = guide.mechanisms.filter((item) => guideMatches(item, cellPicks));
          const matching = items.filter((item) => guideMatches(item, restPicks));
          // A gap is drawn in a cell that has mechanisms, or that the gap names
          // by both row and column; otherwise a gap on one facet would fill a row.
          const found = !matching.length && guideGap(guide, { ...cellPicks, ...restPicks });
          const gap = found && (items.length || (rowStep.facet in found.when && colStep.facet in found.when)) ? found : null;
          const active = picks[rowStep.facet] === row && picks[colStep.facet] === col;
          if (!items.length && !gap) return `<td class="guide-cell-empty"></td>`;
          const behaviors = [...new Set((matching.length ? matching : items).flatMap(guideBehaviors))]
            .sort((a, b) => BEHAVIOR_ORDER.indexOf(a) - BEHAVIOR_ORDER.indexOf(b));
          const label = gap ? `<span class="guide-cell-gap">not possible</span>` : guideTags(behaviors);
          return `<td><button type="button" class="guide-cell${active ? " active" : ""}${matching.length ? "" : " dim"}" ` +
            `data-row="${esc(row)}" data-col="${esc(col)}" aria-pressed="${active}" ` +
            `title="${esc(`${rowLabel} · ${colStep.options[col]}: ${matching.length} mechanism${matching.length === 1 ? "" : "s"}`)}">` +
            `<span class="guide-cell-tags">${label}</span>` +
            `${matching.length ? `<small>${matching.length} ${matching.length === 1 ? "limit" : "limits"}</small>` : ""}</button></td>`;
        }).join("");
        return `<tr><th scope="row">${esc(rowLabel)}</th>${cells}</tr>`;
      }).join("");
      return `<p class="guide-caption">Rows: what to limit. Columns: where the limit is set. Each cell lists what the ` +
        `limits there can do; click a cell to answer the first two questions.</p>` +
        `<div class="guide-visual"><table class="guide-matrix"><thead>${head}</thead><tbody>${rows}</tbody></table></div>`;
    }

    // Cluster diagram: the same limits placed on the nodes a query passes
    // through. Node A receives the query and stores shard 1; Node B runs the
    // secondary query for shard 2. Each row is a stage with its limit count.
    const GUIDE_TOPOLOGIES = {
      cluster: [
        { key: "a", label: "Node A", sub: "Receives the query (initiator), stores shard 1",
          places: ["initiator", "every-node", "table-node"] },
        { key: "b", label: "Node B", sub: "Stores shard 2, runs the secondary query",
          places: ["every-node", "table-node"] },
      ],
      single: [
        { key: "s", label: "ClickHouse server", sub: "Receives, plans, and runs the query",
          places: ["initiator", "every-node", "table-node"] },
      ],
    };

    function guideTopoItems(guide, node, stageKey) {
      return guide.mechanisms.filter((item) => (item.stage || []).includes(stageKey) &&
        (item.where || ["every-node"]).some((place) => node.places.includes(place)));
    }

    function guideTopology(guide, topology, lit, spot) {
      const nodes = GUIDE_TOPOLOGIES[topology] || GUIDE_TOPOLOGIES.cluster;
      const clustered = nodes.length > 1;
      const box = (node) => {
        const rows = guide.stages.map((stage) => {
          const items = guideTopoItems(guide, node, stage.key);
          if (!items.length) return "";
          const hits = lit ? items.filter((item) => lit.has(item.id)).length : 0;
          const only = clustered ? items.filter((item) => (item.where || []).length === 1 && item.where[0] === "initiator").length : 0;
          const active = spot && spot.node === node.key && spot.stage === stage.key;
          const state = active ? " active" : lit ? (hits ? " lit" : " dim") : "";
          const count = lit && hits ? `${hits} of ${items.length}` : `${items.length}`;
          return `<li><button type="button" class="guide-topo-row${state}" data-node="${esc(node.key)}" data-stage="${esc(stage.key)}" ` +
            `aria-pressed="${Boolean(active)}" aria-controls="guide-results">` +
            `<span class="guide-topo-stage">${esc(stage.label)}</span>` +
            (only ? `<span class="guide-topo-only">${only} initiator-only ${only === 1 ? "limit" : "limits"}</span>` : "") +
            `<span class="guide-topo-count">${count}</span></button></li>`;
        }).join("");
        return `<div class="guide-topo-node"><header><strong>${esc(node.label)}</strong><small>${esc(node.sub)}</small></header>` +
          `<ol class="guide-topo-stages">${rows}</ol></div>`;
      };
      const arrow = (forward, back) => `<div class="guide-topo-arrow"><span class="fwd">${esc(forward)}</span>` +
        (back ? `<span class="back">${esc(back)}</span>` : "") + `</div>`;
      const client = `<div class="guide-topo-client"><strong>Client</strong><small>clickhouse-client, driver, HTTP</small></div>`;
      const keeper = clustered ? `<div class="guide-topo-keeper"><strong>Keeper</strong>` +
        `<small>Can store workload and resource definitions (workload_zookeeper_path). Every node still enforces its own copy.</small></div>` : "";
      const lane = clustered
        ? client + arrow("query", "result") + box(nodes[0]) + arrow("secondary query", "partial result") + box(nodes[1]) + keeper
        : client + arrow("query", "result") + box(nodes[0]);
      const notes = clustered ? `<dl class="guide-topo-notes">` + (guide.placements || []).map((place) =>
        `<dt>${esc(place.label)}</dt><dd>${esc(place.note)}</dd>`).join("") + `</dl>` : "";
      const toggle = ["single", "cluster"].map((key) =>
        `<button type="button" class="guide-subtab${key === topology ? " active" : ""}" data-topology="${key}">` +
        `${key === "single" ? "Single node" : "Cluster, 2 shards"}</button>`).join("");
      return `<div class="guide-subtabs">${toggle}</div>` +
        `<p class="guide-caption">Select a stage on ${nodes.map((node) => esc(node.label)).join(" or ")} to display the applicable limits.</p>` +
        `<div class="guide-visual"><div class="guide-topo${clustered ? " clustered" : ""}">${lane}</div></div>` + notes;
    }

    // One question at a time: answered questions collapse into a trail, the
    // current question offers only answers that still match, and the matching
    // limits appear once there are few enough to read. The map is opt-in.
    const GUIDE_RESULTS_AT = 6;

    function render(info) {
      const slot = $("catalog-group-guide");
      if (!slot) return;
      const guide = info?.guide;
      if (!guide) { slot.hidden = true; slot.replaceChildren(); return; }
      slot.hidden = false;
      const fresh = (entry) => ({ entry, picks: {}, skipped: [], focus: "", spot: null, showAll: false, map: false, mapView: "cluster", topology: "cluster" });
      if (!guideState.has(info.key)) guideState.set(info.key, fresh(guide.entries[0].key));
      const state = guideState.get(info.key);
      const entry = guide.entries.find((item) => item.key === state.entry) || guide.entries[0];
      const scopeLabels = entry.steps.find((step) => step.facet === "scope")?.options || {};
      const byId = Object.fromEntries(guide.mechanisms.map((item) => [item.id, item]));

      const optionsFor = (step) => {
        const others = Object.fromEntries(Object.entries(state.picks).filter(([facet]) => facet !== step.facet));
        const values = step.options && Object.keys(step.options).length
          ? Object.keys(step.options)
          : [...new Set(guide.mechanisms.flatMap((item) => guideValues(item, step.facet)))].sort();
        return values.map((value) => {
          const trial = { ...others, [step.facet]: value };
          const count = guide.mechanisms.filter((item) => guideMatches(item, trial)).length;
          return { value, label: step.options?.[value] || value, count, gap: !count && guideGap(guide, trial) };
        }).filter((option) => option.count || option.gap);
      };

      const matches = guide.mechanisms.filter((item) => guideMatches(item, state.picks));
      const gap = !matches.length && guideGap(guide, state.picks);
      // The current question is the first one neither answered nor skipped that
      // still has a choice to make; a gap ends the questions.
      const current = gap ? null : entry.steps.find((step) =>
        !(step.facet in state.picks) && !state.skipped.includes(step.facet) && optionsFor(step).length > 1);

      const trail = entry.steps.map((step, index) => {
        if (step.facet in state.picks) {
          const label = step.options?.[state.picks[step.facet]] || state.picks[step.facet];
          return `<button type="button" class="guide-crumb" data-back="${index}" title="Change this answer">${esc(label)}</button>`;
        }
        if (state.skipped.includes(step.facet)) {
          return `<button type="button" class="guide-crumb skipped" data-back="${index}" title="Answer this question">${esc(step.question)} skipped</button>`;
        }
        return "";
      }).filter(Boolean);

      let question = "";
      if (current) {
        const index = entry.steps.indexOf(current);
        const chips = optionsFor(current).map((option) =>
          `<button type="button" class="guide-chip${option.gap ? " gap" : ""}" data-facet="${esc(current.facet)}" data-value="${esc(option.value)}">` +
          `${esc(option.label)}<small>${option.gap ? "not possible" : option.count}</small></button>`).join("");
        question = `<div class="guide-question-block">` +
          `<p class="guide-question"><span class="guide-step-index">${index + 1}</span>${esc(current.question)}</p>` +
          `<div class="guide-chips">${chips}</div>` +
          `<button type="button" class="guide-skip" data-facet="${esc(current.facet)}">Skip this question</button></div>`;
      }

      const focus = state.focus && byId[state.focus] ? state.focus : "";
      // A row of the cluster diagram lists every limit at that stage on that node.
      const spotNode = state.spot && (GUIDE_TOPOLOGIES[state.topology] || []).find((node) => node.key === state.spot.node);
      const spotStage = spotNode && guide.stages.find((stage) => stage.key === state.spot.stage);
      const spot = spotStage ? { node: spotNode, stage: spotStage, items: guideTopoItems(guide, spotNode, spotStage.key) } : null;
      const ready = spot || focus || gap || !current || matches.length <= GUIDE_RESULTS_AT || state.showAll;
      const shown = spot ? spot.items : focus ? [byId[focus]] : gap ? (gap.see || []).map((id) => byId[id]).filter(Boolean) : matches;
      let summary;
      if (spot) summary = `<header class="guide-selection"><h4 id="guide-selection-title" tabindex="-1">${esc(spot.node.label)} · ${esc(spot.stage.label)}</h4>` +
        `<span class="guide-count">${spot.items.length} ${spot.items.length === 1 ? "limit" : "limits"}</span>` +
        `<button type="button" class="guide-unfocus">Clear selection</button></header>`;
      else if (focus) summary = `<header class="guide-selection"><h4 id="guide-selection-title" tabindex="-1">${esc(byId[focus].title)}</h4>` +
        `<button type="button" class="guide-unfocus">Clear selection</button></header>`;
      else if (gap) summary = `<p class="guide-gap-note"><strong>Not possible.</strong> ${esc(gap.note)}</p><p class="guide-count">Closest options:</p>`;
      else if (ready) summary = `<p class="guide-count">${matches.length} ${matches.length === 1 ? "limit matches" : "limits match"}</p>`;
      else summary = `<p class="guide-count">${matches.length} limits match. Select more criteria in ${esc(entry.label)}, ` +
        `or <button type="button" class="guide-show-all">show all ${matches.length}</button>.</p>`;

      const picked = Object.keys(state.picks).length || state.skipped.length;
      const lit = !spot && (picked || focus) ? new Set(shown.map((item) => item.id)) : null;
      const resourceLabels = guide.entries.flatMap((item) => item.steps)
        .find((step) => step.facet === "resource")?.options || {};
      const views = [["cluster", "Cluster diagram"], [entry.view, entry.view === "matrix" ? "Matrix" : "Stages"]];
      const mapView = state.mapView === "cluster" ? "cluster" : entry.view;
      const viewTabs = `<div class="guide-subtabs">` + views.map(([key, label]) =>
        `<button type="button" class="guide-subtab${key === mapView ? " active" : ""}" data-view="${esc(key)}">${label}</button>`).join("") + `</div>`;
      const visual = !state.map ? "" : viewTabs + (mapView === "cluster" ? guideTopology(guide, state.topology, lit, state.spot)
        : entry.view === "pipeline" ? guidePipeline(guide, lit, focus, resourceLabels)
        : entry.view === "matrix" ? guideMatrix(guide, entry, state.picks) : "");

      const tabs = guide.entries.map((item) =>
        `<button type="button" role="tab" class="guide-tab${item.key === entry.key ? " active" : ""}" ` +
        `aria-selected="${item.key === entry.key}" data-entry="${esc(item.key)}">${esc(item.label)}</button>`).join("");

      slot.innerHTML =
        `<section class="guide-section guide-questions" aria-labelledby="guide-questions-title">` +
        `<h3 id="guide-questions-title" class="guide-section-title">1. Diagnose / Enforce</h3>` +
        `<div class="guide-tabs" role="tablist">${tabs}</div>` +
        `<p class="guide-prompt">${esc(entry.prompt)}</p>` +
        (trail.length ? `<div class="guide-trail">${trail.join('<span class="guide-trail-sep">›</span>')}` +
          `<button type="button" class="guide-reset">Start over</button></div>` : "") +
        question + `</section>` +
        (entry.view ? `<section class="guide-section guide-map" aria-labelledby="guide-map-title">` +
          `<h3 id="guide-map-title" class="guide-section-title">2. Query execution map</h3>` +
          `<button type="button" class="guide-map-toggle" aria-expanded="${state.map}">` +
          `${state.map ? "Hide map" : "Show map of all limits"}</button>${visual}</section>` : "") +
        `<section id="guide-results" class="guide-section guide-results${spot || focus ? " selected" : ""}" aria-labelledby="guide-results-title">` +
        `<h3 id="guide-results-title" class="guide-section-title">3. Limits</h3>${summary}` +
        (ready ? `<div class="guide-mechanisms">${shown.map((item) => guideMechanismCard(item, scopeLabels, guide.stages, spot || focus ? { stage: spot?.stage.key, id: focus } : null)).join("")}</div>` : "") +
        `</section>`;

      const rerender = () => render(info);
      const revealSelection = () => {
        slot.querySelector("#guide-selection-title")?.focus({ preventScroll: true });
        const results = slot.querySelector(".guide-results");
        if (!results) return;
        const stickyHeight = [document.querySelector(".app-header"), document.querySelector(".session-bar")]
          .reduce((height, bar) => height + (bar?.getBoundingClientRect().height || 0), 24);
        results.style.scrollMarginTop = `${stickyHeight}px`;
        results.scrollIntoView({
          behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
          block: "start",
        });
      };
      slot.querySelectorAll(".guide-tab").forEach((btn) => btn.addEventListener("click", () => {
        guideState.set(info.key, fresh(btn.dataset.entry));
        rerender();
      }));
      slot.querySelectorAll(".guide-chip").forEach((btn) => btn.addEventListener("click", () => {
        state.picks[btn.dataset.facet] = btn.dataset.value;
        state.focus = ""; state.spot = null; state.showAll = false;
        rerender();
      }));
      slot.querySelector(".guide-skip")?.addEventListener("click", (event) => {
        state.skipped.push(event.currentTarget.dataset.facet);
        rerender();
      });
      // Going back to a question drops its answer and every later one.
      slot.querySelectorAll(".guide-crumb").forEach((btn) => btn.addEventListener("click", () => {
        entry.steps.slice(Number(btn.dataset.back)).forEach((step) => {
          delete state.picks[step.facet];
          state.skipped = state.skipped.filter((facet) => facet !== step.facet);
        });
        state.focus = ""; state.spot = null; state.showAll = false;
        rerender();
      }));
      slot.querySelector(".guide-reset")?.addEventListener("click", () => {
        guideState.set(info.key, { ...fresh(entry.key), map: state.map, mapView: state.mapView, topology: state.topology });
        rerender();
      });
      slot.querySelector(".guide-show-all")?.addEventListener("click", () => { state.showAll = true; rerender(); });
      slot.querySelector(".guide-unfocus")?.addEventListener("click", () => { state.focus = ""; state.spot = null; rerender(); });
      slot.querySelectorAll(".guide-subtab[data-view]").forEach((btn) => btn.addEventListener("click", () => {
        state.mapView = btn.dataset.view; state.spot = null; rerender();
      }));
      slot.querySelectorAll(".guide-subtab[data-topology]").forEach((btn) => btn.addEventListener("click", () => {
        state.topology = btn.dataset.topology; state.spot = null; rerender();
      }));
      slot.querySelectorAll(".guide-topo-row").forEach((btn) => btn.addEventListener("click", () => {
        const same = state.spot && state.spot.node === btn.dataset.node && state.spot.stage === btn.dataset.stage;
        state.spot = same ? null : { node: btn.dataset.node, stage: btn.dataset.stage };
        state.focus = "";
        rerender();
        if (state.spot) revealSelection();
      }));
      slot.querySelector(".guide-map-toggle")?.addEventListener("click", () => { state.map = !state.map; rerender(); });
      // A node picks one limit; a matrix cell answers the first two questions.
      slot.querySelectorAll(".guide-node").forEach((btn) => btn.addEventListener("click", () => {
        state.focus = state.focus === btn.dataset.id ? "" : btn.dataset.id; state.spot = null;
        rerender();
        if (state.focus) revealSelection();
      }));
      slot.querySelectorAll(".guide-cell").forEach((btn) => btn.addEventListener("click", () => {
        const [rowStep, colStep] = entry.steps;
        state.picks[rowStep.facet] = btn.dataset.row;
        state.picks[colStep.facet] = btn.dataset.col;
        state.focus = ""; state.showAll = false;
        rerender();
      }));
      slot.querySelectorAll(".guide-run").forEach((btn) => btn.addEventListener("click", () => deps.openPattern(btn.dataset.slug)));
    }

    return { render };
  }

  return { create };
})();
