// Static-first browser client; a local server progressively enables lifecycle controls.
(() => {
  "use strict";

  const catalog = window.CLICKHOUSE_PATTERN_CATALOG || { patterns: [], groups: [] };
  // Group definitions come from the catalog: one patterns/<group>/group.yaml per
  // family, plus a synthesized workspaces group. The backend sorts them by
  // `order`; nothing about groups is hardcoded here. A pattern's group is its
  // folder (`pattern.group`).
  const GROUPS = (catalog.groups || []).map((group) => ({ ...group, label: group.label || group.title }));
  const PATTERN_GROUPS = Object.fromEntries(GROUPS.map((group) => [group.key, group]));
  const GROUP_ORDER = Object.fromEntries(GROUPS.map((group, index) => [group.key, group.order ?? index]));
  function fallbackGroup(pattern) {
    const key = pattern.group || "patterns";
    return { key, label: key, title: key, description: "Related patterns", icon: "database", intro: "", related: [] };
  }
  const sortKey = (p) =>
    `${String(GROUP_ORDER[p.group] ?? 999).padStart(5, "0")}/${String(p.order ?? 1000).padStart(5, "0")}/${p.title}`;
  const patterns = [...catalog.patterns].sort((a, b) => sortKey(a).localeCompare(sortKey(b)));
  const $ = (id) => document.getElementById(id);
  const search = $("pattern-search");
  const canvas = $("architecture-canvas");
  const diagramModal = $("diagram-modal");
  const modalCanvas = $("diagram-modal-canvas");
  const resourceInspector = $("resource-inspector");
  const resourceInspectorBody = $("resource-inspector-body");
  let selected = null;
  // Catalog state lives in the URL: ?group=&topology=&q=&pattern=. Every filter
  // is therefore shareable, and the browser's back button walks the catalog the
  // same way it walks patterns.
  function readRoute() {
    const params = new URL(window.location.href).searchParams;
    const group = params.get("group") || "all";
    const topology = params.get("topology") || "all";
    return {
      pattern: params.get("pattern") || "",
      group: group === "all" || PATTERN_GROUPS[group] ? group : "all",
      topology: topology === "all" || TOPOLOGIES[topology] ? topology : "all",
      search: params.get("q") || "",
    };
  }
  let catalogFilters = (({ group, topology, search }) => ({ group, topology, search }))(readRoute());
  let diagramZoom = 1;
  let modalZoom = 1;
  // "logical" (isometric resource flow) | "schematic" (shape per resource kind) |
  // "physical" (containers). Logical and schematic ("Resource diagram" in the
  // UI) are two drawings of the same
  // graph and are always available; physical needs a running session.
  const DIAGRAM_VIEW_KEY = "pe.architectureView";
  const GRAPH_VIEWS = ["logical", "schematic"];
  let graphView = "logical";
  try {
    const stored = localStorage.getItem(DIAGRAM_VIEW_KEY);
    if (GRAPH_VIEWS.includes(stored)) graphView = stored;
  } catch (_error) { /* private mode: default applies */ }
  let architectureView = graphView;
  let topologyRequest = 0;            // guards against out-of-order topology responses
  let control = { mode: "static", interactive: false, token: null, snapshot: null };

  // Shared constant tables and esc() live in util.js (window.PE.util); the pure
  // SVG renderer lives in diagram.js (window.PE.diagram). This file keeps state,
  // DOM wiring, and orchestration.
  const {
    esc, FLOW_COLORS, KIND_LABELS, TOPOLOGIES, DIRECTIONS,
    displayTitle, directionOf, formatDescInline, plainDesc,
    valueText, dataTable, patternGroupIcon
  } = window.PE.util;
  const MIN_ZOOM = 0.5;
  const MAX_ZOOM = 2.5;
  const ZOOM_STEP = 0.1;
  const apiUrl = (path) => new URL(path.replace(/^\//, ""), document.baseURI).toString();

  function canInspectSelectedPattern() {
    const active = control.snapshot?.session;
    return Boolean(
      control.interactive && control.token && selected && active
      && active.slug === selected.slug && active.reachable && active.phase !== "failed"
    );
  }

  function directionBadge(pattern) {
    const dir = directionOf(pattern);
    if (!dir) return null;
    const badge = document.createElement("span");
    badge.className = `direction-badge ${dir}`;
    badge.textContent = DIRECTIONS[dir].label;
    badge.title = DIRECTIONS[dir].help;
    return badge;
  }

  function patternGroup(pattern) {
    return [pattern.group, PATTERN_GROUPS[pattern.group] || fallbackGroup(pattern)];
  }

  function patternGroupKey(pattern) {
    return pattern.group || fallbackGroup(pattern).key;
  }

  function patternStatusBadge(status) {
    const labels = { wip: "WIP", "under-review": "Under review", stable: "Stable" };
    const help = {
      wip: "Actively being written or changed; not yet ready for others to rely on.",
      "under-review": "Available for comparison, but its design or guidance is still being reviewed.",
      stable: "Reviewed, maintained, and suitable as a recommended starting point.",
    };
    if (!labels[status]) return null;
    const badge = document.createElement("span");
    badge.className = `pattern-status ${status}`;
    badge.title = help[status];
    badge.textContent = labels[status];
    return badge;
  }

  function groupStatusRollup(items) {
    const labels = { wip: "WIP", "under-review": "under review", stable: "stable" };
    const counts = items.reduce((all, pattern) => {
      all[pattern.status] = (all[pattern.status] || 0) + 1;
      return all;
    }, {});
    const statuses = Object.keys(counts);
    const label = statuses.length === 1 ? labels[statuses[0]] : "mixed";
    const help = ["stable", "wip", "under-review"]
      .filter((status) => counts[status])
      .map((status) => `${counts[status]} ${labels[status]}`)
      .join(", ");
    return `<span class="group-status-rollup" title="${esc(help)}">${esc(label)}</span>`;
  }



  function matchesCatalogFilters(pattern) {
    const haystack = [
      pattern.slug, pattern.title, pattern.description,
      pattern.topology, ...(pattern.tags || [])
    ].join(" ").toLowerCase();
    const needle = catalogFilters.search.trim().toLowerCase();
    return (!needle || haystack.includes(needle))
      && (catalogFilters.group === "all" || patternGroupKey(pattern) === catalogFilters.group)
      && (catalogFilters.topology === "all" || pattern.topology === catalogFilters.topology);
  }

  const anyFilterSet = () =>
    catalogFilters.group !== "all" || catalogFilters.topology !== "all" || catalogFilters.search.trim() !== "";

  // Single entry point for a catalog state change: merge, write the URL, redraw.
  // `replace` is for keystroke-rate changes (typing in the search box), which
  // should not leave one history entry per character.
  function applyFilters(patch, { replace = false, home = false } = {}) {
    catalogFilters = { ...catalogFilters, ...patch };
    if (home && selected) showCatalogHome(false);
    updateRoute(selected?.slug || "", replace);
    renderCatalogHome();
    renderSidebar();
  }

  function catalogFilterButton(value, label, count, type) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = catalogFilters[type] === value ? "active" : "";
    button.dataset.value = value;
    button.setAttribute("aria-pressed", String(catalogFilters[type] === value));
    button.innerHTML = `<span>${esc(label)}</span><small>${count}</small>`;
    button.addEventListener("click", () => applyFilters({ [type]: value }));
    return button;
  }

  // ===================== CATALOG (filters, cards, groups, list) =====================
  // The group axis moved to the sidebar rail, so the catalog's own filter row
  // carries the topology axis and a reset for whatever is currently narrowing
  // the results — group, topology or search.
  function renderCatalogFilters() {
    const needle = catalogFilters.search.trim().toLowerCase();
    const inScope = (item) =>
      (catalogFilters.group === "all" || patternGroupKey(item) === catalogFilters.group)
      && (!needle || [item.slug, item.title, item.description, item.topology, ...(item.tags || [])]
        .join(" ").toLowerCase().includes(needle));
    const topologies = [["all", "Any topology"], ...Object.entries(TOPOLOGIES).map(([value, info]) => [value, info.label])];
    const topologyFilters = $("catalog-topology-filters");
    const buttons = topologies.map(([value, label]) =>
      catalogFilterButton(value, label, patterns.filter((item) =>
        inScope(item) && (value === "all" || item.topology === value)).length, "topology")
    );
    if (anyFilterSet()) {
      const clear = document.createElement("button");
      clear.type = "button";
      clear.className = "filter-clear";
      clear.textContent = "Clear filters";
      clear.addEventListener("click", () => {
        $("pattern-search").value = "";
        applyFilters({ group: "all", topology: "all", search: "" }, { home: true });
      });
      buttons.push(clear);
    }
    topologyFilters.replaceChildren(...buttons);
  }

  function patternCard(pattern, { showGroup = true } = {}) {
    const [key, info] = patternGroup(pattern);
    const topology = TOPOLOGIES[pattern.topology] || { label: pattern.topology, help: pattern.topology };
    const activeSession = control.snapshot?.session;
    const running = activeSession?.slug === pattern.slug;
    const card = document.createElement("button");
    card.type = "button";
    card.className = `catalog-card${pattern.graph ? "" : " pending"}${running ? " running" : ""}`;
    card.addEventListener("click", () => selectPattern(pattern.slug));

    const header = document.createElement("span");
    // Without the group mark the header is two columns, not three, or the
    // badges land in the middle column instead of against the right edge.
    header.className = `catalog-card-header${showGroup ? "" : " no-mark"}`;
    const mark = document.createElement("span");
    mark.className = `pattern-group-mark ${key}`;
    mark.innerHTML = patternGroupIcon(info.icon, true);
    const context = document.createElement("span");
    context.className = "catalog-card-context";
    // On a group page the group name is the page title, and "Pattern" on a
    // pattern card says nothing — so that line is dropped and only the
    // provenance and status line remains.
    context.innerHTML = (showGroup ? `<span>${esc(info.title)}</span>` : "")
      + `<small>${pattern.location === "workspace" ? "Workspace" : "Curated"}</small>`;
    const status = patternStatusBadge(pattern.status);
    if (status) context.querySelector("small").append(" · ", status);
    const badge = document.createElement("span");
    badge.className = `topology-badge ${pattern.topology}`;
    badge.textContent = topology.label;
    badge.title = topology.help;
    const badges = document.createElement("span");
    badges.className = "pattern-badges";
    const direction = directionBadge(pattern);
    if (direction) badges.append(direction);
    if (pattern.experimental) {
      const exp = document.createElement("span");
      exp.className = "experimental-badge";
      exp.textContent = "Experimental";
      exp.title = "Newer pattern, not yet battle-tested; the mechanics may change.";
      badges.append(exp);
    }
    badges.append(badge);
    if (showGroup) header.append(mark, context, badges);
    else header.append(context, badges);

    const title = document.createElement("strong");
    title.className = "catalog-card-title";
    title.textContent = displayTitle(pattern);
    const description = document.createElement("span");
    description.className = "catalog-card-description";
    description.textContent = plainDesc(pattern.description);

    const footer = document.createElement("span");
    footer.className = "catalog-card-footer";
    const flow = document.createElement("span");
    flow.className = pattern.graph ? "has-flow" : "no-flow";
    flow.textContent = pattern.graph
      ? `${pattern.graph.resources.length} resources · ${pattern.graph.connections.length} links`
      : "Resource flow pending";
    const action = document.createElement("span");
    action.className = "catalog-card-action";
    action.textContent = running ? "Live now ●" : "Explore →";
    footer.append(flow, action);
    card.append(header, title, description, footer);
    return card;
  }

  function groupCard(key, items, info) {
    const card = document.createElement("div");
    card.className = "group-card";
    card.tabIndex = 0;
    card.setAttribute("role", "button");
    // The tile shows one sentence only: the group's short description, or the
    // first sentence of the intro as a fallback. The full intro lives on the
    // group's own page. Links/bold are flattened since the whole card is clickable.
    const firstSentence = (text) => {
      const flat = text.split(/\n{2,}/)[0].replace(/\s+/g, " ").trim();
      const match = flat.match(/^.*?[.!?](?=\s|$)/);
      return match ? match[0] : flat;
    };
    const summary = ((info.description || "").trim() || firstSentence(info.intro || ""))
      .replace(/\[([^\]]+)\]\([^)\s]+\)/g, "$1")
      .replace(/\*\*([^*]+)\*\*/g, "$1");
    card.innerHTML =
      `<div class="group-card-head">${patternGroupIcon(info.icon, true)}` +
      `<div class="group-card-titles"><strong>${esc(info.title)}</strong>` +
      `<div class="group-card-meta"><span class="group-card-count">${items.length} ${items.length === 1 ? "pattern" : "patterns"}</span>${groupStatusRollup(items)}</div></div></div>` +
      (summary ? `<p class="group-card-intro">${esc(summary)}</p>` : "");
    const openGroup = () => applyFilters({ group: key });
    card.addEventListener("click", openGroup);
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); openGroup(); }
    });
    return card;
  }

  const GITHUB_MARK = '<svg viewBox="0 0 16 16" width="13" height="13" fill="currentColor" aria-hidden="true">'
    + '<path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49'
    + '-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 '
    + '1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 '
    + '0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 '
    + '1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 '
    + '0 0 0 16 8c0-4.42-3.58-8-8-8z"/></svg>';

  // The landing page is described like a group, so the same title / lede /
  // intro rendering covers both and the two pages cannot drift apart.
  const HOME_GROUP = {
    key: "all",
    title: "All patterns",
    description: "In ClickHouse, ingestion, retention, and replication are as complex as data modelling and query design.",
    intro: "Compare runnable patterns, understand their trade-offs, and adapt them for your own systems.\n\n"
      + "This catalog is a work in progress. Check each pattern's status before adapting it.\n\n"
      + "[How to run patterns locally](https://github.com/dmkskd/clickhouse-patterns#run-patterns-locally)"
  };

  // Matches .group-intro-preview.collapsed in app.css.
  const COLLAPSED_INTRO_HEIGHT = 138;

  function renderIntro(text) {
    // group.yaml is trusted authoring, so allow inline [label](url) markdown links.
    return esc(text)
      .replace(
        /\[([^\]]+)\]\(([^)\s]+)\)/g,
        (_match, label, url) => `<a href="${url}" target="_blank" rel="noopener noreferrer">${label}</a>`
      )
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`]+)`/g, "<code>$1</code>");
  }

  // Support wrapped list items from YAML literal blocks: the continuation line
  // belongs to the preceding "- " item.
  function introListItems(block) {
    const items = [];
    let current = null;
    block.split("\n").map((line) => line.trim()).filter(Boolean).forEach((line) => {
      if (line.startsWith("- ")) {
        if (current !== null) items.push(current);
        current = line.slice(2);
      } else if (current !== null) {
        current += ` ${line}`;
      }
    });
    if (current !== null) items.push(current);
    return items;
  }

  // A paragraph that starts a sequence of "- " items becomes a list; anything
  // else stays a paragraph. Wrapped source lines remain in their list item.
  function isIntroList(block) {
    return block.trim().startsWith("- ") && introListItems(block).length > 1;
  }

  function renderIntroBlock(block) {
    if (isIntroList(block)) {
      const items = introListItems(block)
        .map((item) => `<li>${renderIntro(item)}</li>`).join("");
      return `<ul class="group-intro-list">${items}</ul>`;
    }
    return `<p>${renderIntro(block)}</p>`;
  }

  // A list and the paragraph introducing it are one unit, so the two-column
  // flow cannot strand the paragraph at the foot of a column.
  function renderIntroBody(blocks) {
    const out = [];
    blocks.forEach((block) => {
      const html = renderIntroBlock(block);
      if (isIntroList(block) && out.length) {
        out[out.length - 1] = `<div class="group-intro-pair">${out[out.length - 1]}${html}</div>`;
        return;
      }
      out.push(html);
    });
    return out.join("");
  }

  // Long prose opens as a faded preview with a Show more toggle. The hero and
  // every group intro use this one implementation; `key` remembers what the
  // reader opened for the rest of the session.
  const introExpanded = new Map();

  function attachShowMore(preview, key) {
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "group-intro-toggle";
    toggle.setAttribute("aria-controls", preview.id);
    toggle.hidden = true;
    const apply = (open) => {
      preview.classList.toggle("collapsed", !open);
      toggle.setAttribute("aria-expanded", String(open));
      toggle.textContent = open ? "Show less ↑" : "Show more ↓";
    };
    apply(introExpanded.get(key) ?? false);
    toggle.addEventListener("click", () => {
      const open = toggle.getAttribute("aria-expanded") !== "true";
      introExpanded.set(key, open);
      apply(open);
    });
    preview.after(toggle);
    // Only text that actually overflows the collapsed height needs a toggle.
    requestAnimationFrame(() => {
      if (!preview.isConnected) return;
      const overflows = preview.scrollHeight > COLLAPSED_INTRO_HEIGHT + 8;
      toggle.hidden = !overflows;
      if (!overflows) preview.classList.remove("collapsed");
    });
    return toggle;
  }

  // The group's intro sits between the page heading and the pattern toolbar, so
  // a group page reads as one page: title, what it is, then its patterns.
  function renderGroupIntro(info) {
    const slot = $("catalog-group-intro");
    if (!slot) return;
    if (!info) { slot.hidden = true; slot.replaceChildren(); return; }
    slot.hidden = false;
    const paras = (info.intro || info.description || "").split(/\n{2,}/).map((s) => s.trim()).filter(Boolean);
    const [lead, ...rest] = paras;
    slot.innerHTML =
      `<div class="group-intro-preview" id="group-intro-${esc(info.key)}">` +
      (lead ? `<p class="group-intro-lead">${renderIntro(lead)}</p>` : "") +
      (rest.length ? `<div class="group-intro-body">${renderIntroBody(rest)}</div>` : "") +
      `</div>`;
    // A link to the repository is a link, not prose: it keeps the GitHub mark it
    // had before this copy moved into the intro.
    slot.querySelectorAll('a[href*="github.com/dmkskd/clickhouse-patterns"]').forEach((link) => {
      link.className = "clone-guide-link";
      link.insertAdjacentHTML("afterbegin", GITHUB_MARK);
      // A paragraph that is only this link is a control, not prose: it moves to
      // the top-right of the intro so the copy keeps one straight left edge.
      const para = link.closest("p");
      if (para && para.childElementCount === 1 && para.textContent.trim() === link.textContent.trim()) {
        para.classList.add("group-intro-action");
      }
    });
    attachShowMore(slot.querySelector(".group-intro-preview"), info.key);
  }

  // External reading and related groups render below the pattern cards, not
  // between the intro and the grid — they are end-of-page material.
  function groupFooter(info) {
    const related = (info.related || []).map((link) => {
      const target = PATTERN_GROUPS[link.group];
      if (!target) return "";
      return `<li><button type="button" class="group-link" data-group="${esc(link.group)}"` +
        (link.note ? ` title="${esc(link.note)}"` : "") + `>${esc(target.title)}</button></li>`;
    }).join("");
    const reading = (info.links || []).map((link) =>
      `<li><a class="reading-link" href="${esc(link.url)}" target="_blank" rel="noopener noreferrer"` +
      (link.note ? ` title="${esc(link.note)}"` : "") + `>${esc(link.label)}</a></li>`
    ).join("");
    if (!reading && !related) return null;
    const footer = document.createElement("section");
    footer.className = "catalog-group-footer";
    footer.innerHTML =
      `<div class="group-intro-footer">` +
      (related ? `<div class="group-related"><span>Related patterns</span><ul>${related}</ul></div>` : "") +
      (reading ? `<div class="group-links"><span>Further reading</span><ul>${reading}</ul></div>` : "") +
      `</div>`;
    footer.querySelectorAll(".group-link").forEach((btn) => btn.addEventListener("click", () => {
      applyFilters({ group: btn.dataset.group });
      $("catalog-home")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }));
    return footer;
  }

  function renderCatalogHome() {
    renderCatalogFilters();
    const visible = patterns.filter(matchesCatalogFilters);
    const query = catalogFilters.search.trim();
    const group = catalogFilters.group === "all" ? HOME_GROUP : PATTERN_GROUPS[catalogFilters.group];
    // The page heading is the thing being read: the group's title on a group
    // page, the landing question on the landing page, the query when searching.
    const lede = $("catalog-browser-lede");
    const title = $("catalog-browser-title");
    title.textContent = query ? `Results for “${query}”` : group ? group.title : "";
    title.hidden = !title.textContent;
    lede.textContent = !query && group ? group.description || "" : "";
    lede.hidden = !lede.textContent;
    renderGroupIntro(query ? null : group);
    $("catalog-results-summary").textContent = `${visible.length} ${visible.length === 1 ? "pattern" : "patterns"}`;
    const grid = $("catalog-grid");
    if (!visible.length) {
      grid.classList.remove("as-groups");
      renderGroupIntro(null);
      grid.innerHTML = '<div class="catalog-empty"><strong>No matching patterns</strong><span>Try another search term or clear a filter.</span><button type="button">Clear filters</button></div>';
      grid.querySelector(".catalog-empty button")?.addEventListener("click", () => {
        $("pattern-search").value = "";
        applyFilters({ group: "all", topology: "all", search: "" });
      });
      return;
    }
    const byGroup = new Map();
    visible.forEach((pattern) => {
      const key = patternGroupKey(pattern);
      if (!byGroup.has(key)) byGroup.set(key, []);
      byGroup.get(key).push(pattern);
    });
    if (catalogFilters.group === "all") {
      // Landing: give the real estate to the groups. One tile per family, its
      // patterns as one-liners; click a tile to drill into the full cards.
      // A search or a topology filter is a question about patterns, though, so
      // those answer with the matching patterns across every group instead.
      if (!anyFilterSet()) {
        grid.classList.add("as-groups");
        grid.replaceChildren(...[...byGroup].map(([key, items]) =>
          groupCard(key, items, PATTERN_GROUPS[key] || patternGroup(items[0])[1])));
        return;
      }
      grid.classList.remove("as-groups");
      grid.replaceChildren(...visible.map(patternCard));
      return;
    }
    // Drill-in: the family's fuller intro, its pattern cards, then the
    // further-reading footer below the grid.
    grid.classList.remove("as-groups");
    const [groupKey, groupItems] = [...byGroup][0];
    const info = PATTERN_GROUPS[groupKey] || patternGroup(groupItems[0])[1];
    grid.replaceChildren(...groupItems.map((pattern) => patternCard(pattern, { showGroup: false })));
    const footer = groupFooter(info);
    if (footer) grid.append(footer);
  }

  // The sidebar is one flat rail: "All patterns" over one row per group. Only
  // the group in view unfolds its patterns, so the column stays short enough to
  // read at a glance instead of listing every pattern in the catalog.
  function patternOption(pattern) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `pattern-option${pattern.slug === selected?.slug ? " active" : ""}${pattern.graph ? "" : " pending"}`;
    button.title = pattern.slug;
    const row = document.createElement("span");
    row.className = "pattern-option-row";
    const strong = document.createElement("strong");
    strong.textContent = displayTitle(pattern);
    // No topology or direction badge here: the rail is for moving between
    // patterns, and both are on the card and the pattern page. Only a running
    // session still shows, because that is state the rail cannot repeat.
    const badges = document.createElement("span");
    badges.className = "pattern-badges";
    const activeSession = control.snapshot?.session;
    if (activeSession?.slug === pattern.slug) {
      const healthy = activeSession.reachable && activeSession.phase !== "failed";
      const runtime = document.createElement("span");
      runtime.className = `runtime-status${healthy ? " running" : " failed"}`;
      runtime.title = activeSession.reachable ? "Running now" : "Active session is not reachable";
      runtime.setAttribute("aria-label", runtime.title);
      badges.append(runtime);
    }
    row.append(strong, badges);
    button.append(row);
    button.addEventListener("click", () => selectPattern(pattern.slug));
    return button;
  }

  function renderSidebar() {
    const nav = $("group-nav");
    if (!nav) return;
    const needle = catalogFilters.search.trim().toLowerCase();
    const matches = (pattern) =>
      [pattern.slug, pattern.title, pattern.description, pattern.topology, ...(pattern.tags || [])]
        .join(" ").toLowerCase().includes(needle);
    const visible = patterns.filter(matches);
    const active = selected ? patternGroupKey(selected) : catalogFilters.group;

    const heading = document.createElement("span");
    heading.className = "group-nav-heading";
    heading.textContent = "Explore";

    const link = (key, label, count, onClick, current) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `group-navlink${current ? " active" : ""}`;
      button.setAttribute("aria-current", current ? "true" : "false");
      const text = document.createElement("span");
      text.textContent = label;
      const badge = document.createElement("small");
      badge.textContent = String(count);
      button.append(text, badge);
      button.addEventListener("click", onClick);
      return button;
    };

    const rows = [heading, link("all", "All patterns", patterns.length, () => {
      $("pattern-search").value = "";
      applyFilters({ group: "all", topology: "all", search: "" }, { home: true });
    }, !selected && active === "all" && !needle)];

    GROUPS.forEach((group) => {
      const items = visible.filter((pattern) => patternGroupKey(pattern) === group.key);
      const total = patterns.filter((pattern) => patternGroupKey(pattern) === group.key).length;
      // A search reveals every group that still has a hit; otherwise only the
      // group being read is unfolded.
      const unfold = needle ? items.length > 0 : group.key === active;
      if (needle && !items.length) return;
      const item = document.createElement("div");
      item.className = `group-nav-item${unfold ? " open" : ""}`;
      item.append(link(group.key, group.label, needle ? items.length : total,
        () => applyFilters({ group: group.key }, { home: true }), group.key === active));
      if (unfold) {
        const options = document.createElement("div");
        options.className = "pattern-options";
        items.forEach((pattern) => options.append(patternOption(pattern)));
        item.append(options);
      }
      rows.push(item);
    });
    nav.replaceChildren(...rows);
  }

  // ===================== PATTERN DETAIL: trade-offs + diagram zoom =====================
  function renderTradeoffs(pattern) {
    const section = $("tradeoffs");
    const values = pattern.tradeoffs;
    if (!values || (!values.benefits?.length && !values.limitations?.length)) { section.hidden = true; return; }
    section.hidden = false;
    const fill = (element, items) => {
      element.replaceChildren(...(items || []).map((item) => {
        const li = document.createElement("li"); li.textContent = item; return li;
      }));
    };
    fill($("benefits"), values.benefits); fill($("limitations"), values.limitations);
  }

  // The Definition strip under the diagram shows the pattern's source files in
  // lifecycle order: Structure (schema) -> Load -> Verify (query + expected),
  // plus any per-service customization the pattern mounts (ClickHouse config
  // fragments, database init scripts).
  function codeBlock(file, code, lang) {
    const source = code || "";
    // Highlight.js escapes input before returning its markup. Keep the fallback
    // escaped as well, so source files are never interpreted as page HTML.
    const highlighted = window.hljs && ["yaml", "sql", "python", "xml"].includes(lang)
      ? window.hljs.highlight(source, { language: lang, ignoreIllegals: true }).value
      : esc(source);
    return `<figure class="code-file"><figcaption>${esc(file)}</figcaption>`
      + `<pre class="code lang-${esc(lang)}"><code class="hljs language-${esc(lang)}">${highlighted}</code></pre></figure>`;
  }

  function expectedTable(file, tsv) {
    const text = (tsv || "").trim();
    const rows = text ? text.split("\n").map((line) => {
      // '#' lines are annotations (usually a column header); show them as a
      // dimmed row, still split on tabs so the labels align with the columns.
      const comment = line.startsWith("#");
      const cells = (comment ? line.replace(/^#\s?/, "") : line).split("\t");
      return `<tr${comment ? ' class="expected-comment"' : ""}>${cells.map((cell) => `<td>${esc(cell)}</td>`).join("")}</tr>`;
    }) : [];
    const body = rows.length
      ? rows.join("")
      : `<tr><td>(empty)</td></tr>`;
    return `<figure class="code-file"><figcaption>${esc(file)}</figcaption>`
      + `<div class="expected-scroll"><table class="expected-table"><tbody>${body}</tbody></table></div></figure>`;
  }

  // Source files open in a dialog over the diagram. They used to expand a strip
  // under the panel, which pushed the page around and put the file far from the
  // control that asked for it.
  const definitionModal = $("definition-modal");
  const DEFINITION_TABS = [
    ["manifest", "Manifest"], ["config", "Configuration"], ["structure", "DDL"],
    ["load", "Loader"], ["verify", "Verification"]
  ];

  function showDefinition(pattern, key) {
    const def = pattern.definition || {};
    const body = $("definition-body");
    // Clicking the tab that is already open closes the dialog again.
    if (definitionModal.open && definitionModal.dataset.key === key) { definitionModal.close(); return; }
    definitionModal.dataset.key = key;
    $("definition-modal-title").textContent = pattern.title;
    if (key === "verify") {
      const v = def.verify;
      body.className = "definition-body verify";
      body.innerHTML = codeBlock(v.sqlFile, v.sql, "sql")
        + (v.expected != null ? expectedTable(v.expectedFile, v.expected) : "");
    } else if (key === "config") {
      body.className = "definition-body configuration";
      body.innerHTML = def.config.map((item) =>
        codeBlock(`${item.file} · ${item.node} → ${item.mountPath}`
          + (item.dependsOn?.length ? ` · after ${item.dependsOn.join(", ")}` : ""), item.code, item.lang)
      ).join("");
    } else {
      const d = def[key];
      body.className = "definition-body";
      body.innerHTML = codeBlock(d.file, d.code, d.lang);
    }
    body.scrollTop = 0;
    // The dialog carries its own copy of the tabs, so a reader can move between
    // files without closing it.
    const inModal = $("definition-modal-tabs");
    inModal.replaceChildren(...DEFINITION_TABS.filter(([k]) => def[k]).map(([k, label]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.def = k;
      button.textContent = label;
      button.className = k === key ? "active" : "";
      button.addEventListener("click", () => showDefinition(pattern, k));
      return button;
    }));
    document.querySelectorAll("#definition-tabs button").forEach((b) =>
      b.classList.toggle("active", b.dataset.def === key));
    if (!definitionModal.open) definitionModal.showModal();
    // showModal() autofocuses the first control, which lands a focus ring on the
    // first tab. The file itself is the thing being read, so it takes focus.
    body.focus({ preventScroll: true });
  }

  function renderDefinition(pattern) {
    const def = pattern.definition || {};
    const tabs = DEFINITION_TABS.filter(([key]) => def[key]);
    $("definition-tabs").replaceChildren(...tabs.map(([key, label]) => {
      const b = document.createElement("button");
      b.type = "button"; b.dataset.def = key; b.textContent = label;
      b.addEventListener("click", () => showDefinition(pattern, key));
      return b;
    }));
    // Nothing is loaded until a tab is clicked; switching pattern closes any
    // file left open from the previous one.
    if (definitionModal.open) definitionModal.close();
    delete definitionModal.dataset.key;
    $("definition-body").innerHTML = "";
    // The row carries the legend and the tabs; it hides only with neither.
    $("control-strip").hidden = !tabs.length && !$("flow-legend").childElementCount;
  }

  function updateZoomControl(hasDiagram = Boolean(canvas.querySelector("svg"))) {
    const percent = Math.round(diagramZoom * 100);
    $("zoom-reset").textContent = `${percent}%`;
    $("zoom-reset").disabled = !hasDiagram;
    $("zoom-out").disabled = !hasDiagram || diagramZoom <= MIN_ZOOM;
    $("zoom-in").disabled = !hasDiagram || diagramZoom >= MAX_ZOOM;
  }

  // A wide, shallow diagram (the schematic view especially) is scaled to the canvas
  // width and then leaves the rest of the canvas empty. Centre it vertically so
  // the empty space sits above and below rather than all below.
  function centreIfShorter(target) {
    requestAnimationFrame(() => {
      const svg = target.querySelector("svg");
      target.classList.toggle("fits-height", Boolean(svg) && svg.clientHeight < target.clientHeight);
    });
  }

  function applyCanvasZoom(targetCanvas, nextZoom, previousZoom, anchorX, anchorY) {
    const svg = targetCanvas.querySelector("svg");
    if (!svg) return previousZoom;
    const next = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Math.round(nextZoom * 1000) / 1000));
    if (next === previousZoom) return previousZoom;
    const contentX = targetCanvas.scrollLeft + anchorX;
    const contentY = targetCanvas.scrollTop + anchorY;
    svg.style.width = `${next * 100}%`;
    svg.style.marginInline = next < 1 ? "auto" : "0";
    const ratio = next / previousZoom;
    targetCanvas.scrollLeft = Math.max(0, contentX * ratio - anchorX);
    targetCanvas.scrollTop = Math.max(0, contentY * ratio - anchorY);
    // Vertical centring only applies while the diagram is shorter than the
    // canvas; zooming past that has to release it, or the canvas cannot scroll.
    centreIfShorter(targetCanvas);
    return next;
  }

  function setDiagramZoom(nextZoom, anchorX = canvas.clientWidth / 2, anchorY = canvas.clientHeight / 2) {
    diagramZoom = applyCanvasZoom(canvas, nextZoom, diagramZoom, anchorX, anchorY);
    updateZoomControl();
  }

  function updateModalZoomControl() {
    $("modal-zoom-reset").textContent = `${Math.round(modalZoom * 100)}%`;
    $("modal-zoom-out").disabled = modalZoom <= MIN_ZOOM;
    $("modal-zoom-in").disabled = modalZoom >= MAX_ZOOM;
  }

  function setModalZoom(nextZoom, anchorX = modalCanvas.clientWidth / 2, anchorY = modalCanvas.clientHeight / 2) {
    modalZoom = applyCanvasZoom(modalCanvas, nextZoom, modalZoom, anchorX, anchorY);
    updateModalZoomControl();
  }

  function resetDiagramZoom() {
    diagramZoom = 1;
    canvas.scrollTo({ left: 0, top: 0 });
    const svg = canvas.querySelector("svg");
    if (svg) {
      svg.style.width = "100%";
      svg.style.marginInline = "0";
    }
    centreIfShorter(canvas);
    updateZoomControl(Boolean(svg));
  }

  function resetModalZoom() {
    modalZoom = 1;
    modalCanvas.scrollTo({ left: 0, top: 0 });
    const svg = modalCanvas.querySelector("svg");
    if (svg) { svg.style.width = "100%"; svg.style.marginInline = "0"; }
    centreIfShorter(modalCanvas);
    updateModalZoomControl();
  }

  // ===================== ARCHITECTURE VIEWS: LOGICAL vs PHYSICAL =====================
  // Logical is the pattern's resource flow, compiled into the catalog, and works
  // from a static file. Physical is the container wiring behind the pattern's
  // profiles, read from Docker by the local server, and offered only while this
  // pattern is the running session: all patterns share one Compose project, so
  // container state read against another pattern's stack is not this pattern's.
  function physicalAvailable() {
    const active = control.snapshot?.session;
    return Boolean(
      control.interactive && control.token && selected?.profiles?.length
      && active && active.slug === selected.slug
    );
  }

  function canvasMessage(title, detail) {
    return `<div class="empty-state"><div><strong>${esc(title)}</strong><br><span>${esc(detail)}</span></div></div>`;
  }

  async function renderPhysical() {
    const slug = selected?.slug;
    if (!slug) return;
    const request = (topologyRequest += 1);
    const stale = () =>
      request !== topologyRequest || selected?.slug !== slug || architectureView !== "physical";
    canvas.innerHTML = canvasMessage("Reading the Compose wiring…", `docker compose config for ${slug}`);
    $("download-svg").disabled = true;
    try {
      const response = await fetch(apiUrl(`api/topology?pattern=${encodeURIComponent(slug)}`), {
        cache: "no-store",
        headers: { "X-Explorer-Token": control.token }
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || `request failed (${response.status})`);
      if (stale()) return;
      canvas.innerHTML = PE.topology.render(payload);
      resetDiagramZoom();
      $("download-svg").disabled = false;
      syncModalDiagram();
    } catch (error) {
      if (stale()) return;
      const detail = error instanceof Error ? error.message : String(error);
      canvas.innerHTML = canvasMessage("Container topology unavailable", detail);
      resetDiagramZoom();
      syncModalDiagram();
    }
  }

  // The panel and the expanded modal carry the same switch, driven by the one
  // `architectureView` state, so switching in either place keeps them in step.
  const VIEW_TITLES = {
    logical: "Resource flow", schematic: "Resource diagram", physical: "Container topology"
  };

  function updateViewToggle() {
    const physical = architectureView === "physical";
    const available = physicalAvailable();
    // Logical and schematic are always offered. The physical button appears only
    // where it exists: a pattern that is not running has no containers to draw,
    // so a disabled button would be noise.
    [["architecture-view", "view", "flow-legend"],
     ["modal-architecture-view", "modal-view", "modal-flow-legend"]]
      .forEach(([group, prefix, legendId]) => {
        const container = $(group);
        if (!container) return;
        container.hidden = false;
        ["logical", "schematic", "physical"].forEach((view) => {
          const button = $(`${prefix}-${view}`);
          if (!button) return;
          button.hidden = view === "physical" && !available;
          button.classList.toggle("active", view === architectureView);
          button.setAttribute("aria-pressed", String(view === architectureView));
        });
        if ($(legendId)) $(legendId).hidden = physical;
      });
    $("architecture-title").textContent = VIEW_TITLES[architectureView];
    if (diagramModal.open) $("diagram-modal-title").textContent = modalTitle();
  }

  function modalTitle() {
    if (!selected) return "Resource flow";
    if (architectureView === "physical") return `${selected.title} · containers`;
    return architectureView === "schematic" ? `${selected.title} · diagram` : selected.title;
  }

  // The modal shows a clone of whatever the panel currently holds, so a view
  // switch or a re-render while it is open has to be mirrored into it.
  function syncModalDiagram() {
    if (!diagramModal.open) return;
    modalCanvas.replaceChildren(...[...canvas.children].map((node) => {
      const copy = node.cloneNode(true);
      copy.removeAttribute?.("style");
      return copy;
    }));
    $("diagram-modal-title").textContent = modalTitle();
    resetModalZoom();
  }

  function renderArchitecture() {
    updateViewToggle();
    if (architectureView === "physical") { renderPhysical(); return; }
    const draw = architectureView === "schematic" ? PE.diagram.renderSchematic : PE.diagram.render;
    if (selected?.graph) canvas.innerHTML = draw(selected, { inspectable: canInspectSelectedPattern() });
    else canvas.innerHTML = canvasMessage("Architecture pending", "This pattern has not declared a compact resource graph yet.");
    resetDiagramZoom();
    $("download-svg").disabled = !selected?.graph;
    syncModalDiagram();
  }

  function setArchitectureView(view) {
    if (view === "physical" && !physicalAvailable()) return;
    if (view === architectureView) return;
    architectureView = view;
    // Which drawing of the graph the reader prefers is a browser-local setting,
    // like the diagram's placement. Physical is a per-session step down into the
    // containers, so it is never remembered.
    if (GRAPH_VIEWS.includes(view)) {
      graphView = view;
      try { localStorage.setItem(DIAGRAM_VIEW_KEY, view); } catch (_error) { /* private mode */ }
    }
    renderArchitecture();
  }

  // Called by session.js after every control-plane refresh. Polling is frequent
  // and re-rendering resets zoom, so redraw the physical view only when the
  // session state it depicts actually moved; otherwise refresh only the toggle.
  let lastSessionSignature = null;
  function syncArchitecture() {
    if (!selected || $("pattern-detail").hidden) return;
    if (architectureView === "physical" && !physicalAvailable()) {
      architectureView = graphView;
      renderArchitecture();
      return;
    }
    const snapshot = control.snapshot;
    const signature = [
      snapshot?.session?.slug, snapshot?.session?.phase,
      snapshot?.operation?.name, snapshot?.operation?.status
    ].join("|");
    const moved = signature !== lastSessionSignature;
    lastSessionSignature = signature;
    if (architectureView === "physical" && moved) renderArchitecture();
    else updateViewToggle();
  }

  ["logical", "schematic", "physical"].forEach((view) => {
    ["view", "modal-view"].forEach((prefix) =>
      $(`${prefix}-${view}`)?.addEventListener("click", () => setArchitectureView(view)));
  });

  // ===================== DIAGRAM PLACEMENT & COLLAPSE =====================
  // Both are browser-local viewer preferences (localStorage), not per-pattern
  // settings: the reader keeps the diagram where they like it. The panel is a
  // single self-contained section, so placement is one insertBefore move.
  const DIAGRAM_PLACE_KEY = "pe.diagramPlacement";
  const DIAGRAM_COLLAPSE_KEY = "pe.diagramCollapsed";
  const architecturePanel = document.querySelector(".architecture-panel");
  // The two locations the page layout has used: below the whole description
  // (current) and right after the lede (previous).
  const DIAGRAM_PLACES = ["middle", "bottom"];

  function applyDiagramPlacement(place, persist = true) {
    const lede = $("pattern-description-lede");
    architecturePanel.classList.toggle("diagram-bottom", place === "bottom");
    if (place === "bottom") $("pattern-description").after(architecturePanel);
    else lede.after(architecturePanel);
    if (persist) try { localStorage.setItem(DIAGRAM_PLACE_KEY, place); } catch (_error) { /* private mode */ }
    DIAGRAM_PLACES.forEach((p) => {
      const button = $(`place-${p}`);
      button.classList.toggle("active", p === place);
      button.setAttribute("aria-pressed", String(p === place));
    });
  }

  function applyDiagramCollapsed(collapsed, persist = true) {
    architecturePanel.classList.toggle("diagram-collapsed", collapsed);
    const button = $("collapse-diagram");
    button.setAttribute("aria-expanded", String(!collapsed));
    button.title = collapsed ? "Expand diagram" : "Collapse diagram";
    button.setAttribute("aria-label", button.title);
    if (persist) try { localStorage.setItem(DIAGRAM_COLLAPSE_KEY, collapsed ? "1" : "0"); } catch (_error) { /* private mode */ }
  }

  DIAGRAM_PLACES.forEach((p) =>
    $(`place-${p}`).addEventListener("click", () => applyDiagramPlacement(p)));
  $("collapse-diagram").addEventListener("click", () =>
    applyDiagramCollapsed(!architecturePanel.classList.contains("diagram-collapsed")));

  try {
    const savedPlace = localStorage.getItem(DIAGRAM_PLACE_KEY);
    applyDiagramPlacement(DIAGRAM_PLACES.includes(savedPlace) ? savedPlace : "bottom", false);
    applyDiagramCollapsed(localStorage.getItem(DIAGRAM_COLLAPSE_KEY) === "1", false);
  } catch (_error) {
    applyDiagramPlacement("bottom", false);
  }

  // ===================== ROUTING & PATTERN SELECTION (detail view) =====================
  // The whole catalog state is the route, so a link carries the group, the
  // topology, the query and the open pattern together.
  function updateRoute(slug, replace = false) {
    const url = new URL(window.location.href);
    const set = (key, value, blank) => {
      if (value && value !== blank) url.searchParams.set(key, value);
      else url.searchParams.delete(key);
    };
    set("pattern", slug, "");
    set("group", catalogFilters.group, "all");
    set("topology", catalogFilters.topology, "all");
    set("q", catalogFilters.search.trim(), "");
    if (url.href === window.location.href) return;
    // Leaving the catalog for a pattern: remember where the reader was, so the
    // back button returns to the same scroll position and not to the top.
    if (slug && !selectedSlugInRoute()) history.replaceState({ scroll: window.scrollY }, "");
    history[replace ? "replaceState" : "pushState"]({}, "", url);
  }

  const selectedSlugInRoute = () => new URL(window.location.href).searchParams.get("pattern") || "";

  function showCatalogHome(updateUrl = true) {
    if (resourceInspector.open) resourceInspector.close();
    if (diagramModal.open) diagramModal.close();
    selected = null;
    document.querySelector(".app-shell").classList.add("home-view");
    $("catalog-home").hidden = false;
    $("pattern-detail").hidden = true;
    document.title = "ClickHouse Pattern Explorer";
    if (updateUrl) updateRoute("");
    renderCatalogHome();
    renderSidebar();
    session.renderSession();
  }

  function selectPattern(slug, updateUrl = true) {
    if (resourceInspector.open) resourceInspector.close();
    selected = patterns.find((pattern) => pattern.slug === slug);
    if (!selected) { showCatalogHome(updateUrl); return; }
    document.querySelector(".app-shell").classList.remove("home-view");
    $("catalog-home").hidden = true;
    $("pattern-detail").hidden = false;
    renderBreadcrumb(selected);
    $("pattern-title").textContent = selected.title;
    renderPatternMeta(selected);
    renderPatternTags(selected.tags);
    renderDescription(selected.description);
    renderRequires(selected.requires);
    renderExperimental(selected);
    renderSuperseded(selected);
    const references = $("pattern-references");
    const entries = (selected.references || []).map((reference) => {
      const link = document.createElement("a");
      link.href = reference.url;
      link.target = "_blank";
      link.rel = "noreferrer";
      link.textContent = reference.label;
      return link;
    });
    const referencesHead = document.createElement("span");
    referencesHead.className = "references-head";
    referencesHead.textContent = "References";
    references.replaceChildren(...(entries.length ? [referencesHead, ...entries] : []));
    references.hidden = !entries.length;
    const relatedPatterns = $("pattern-related");
    const related = (selected.related_patterns || [])
      .map((relation) => ({ relation, target: patterns.find((pattern) => pattern.slug === relation.slug) }))
      .filter(({ target }) => target);
    relatedPatterns.replaceChildren();
    if (related.length) {
      const label = document.createElement("span");
      label.textContent = "Related guidance";
      relatedPatterns.append(label);
      related.forEach(({ relation, target }) => {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = target.title;
        button.title = relation.note || `Open ${target.title}`;
        button.addEventListener("click", () => selectPattern(target.slug));
        relatedPatterns.append(button);
      });
    }
    relatedPatterns.hidden = !related.length;
    $("pattern-links").hidden = references.hidden && relatedPatterns.hidden;
    document.title = `${selected.title} — Pattern Explorer`;
    renderTradeoffs(selected);
    renderDefinition(selected);
    const flows = selected.graph?.flows || [];
    const legendHtml = flows.map((flow) => `<span><i style="background:${FLOW_COLORS[flow] || "#8b93ad"}"></i>${esc(flow)}</span>`).join("");
    $("flow-legend").innerHTML = legendHtml;
    const modalLegend = $("modal-flow-legend");
    if (modalLegend) modalLegend.innerHTML = legendHtml;
    // Each pattern opens on the reader's preferred drawing of the graph; the
    // physical view is a deliberate, server-backed step down into the wiring.
    architectureView = graphView;
    renderArchitecture();
    if (updateUrl) updateRoute(selected.slug);
    renderSidebar();
    session.renderSession();
    window.scrollTo(0, 0);
  }

  // One search box for the whole catalog. Typing replaces the history entry
  // rather than pushing one per keystroke, and restores the caret across the
  // re-render.
  search.addEventListener("input", (event) => {
    const caret = event.target.selectionStart;
    applyFilters({ search: event.target.value }, { replace: true, home: true });
    search.focus();
    try { search.setSelectionRange(caret, caret); } catch (_error) { /* unsupported input type */ }
  });
  // The brand is "start over": back to the landing page with nothing narrowed.
  $("show-catalog-home").addEventListener("click", () => {
    $("pattern-search").value = "";
    applyFilters({ group: "all", topology: "all", search: "" }, { home: true });
  });
  const heroProse = $("catalog-hero-prose");
  if (heroProse) attachShowMore(heroProse, "catalog-hero");
  $("clone-pattern")?.addEventListener("click", () => $("clone-modal").showModal());
  $("clone-modal-close")?.addEventListener("click", () => $("clone-modal").close());
  $("definition-modal-close")?.addEventListener("click", () => definitionModal.close());
  definitionModal.addEventListener("click", (event) => {
    if (event.target === definitionModal) definitionModal.close();
  });
  definitionModal.addEventListener("close", () => {
    delete definitionModal.dataset.key;
    document.querySelectorAll("#definition-tabs button").forEach((b) => b.classList.remove("active"));
  });
  $("clone-modal")?.addEventListener("click", (event) => {
    if (event.target === $("clone-modal")) $("clone-modal").close();
  });
  window.addEventListener("popstate", (event) => {
    const route = readRoute();
    catalogFilters = { group: route.group, topology: route.topology, search: route.search };
    search.value = route.search;
    if (route.pattern) { selectPattern(route.pattern, false); return; }
    showCatalogHome(false);
    // Coming back from a pattern: land where the reader left the catalog.
    const scroll = event.state?.scroll;
    if (typeof scroll === "number") requestAnimationFrame(() => window.scrollTo(0, scroll));
  });
  $("zoom-out").addEventListener("click", () => setDiagramZoom(diagramZoom - ZOOM_STEP));
  $("zoom-reset").addEventListener("click", resetDiagramZoom);
  $("zoom-in").addEventListener("click", () => setDiagramZoom(diagramZoom + ZOOM_STEP));
  canvas.addEventListener("wheel", (event) => {
    if (!canvas.querySelector("svg")) return;
    const unit = event.deltaMode === WheelEvent.DOM_DELTA_LINE ? 16
      : event.deltaMode === WheelEvent.DOM_DELTA_PAGE ? canvas.clientHeight
      : 1;
    const delta = Math.max(-80, Math.min(80, event.deltaY * unit));
    if (!delta || (delta < 0 && diagramZoom >= MAX_ZOOM) || (delta > 0 && diagramZoom <= MIN_ZOOM)) return;
    event.preventDefault();
    const bounds = canvas.getBoundingClientRect();
    const factor = Math.exp(-delta * 0.0025);
    setDiagramZoom(diagramZoom * factor, event.clientX - bounds.left, event.clientY - bounds.top);
  }, { passive: false });
  // Drag to pan. Scrollbars alone are awkward on a zoomed diagram, and macOS
  // overlay bars are invisible until they move, so the canvas is grabbable.
  // A press that never travels more than a few pixels is still a click, so
  // inspecting a node keeps working.
  function enablePanning(target) {
    let panning = false;
    let moved = false;
    let startX = 0, startY = 0, scrollX = 0, scrollY = 0;
    target.addEventListener("pointerdown", (event) => {
      if (event.button !== 0 || !target.querySelector("svg")) return;
      panning = true;
      moved = false;
      startX = event.clientX;
      startY = event.clientY;
      scrollX = target.scrollLeft;
      scrollY = target.scrollTop;
    });
    target.addEventListener("pointermove", (event) => {
      if (!panning) return;
      const dx = event.clientX - startX, dy = event.clientY - startY;
      if (!moved && Math.hypot(dx, dy) < 4) return;
      if (!moved) { moved = true; target.setPointerCapture(event.pointerId); target.classList.add("panning"); }
      target.scrollLeft = scrollX - dx;
      target.scrollTop = scrollY - dy;
      event.preventDefault();
    });
    const end = (event) => {
      if (!panning) return;
      panning = false;
      target.classList.remove("panning");
      if (moved) {
        // The release ends a drag, not a click on whatever is underneath.
        target.releasePointerCapture?.(event.pointerId);
        event.preventDefault();
        event.stopPropagation();
      }
    };
    target.addEventListener("pointerup", end);
    target.addEventListener("pointercancel", end);
    target.addEventListener("click", (event) => { if (moved) { event.stopPropagation(); moved = false; } }, true);
  }
  enablePanning(canvas);
  enablePanning(modalCanvas);

  const noteTip = document.createElement("div");
  noteTip.className = "diagram-note-tip";
  noteTip.hidden = true;
  document.body.appendChild(noteTip);
  function positionNoteTip(event) {
    const pad = 14;
    const rect = noteTip.getBoundingClientRect();
    let x = event.clientX + pad, y = event.clientY + pad;
    if (x + rect.width > window.innerWidth - 8) x = event.clientX - rect.width - pad;
    if (y + rect.height > window.innerHeight - 8) y = event.clientY - rect.height - pad;
    noteTip.style.left = `${Math.max(8, x)}px`;
    noteTip.style.top = `${Math.max(8, y)}px`;
  }
  function hideNoteTip() { noteTip.hidden = true; }
  function renderNote(text) {
    const fragment = document.createDocumentFragment();
    text.split(/\\n/).forEach((rawLine) => {
      const line = rawLine.trim();
      const el = document.createElement("div");
      el.className = "note-line";
      let body = line;
      if (line.startsWith("- ")) { el.classList.add("note-bullet"); body = line.slice(2); }
      body.split(/(\*\*[^*]+\*\*)/).forEach((part) => {
        if (!part) return;
        if (part.startsWith("**") && part.endsWith("**")) {
          const strong = document.createElement("strong");
          strong.textContent = part.slice(2, -2);
          el.appendChild(strong);
        } else {
          el.appendChild(document.createTextNode(part));
        }
      });
      fragment.appendChild(el);
    });
    return fragment;
  }

  function renderRequires(req) {
    const el = $("pattern-requires");
    if (!req || (!req.clickhouse_min && !req.clickhouse_max)) { el.hidden = true; el.replaceChildren(); return; }
    const parts = [];
    if (req.clickhouse_min) parts.push(`ClickHouse ≥ ${req.clickhouse_min}`);
    if (req.clickhouse_max) parts.push(`ClickHouse ≤ ${req.clickhouse_max}`);
    const badge = document.createElement("span");
    badge.className = "requires-badge";
    badge.textContent = parts.join("   ·   ");
    el.replaceChildren(badge);
    if (req.note) {
      const note = document.createElement("span");
      note.className = "requires-note";
      note.textContent = req.note;
      el.append(note);
    }
    el.hidden = false;
  }

  // renderDescription paints the styled paragraphs into the DOM; the inline
  // markup and plain-text helpers it uses live in util.js.
  function renderDescription(text) {
    const el = $("pattern-description");
    const blocks = String(text ?? "").split(/\n{2,}/).map((s) => s.trim()).filter(Boolean);
    const nodes = blocks.map((block) => {
      const lines = block.split("\n").map((line) => line.trim()).filter(Boolean);
      if (!lines[0]?.startsWith("- ")) {
        const para = document.createElement("p");
        para.innerHTML = formatDescInline(block);
        return para;
      }

      const list = document.createElement("ul");
      const items = [];
      for (const line of lines) {
        if (line.startsWith("- ")) {
          items.push(line.slice(2));
        } else if (items.length) {
          items[items.length - 1] += ` ${line}`;
        }
      }
      for (const item of items) {
        const li = document.createElement("li");
        li.innerHTML = formatDescInline(item);
        list.append(li);
      }
      return list;
    });
    // The first block is the lede and renders above the architecture panel;
    // the rest of the description follows it.
    const lede = $("pattern-description-lede");
    const [first, ...rest] = nodes;
    lede.replaceChildren(...(first ? [first] : []));
    el.replaceChildren(...rest);
    // [[slug|label]] in a description renders as a button that opens the
    // pattern in place.
    [lede, el].forEach((root) =>
      root.querySelectorAll(".pattern-inline-link").forEach((btn) =>
        btn.addEventListener("click", () => selectPattern(btn.dataset.pattern))
      )
    );
  }

  function renderPatternMeta(pattern) {
    const el = $("pattern-status-detail");
    const provenance = document.createElement("span");
    provenance.className = "pattern-provenance";
    provenance.textContent = pattern.location === "workspace" ? "Workspace" : "Curated";
    const status = patternStatusBadge(pattern.status);
    el.replaceChildren(provenance, ...(status ? [status] : []));
    el.hidden = false;
  }

  function renderPatternTags(tags) {
    const el = $("pattern-tags");
    el.replaceChildren();
    if (!tags?.length) {
      el.hidden = true;
      return;
    }
    tags.forEach((tag) => {
      const item = document.createElement("span");
      item.className = "pattern-tag";
      item.textContent = tag;
      el.append(item);
    });
    el.hidden = false;
  }

  function crumbSep() {
    const sep = document.createElement("span");
    sep.className = "crumb-sep";
    sep.setAttribute("aria-hidden", "true");
    sep.textContent = "›";
    return sep;
  }

  function renderBreadcrumb(selected) {
    const nav = $("pattern-breadcrumb");
    const groupKey = patternGroupKey(selected);
    const groupLabel = PATTERN_GROUPS[selected.group]?.label || selected.group;

    const all = document.createElement("button");
    all.type = "button";
    all.className = "crumb-link";
    all.textContent = "All patterns";
    // "All patterns" means unfiltered: reset any group/topology/search filtering.
    all.addEventListener("click", () => {
      $("pattern-search").value = "";
      applyFilters({ group: "all", topology: "all", search: "" }, { home: true });
    });

    // The group is the emphasised crumb, and clicking it returns to the catalog
    // filtered to that group.
    const group = document.createElement("button");
    group.type = "button";
    group.className = "crumb-link crumb-group";
    group.textContent = groupLabel;
    group.addEventListener("click", () => {
      applyFilters({ group: groupKey }, { home: true });
      $("catalog-home")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });

    nav.replaceChildren(all, crumbSep(), group);
  }

  function renderExperimental(selected) {
    const el = $("pattern-experimental");
    if (!selected.experimental) { el.hidden = true; el.replaceChildren(); return; }
    const badge = document.createElement("span");
    badge.className = "experimental-badge";
    badge.textContent = "Experimental";
    const note = document.createElement("span");
    note.className = "experimental-note";
    note.textContent = "Newer pattern, not yet battle-tested; the mechanics may change.";
    el.replaceChildren(badge, note);
    el.hidden = false;
  }

  function renderSuperseded(selected) {
    const el = $("pattern-superseded");
    const target = selected.supersededBy && patterns.find((p) => p.slug === selected.supersededBy);
    if (!target) { el.hidden = true; el.replaceChildren(); return; }
    const lead = document.createElement("span");
    lead.className = "superseded-lead";
    lead.textContent = "Superseded by";
    const link = document.createElement("button");
    link.type = "button";
    link.className = "superseded-link";
    link.textContent = displayTitle(target);
    link.addEventListener("click", () => selectPattern(target.slug));
    const since = document.createElement("span");
    since.className = "superseded-since";
    since.textContent = selected.supersededSince ? `· native in ClickHouse ${selected.supersededSince}+` : "";
    el.replaceChildren(lead, link);
    if (since.textContent) el.append(since);
    el.hidden = false;
  }
  [canvas, modalCanvas].forEach((surface) => {
    surface.addEventListener("mouseover", (event) => {
      const node = event.target.closest?.("[data-note]");
      if (!node) return;
      noteTip.replaceChildren(renderNote(node.dataset.note));
      // A <dialog> opened with showModal() renders in the top layer, above
      // body content; reparent the tip into it so it is visible over the modal.
      (node.closest("dialog") || document.body).appendChild(noteTip);
      noteTip.hidden = false;
      positionNoteTip(event);
    });
    surface.addEventListener("mousemove", (event) => {
      if (noteTip.hidden) return;
      if (event.target.closest?.("[data-note]")) positionNoteTip(event);
      else hideNoteTip();
    });
    surface.addEventListener("mouseout", (event) => {
      if (!event.relatedTarget?.closest?.("[data-note]")) hideNoteTip();
    });
  });
  canvas.addEventListener("keydown", (event) => {
    const resourceKey = event.target.closest?.("[data-resource-key]")?.dataset.resourceKey;
    if (resourceKey && canInspectSelectedPattern() && (event.key === "Enter" || event.key === " ")) {
      event.preventDefault();
      session.openResourceInspector(resourceKey);
      return;
    }
    if (event.key === "+" || event.key === "=") { event.preventDefault(); setDiagramZoom(diagramZoom + ZOOM_STEP); }
    else if (event.key === "-") { event.preventDefault(); setDiagramZoom(diagramZoom - ZOOM_STEP); }
    else if (event.key === "0") { event.preventDefault(); resetDiagramZoom(); }
    else if (event.key === "Enter" || event.key === " ") { event.preventDefault(); openDiagramModal(); }
  });
  // ===================== DIAGRAM MODAL, THEME, EVENT WIRING & BOOT =====================
  function openDiagramModal() {
    if (!canvas.querySelector("svg")) return;
    diagramModal.showModal();
    syncModalDiagram();
    updateViewToggle();
  }
  canvas.addEventListener("click", (event) => {
    const resourceNode = event.target.closest?.(".resource");
    const resourceKey = resourceNode?.dataset.resourceKey;
    if (resourceKey && canInspectSelectedPattern()) { session.openResourceInspector(resourceKey); return; }
    if (resourceNode) return;
    if (event.target.closest?.("svg")) openDiagramModal();
  });
  $("modal-zoom-out").addEventListener("click", () => setModalZoom(modalZoom - ZOOM_STEP));
  $("modal-zoom-reset").addEventListener("click", resetModalZoom);
  $("modal-zoom-in").addEventListener("click", () => setModalZoom(modalZoom + ZOOM_STEP));
  // Esc on a pattern page returns to its group, mirroring the group breadcrumb.
  // Dialogs close themselves on Esc, and a text field's own Esc handling wins.
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !selected) return;
    if (diagramModal.open || resourceInspector.open) return;
    const tag = (event.target?.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select") return;
    event.preventDefault();
    catalogFilters.group = patternGroupKey(selected);
    showCatalogHome();
    $("catalog-home")?.scrollIntoView({ behavior: "smooth", block: "start" });
  });
  $("diagram-modal-close").addEventListener("click", () => diagramModal.close());
  diagramModal.addEventListener("click", (event) => {
    if (event.target === diagramModal) diagramModal.close();
  });
  modalCanvas.addEventListener("click", (event) => {
    const resourceNode = event.target.closest?.(".resource");
    const resourceKey = resourceNode?.dataset.resourceKey;
    if (resourceKey && canInspectSelectedPattern()) session.openResourceInspector(resourceKey);
  });
  modalCanvas.addEventListener("wheel", (event) => {
    if (!modalCanvas.querySelector("svg")) return;
    const unit = event.deltaMode === WheelEvent.DOM_DELTA_LINE ? 16
      : event.deltaMode === WheelEvent.DOM_DELTA_PAGE ? modalCanvas.clientHeight
      : 1;
    const delta = Math.max(-80, Math.min(80, event.deltaY * unit));
    if (!delta || (delta < 0 && modalZoom >= MAX_ZOOM) || (delta > 0 && modalZoom <= MIN_ZOOM)) return;
    event.preventDefault();
    const bounds = modalCanvas.getBoundingClientRect();
    const factor = Math.exp(-delta * 0.0025);
    setModalZoom(modalZoom * factor, event.clientX - bounds.left, event.clientY - bounds.top);
  }, { passive: false });
  modalCanvas.addEventListener("keydown", (event) => {
    const resourceKey = event.target.closest?.("[data-resource-key]")?.dataset.resourceKey;
    if (resourceKey && canInspectSelectedPattern() && (event.key === "Enter" || event.key === " ")) {
      event.preventDefault();
      session.openResourceInspector(resourceKey);
      return;
    }
    if (event.key === "+" || event.key === "=") { event.preventDefault(); setModalZoom(modalZoom + ZOOM_STEP); }
    else if (event.key === "-") { event.preventDefault(); setModalZoom(modalZoom - ZOOM_STEP); }
    else if (event.key === "0") { event.preventDefault(); resetModalZoom(); }
  });
  $("resource-inspector-close").addEventListener("click", () => resourceInspector.close());
  resourceInspector.addEventListener("click", (event) => {
    if (event.target === resourceInspector) resourceInspector.close();
  });
  function downloadDiagramSvg(svg) {
    if (!svg || !selected) return;
    const exportedSvg = svg.cloneNode(true);
    exportedSvg.removeAttribute("style");
    const blob = new Blob([new XMLSerializer().serializeToString(exportedSvg)], { type: "image/svg+xml" });
    const link = document.createElement("a"); link.href = URL.createObjectURL(blob); const suffix = { logical: "", schematic: "-diagram", physical: "-containers" }[architectureView] || "";
    link.download = `${selected.slug}${suffix}.svg`; link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  }
  $("download-svg").addEventListener("click", () => downloadDiagramSvg(canvas.querySelector("svg")));
  $("download-svg-modal")?.addEventListener("click", () =>
    downloadDiagramSvg(modalCanvas.querySelector("svg") || canvas.querySelector("svg")));

  // ---- Theme switcher: flat (default) vs soft, soft in light|dark schemes ----
  // Persisted in localStorage; the inline <head> script restores it pre-paint.
  const themeStore = {
    read() { try { return JSON.parse(localStorage.getItem("pe-theme-v2")) || {}; } catch { return {}; } },
    write(theme, scheme) { try { localStorage.setItem("pe-theme-v2", JSON.stringify({ theme, scheme })); } catch { /* private mode */ } },
  };
  let uiTheme = themeStore.read().theme || "flat";
  let uiScheme = themeStore.read().scheme || "light";
  function applyTheme() {
    document.documentElement.dataset.theme = uiTheme;
    document.documentElement.dataset.scheme = uiScheme;
    themeStore.write(uiTheme, uiScheme);
    document.querySelectorAll(".theme-switch [data-theme-choice]").forEach((button) =>
      button.classList.toggle("active", button.dataset.themeChoice === uiTheme));
    const toggle = document.querySelector(".scheme-toggle");
    if (toggle) {
      toggle.hidden = false;
      toggle.textContent = uiScheme === "dark" ? "☾" : "☀";
      toggle.title = uiScheme === "dark" ? "Switch to light" : "Switch to dark";
    }
    // Diagrams are colored per scheme: re-render the open one and the hero art.
    if (selected) selectPattern(selected.slug, false);

  }
  const themeSwitch = document.createElement("div");
  themeSwitch.className = "theme-switch";
  themeSwitch.innerHTML =
    '<button type="button" data-theme-choice="flat">Flat</button>' +
    '<button type="button" data-theme-choice="soft">Soft</button>' +
    '<button type="button" class="scheme-toggle" aria-label="Toggle light or dark soft theme"></button>' +
    '<a class="repo-link" href="https://github.com/dmkskd/clickhouse-patterns" target="_blank" rel="noopener noreferrer" title="Source on GitHub" aria-label="Source on GitHub">' +
    '<svg viewBox="0 0 16 16" width="13" height="13" fill="currentColor" aria-hidden="true">' +
    '<path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 ' +
    '0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 ' +
    '1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 ' +
    '0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 ' +
    '2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 ' +
    '2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 ' +
    '.21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z"/></svg></a>';
  themeSwitch.addEventListener("click", (event) => {
    const choice = event.target.closest("[data-theme-choice]");
    if (choice) { uiTheme = choice.dataset.themeChoice; applyTheme(); return; }
    if (event.target.closest(".scheme-toggle")) {
      uiScheme = uiScheme === "dark" ? "light" : "dark";
      applyTheme();
    }
  });
  ($("header-tools") || document.body).appendChild(themeSwitch);
  applyTheme();

  // ---- Collapsible sidebar: edge toggle, persisted like the theme ----
  const sidebarToggle = document.createElement("button");
  sidebarToggle.type = "button";
  sidebarToggle.className = "sidebar-toggle";
  sidebarToggle.setAttribute("aria-label", "Hide or show the pattern list");
  let sidebarHidden = false;
  try { sidebarHidden = localStorage.getItem("pe-sidebar") === "hidden"; } catch { /* private mode */ }
  function applySidebar() {
    document.documentElement.dataset.sidebar = sidebarHidden ? "hidden" : "shown";
    sidebarToggle.textContent = sidebarHidden ? "»" : "«";
    sidebarToggle.title = sidebarHidden ? "Show pattern list" : "Hide pattern list";
    try { localStorage.setItem("pe-sidebar", sidebarHidden ? "hidden" : "shown"); } catch { /* private mode */ }
  }
  sidebarToggle.addEventListener("click", () => { sidebarHidden = !sidebarHidden; applySidebar(); });
  document.body.appendChild(sidebarToggle);
  applySidebar();

  // The session / control-plane layer (session.js) owns everything that needs a
  // local server. It reads app state through these accessors and calls back into
  // routing/catalog rendering; app.js keeps `selected`/`control` and the routing.
  const session = window.PE.session.create({
    getSelected: () => selected,
    getControl: () => control,
    setControl: (next) => { control = next; },
    selectPattern,
    renderList: renderSidebar,
    renderCatalogHome,
    canInspect: canInspectSelectedPattern,
    syncArchitecture,
    patterns,
    patternGroups: PATTERN_GROUPS,
  });

  const route = readRoute();
  search.value = route.search;
  renderSidebar();
  if (route.pattern) selectPattern(route.pattern, false);
  else showCatalogHome(false);
  session.connectControlPlane();
})();
