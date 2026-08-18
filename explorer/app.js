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
    const key = pattern.group || `${pattern.category}-${pattern.flow}`;
    return { key, label: key, title: key, description: "Related patterns", icon: "database", intro: "", related: [] };
  }
  const sortKey = (p) =>
    `${String(GROUP_ORDER[p.group] ?? 999).padStart(5, "0")}/${String(p.order ?? 1000).padStart(5, "0")}/${p.title}`;
  const patterns = [...catalog.patterns].sort((a, b) => sortKey(a).localeCompare(sortKey(b)));
  const $ = (id) => document.getElementById(id);
  const list = $("pattern-list");
  const search = $("pattern-search");
  const canvas = $("architecture-canvas");
  const diagramModal = $("diagram-modal");
  const modalCanvas = $("diagram-modal-canvas");
  const resourceInspector = $("resource-inspector");
  const resourceInspectorBody = $("resource-inspector-body");
  const toggleGroups = $("toggle-groups");
  let selected = null;
  let catalogFilters = { group: "all", topology: "all", search: "" };
  let diagramZoom = 1;
  let modalZoom = 1;
  let architectureView = "logical";   // "logical" (resource flow) | "physical" (containers)
  let topologyRequest = 0;            // guards against out-of-order topology responses
  const groupState = new Map();
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
      pattern.slug, pattern.title, pattern.description, pattern.category,
      pattern.flow, pattern.topology, ...(pattern.tags || [])
    ].join(" ").toLowerCase();
    return (!catalogFilters.search || haystack.includes(catalogFilters.search))
      && (catalogFilters.group === "all" || patternGroupKey(pattern) === catalogFilters.group)
      && (catalogFilters.topology === "all" || pattern.topology === catalogFilters.topology);
  }

  function catalogFilterButton(value, label, count, type) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = catalogFilters[type] === value ? "active" : "";
    button.dataset.value = value;
    button.setAttribute("aria-pressed", String(catalogFilters[type] === value));
    button.innerHTML = `<span>${esc(label)}</span><small>${count}</small>`;
    button.addEventListener("click", () => {
      catalogFilters[type] = value;
      renderCatalogHome();
    });
    return button;
  }

  // ===================== CATALOG (filters, cards, groups, list) =====================
  function renderCatalogFilters() {
    const groups = [["all", "All groups"], ...GROUPS.map((group) => [group.key, group.label])];
    const groupFilters = $("catalog-group-filters");
    groupFilters.replaceChildren(...groups.map(([value, label]) =>
      catalogFilterButton(value, label, value === "all" ? patterns.length : patterns.filter((item) => patternGroupKey(item) === value).length, "group")
    ));

    const topologies = [["all", "Any topology"], ...Object.entries(TOPOLOGIES).map(([value, info]) => [value, info.label])];
    const topologyFilters = $("catalog-topology-filters");
    topologyFilters.replaceChildren(...topologies.map(([value, label]) =>
      catalogFilterButton(value, label, value === "all" ? patterns.length : patterns.filter((item) => item.topology === value).length, "topology")
    ));
  }

  function patternCard(pattern) {
    const [key, info] = patternGroup(pattern);
    const topology = TOPOLOGIES[pattern.topology] || { label: pattern.topology, help: pattern.topology };
    const activeSession = control.snapshot?.session;
    const running = activeSession?.slug === pattern.slug;
    const card = document.createElement("button");
    card.type = "button";
    card.className = `catalog-card${pattern.graph ? "" : " pending"}${running ? " running" : ""}`;
    card.addEventListener("click", () => selectPattern(pattern.slug));

    const header = document.createElement("span");
    header.className = "catalog-card-header";
    const mark = document.createElement("span");
    mark.className = `pattern-group-mark ${key}`;
    mark.innerHTML = patternGroupIcon(info.icon);
    const context = document.createElement("span");
    context.className = "catalog-card-context";
    context.innerHTML = `<span>${esc(info.title)}</span><small>${pattern.location === "workspace" ? "Workspace" : "Curated"}</small>`;
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
    header.append(mark, context, badges);

    const title = document.createElement("strong");
    title.className = "catalog-card-title";
    title.textContent = displayTitle(pattern);
    const description = document.createElement("span");
    description.className = "catalog-card-description";
    description.textContent = plainDesc(pattern.description);

    const tags = document.createElement("span");
    tags.className = "catalog-card-tags";
    const visibleTags = (pattern.tags || []).slice(0, 4);
    visibleTags.forEach((tag) => {
      const item = document.createElement("span");
      item.textContent = tag;
      tags.append(item);
    });
    const hiddenTagCount = (pattern.tags || []).length - visibleTags.length;
    if (hiddenTagCount > 0) {
      const more = document.createElement("span");
      more.className = "more";
      more.textContent = "+" + hiddenTagCount;
      more.title = hiddenTagCount + " more tags";
      tags.append(more);
    }

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
    card.append(header, title, description, tags, footer);
    return card;
  }

  function renderHeroArt() {
    // Decorative background: render the richest real pattern diagram once and
    // embed it as an isolated data-URI background (no id clashes, no motion).
    const art = $("catalog-hero-art");
    if (!art || art.dataset.rendered) return;
    const richest = patterns
      .filter((pattern) => pattern.graph)
      .sort((a, b) => b.graph.connections.length - a.graph.connections.length)[0];
    if (!richest) return;
    art.style.backgroundImage = `url("data:image/svg+xml,${encodeURIComponent(PE.diagram.render(richest, { inspectable: false }))}")`;
    art.dataset.rendered = "1";
  }

  function groupCard(key, items, info) {
    const card = document.createElement("div");
    card.className = "group-card";
    card.tabIndex = 0;
    card.setAttribute("role", "button");
    const allTags = [...new Set(items.flatMap((pattern) => pattern.tags || []))];
    const visibleTags = allTags.slice(0, 5);
    const hiddenTagCount = allTags.length - visibleTags.length;
    const chips = visibleTags.map((tag) => `<span class="group-intro-tag">${esc(tag)}</span>`).join("")
      + (hiddenTagCount > 0
        ? `<span class="group-intro-tag more" title="${hiddenTagCount} more tags">+ more</span>`
        : "");
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
      `<div class="group-card-head">${patternGroupIcon(info.icon)}` +
      `<div class="group-card-titles"><strong>${esc(info.title)}</strong>` +
      `<div class="group-card-meta"><span class="group-card-count">${items.length} ${items.length === 1 ? "pattern" : "patterns"}</span>${groupStatusRollup(items)}</div></div></div>` +
      (summary ? `<p class="group-card-intro">${esc(summary)}</p>` : "") +
      (chips ? `<div class="group-intro-tags">${chips}</div>` : "");
    const openGroup = () => { catalogFilters.group = key; renderCatalogHome(); };
    card.addEventListener("click", openGroup);
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); openGroup(); }
    });
    return card;
  }

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

  function renderGroupAdvisories(advisories) {
    return (advisories || []).map((advisory) => {
      const title = esc(advisory.title || "Notice");
      const summary = esc(advisory.summary || "");
      const body = advisory.body ? `<p>${renderIntro(advisory.body)}</p>` : "";
      const externalLink = advisory.link
        ? `<a href="${esc(advisory.link)}" target="_blank" rel="noopener noreferrer">${esc(advisory.link_label || "Read more")}</a>`
        : "";
      const patternLink = advisory.link_pattern
        ? `<button type="button" class="group-advisory-link" data-pattern="${esc(advisory.link_pattern)}">${esc(advisory.link_label || "Read more")}</button>`
        : "";
      return `<details class="group-advisory">` +
        `<summary><span>Notice</span><strong>${title}</strong>${summary ? `<em>${summary}</em>` : ""}</summary>` +
        `<div class="group-advisory-body">${body}${externalLink}${patternLink}</div>` +
        `</details>`;
    }).join("");
  }

  function groupHeader(info, items) {
    const header = document.createElement("section");
    header.className = "catalog-group-intro";
    const paras = (info.intro || info.description || "").split(/\n{2,}/).map((s) => s.trim()).filter(Boolean);
    const related = (info.related || []).map((link) => {
      const target = PATTERN_GROUPS[link.group];
      if (!target) return "";
      return `<li>${esc(link.note)} <button type="button" class="group-link" data-group="${esc(link.group)}">${esc(target.title)}</button></li>`;
    }).join("");
    const advisories = renderGroupAdvisories(info.advisories);
    // First paragraph reads full width as a lead; the rest flow into two columns
    // so the summary uses the horizontal space instead of leaving it empty.
    const [lead, ...rest] = paras;
    header.innerHTML =
      `<div class="group-intro-head"><h3>${esc(info.title)}</h3>` +
      `<span class="group-intro-count">${items.length} ${items.length === 1 ? "pattern" : "patterns"}${groupStatusRollup(items)}</span>` +
      `</div>` +
      (lead ? `<p class="group-intro-lead">${renderIntro(lead)}</p>` : "") +
      (rest.length ? `<div class="group-intro-body">${renderIntroBody(rest)}</div>` : "") +
      advisories +
      (related ? `<div class="group-related"><span>Related</span><ul>${related}</ul></div>` : "");
    header.querySelectorAll(".group-link").forEach((btn) => btn.addEventListener("click", () => {
      catalogFilters.group = btn.dataset.group;
      renderCatalogHome();
      $("catalog-home")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }));
    header.querySelectorAll(".group-advisory-link").forEach((btn) => btn.addEventListener("click", () => {
      selectPattern(btn.dataset.pattern);
    }));
    return header;
  }

  function renderCatalogHome() {
    renderHeroArt();
    renderCatalogFilters();
    const visible = patterns.filter(matchesCatalogFilters);
    $("catalog-results-summary").textContent = `${visible.length} ${visible.length === 1 ? "pattern" : "patterns"}`;
    const grid = $("catalog-grid");
    if (!visible.length) {
      grid.classList.remove("as-groups");
      grid.innerHTML = '<div class="catalog-empty"><strong>No matching patterns</strong><span>Try another search term or clear a filter.</span><button type="button">Clear filters</button></div>';
      grid.querySelector(".catalog-empty button")?.addEventListener("click", () => {
        catalogFilters = { group: "all", topology: "all", search: "" };
        $("catalog-search").value = "";
        renderCatalogHome();
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
      grid.classList.add("as-groups");
      grid.replaceChildren(...[...byGroup].map(([key, items]) =>
        groupCard(key, items, PATTERN_GROUPS[key] || patternGroup(items[0])[1])));
      return;
    }
    // Drill-in: the family's fuller intro, related links, then its pattern cards.
    grid.classList.remove("as-groups");
    const [groupKey, groupItems] = [...byGroup][0];
    const info = PATTERN_GROUPS[groupKey] || patternGroup(groupItems[0])[1];
    grid.replaceChildren(groupHeader(info, groupItems), ...groupItems.map(patternCard));
  }

  function renderList(filter = "") {
    const needle = filter.trim().toLowerCase();
    const visible = patterns.filter((pattern) =>
      [pattern.slug, pattern.title, pattern.description, pattern.category, pattern.flow, pattern.topology, ...(pattern.tags || [])]
        .join(" ").toLowerCase().includes(needle)
    );
    list.replaceChildren();
    const groups = new Map();
    visible.forEach((pattern) => {
      const key = patternGroupKey(pattern);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(pattern);
    });
    groups.forEach((items, key) => {
      const section = document.createElement("details");
      section.className = "pattern-group";
      section.dataset.group = key;
      // Always reveal the group of the pattern currently open, however it was
      // opened (catalog grid, hero, direct link), not just when the user expanded
      // it by hand. It is also marked current for a subtle highlight.
      const isCurrent = Boolean(selected) && key === patternGroupKey(selected);
      if (isCurrent) section.classList.add("current");
      section.open = needle ? true : (isCurrent || (groupState.get(key) ?? false));
      section.addEventListener("toggle", () => {
        if (!needle) groupState.set(key, section.open);
        updateGroupToggle();
      });
      const info = patternGroup(items[0])[1];
      const summary = document.createElement("summary");
      summary.className = "pattern-group-heading";
      const icon = document.createElement("span");
      icon.className = `pattern-group-mark ${key}`;
      icon.innerHTML = patternGroupIcon(info.icon);
      const copy = document.createElement("span");
      copy.className = "pattern-group-copy";
      const groupTitle = document.createElement("strong");
      groupTitle.textContent = info.title;
      const description = document.createElement("span");
      description.textContent = info.description;
      copy.append(groupTitle, description);
      const count = document.createElement("span");
      count.className = "pattern-count";
      count.textContent = String(items.length);
      summary.append(icon, copy, count);
      const options = document.createElement("div");
      options.className = "pattern-options";
      items.forEach((pattern) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = `pattern-option${pattern.slug === selected?.slug ? " active" : ""}${pattern.graph ? "" : " pending"}`;
        button.title = pattern.slug;
        const row = document.createElement("span");
        row.className = "pattern-option-row";
        const strong = document.createElement("strong");
        strong.textContent = displayTitle(pattern);
        const topology = TOPOLOGIES[pattern.topology] || { label: pattern.topology, help: pattern.topology };
        const badge = document.createElement("span");
        badge.className = `topology-badge ${pattern.topology}`;
        badge.textContent = topology.label;
        badge.title = topology.help;
        const badges = document.createElement("span");
        badges.className = "pattern-badges";
        const direction = directionBadge(pattern);
        if (direction) badges.append(direction);
        badges.append(badge);
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
        options.append(button);
      });
      section.append(summary, options);
      list.append(section);
    });
    updateGroupToggle();
  }

  function updateGroupToggle() {
    const groups = [...list.querySelectorAll(".pattern-group")];
    const allOpen = groups.length > 0 && groups.every((group) => group.open);
    const label = allOpen ? "Collapse all" : "Expand all";
    toggleGroups.dataset.action = allOpen ? "collapse" : "expand";
    toggleGroups.querySelector("[aria-hidden]").textContent = allOpen ? "⊟" : "⊞";
    toggleGroups.querySelector(".group-toggle-label").textContent = label;
    toggleGroups.setAttribute("aria-label", `${label} pattern groups`);
    toggleGroups.disabled = groups.length === 0;
  }

  function setAllGroups(open) {
    list.querySelectorAll(".pattern-group").forEach((group) => {
      group.open = open;
      groupState.set(group.dataset.group, open);
    });
    updateGroupToggle();
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
  // plus any ClickHouse configuration fragments the pattern mounts.
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

  function showDefinition(pattern, key) {
    const def = pattern.definition || {};
    const body = $("definition-body");
    const buttons = [...document.querySelectorAll("#definition-tabs button")];
    // Clicking the open tab collapses the strip back to just the tabs.
    const alreadyOpen = buttons.some((b) => b.dataset.def === key && b.classList.contains("active"));
    buttons.forEach((b) => b.classList.toggle("active", !alreadyOpen && b.dataset.def === key));
    if (alreadyOpen) { body.hidden = true; body.innerHTML = ""; $("definition-strip").hidden = true; return; }
    $("definition-strip").hidden = false;
    body.hidden = false;
    if (key === "verify") {
      const v = def.verify;
      body.className = "definition-body verify";
      body.innerHTML = codeBlock(v.sqlFile, v.sql, "sql")
        + (v.expected != null ? codeBlock(v.expectedFile, v.expected, "text") : "");
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
  }

  function renderDefinition(pattern) {
    const def = pattern.definition || {};
    const tabs = [["manifest", "Definition", def.manifest], ["structure", "Structure", def.structure], ["load", "Loader", def.load], ["verify", "Verification", def.verify], ["config", "Configuration", def.config]]
      .filter(([, , data]) => data);
    $("definition-tabs").replaceChildren(...tabs.map(([key, label]) => {
      const b = document.createElement("button");
      b.type = "button"; b.dataset.def = key; b.textContent = label;
      b.addEventListener("click", () => showDefinition(pattern, key));
      return b;
    }));
    // Collapsed by default: tabs are shown, but no file is loaded until one is
    // clicked, so the strip holding the file body starts hidden.
    const body = $("definition-body");
    body.hidden = true;
    body.innerHTML = "";
    $("definition-strip").hidden = true;
    // The bottom row hides only when neither side has content (static mode and
    // no definition files); session.js applies the same rule on its renders.
    $("control-strip").hidden = $("session-panel").hidden && !tabs.length;
  }

  function updateZoomControl(hasDiagram = Boolean(canvas.querySelector("svg"))) {
    const percent = Math.round(diagramZoom * 100);
    $("zoom-reset").textContent = `${percent}%`;
    $("zoom-reset").disabled = !hasDiagram;
    $("zoom-out").disabled = !hasDiagram || diagramZoom <= MIN_ZOOM;
    $("zoom-in").disabled = !hasDiagram || diagramZoom >= MAX_ZOOM;
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
    updateZoomControl(Boolean(svg));
  }

  function resetModalZoom() {
    modalZoom = 1;
    modalCanvas.scrollTo({ left: 0, top: 0 });
    const svg = modalCanvas.querySelector("svg");
    if (svg) { svg.style.width = "100%"; svg.style.marginInline = "0"; }
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
  function updateViewToggle() {
    const physical = architectureView === "physical";
    const available = physicalAvailable();
    // The switch appears only where both views exist: a pattern that is not
    // running has no containers to draw, so a disabled button would be noise.
    [["architecture-view", "view-logical", "view-physical", "flow-legend"],
     ["modal-architecture-view", "modal-view-logical", "modal-view-physical", "modal-flow-legend"]]
      .forEach(([group, logicalId, physicalId, legendId]) => {
        const container = $(group);
        if (!container) return;
        container.hidden = !available;
        $(logicalId).classList.toggle("active", !physical);
        $(physicalId).classList.toggle("active", physical);
        $(logicalId).setAttribute("aria-pressed", String(!physical));
        $(physicalId).setAttribute("aria-pressed", String(physical));
        if ($(legendId)) $(legendId).hidden = physical;
      });
    $("architecture-title").textContent = physical ? "Container topology" : "Resource flow";
    if (diagramModal.open) $("diagram-modal-title").textContent = modalTitle();
  }

  function modalTitle() {
    if (!selected) return "Resource flow";
    return architectureView === "physical" ? `${selected.title} · containers` : selected.title;
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
    if (selected?.graph) canvas.innerHTML = PE.diagram.render(selected, { inspectable: canInspectSelectedPattern() });
    else canvas.innerHTML = canvasMessage("Architecture pending", "This pattern has not declared a compact resource graph yet.");
    resetDiagramZoom();
    $("download-svg").disabled = !selected?.graph;
    syncModalDiagram();
  }

  function setArchitectureView(view) {
    if (view === "physical" && !physicalAvailable()) return;
    if (view === architectureView) return;
    architectureView = view;
    renderArchitecture();
  }

  // Called by session.js after every control-plane refresh. Polling is frequent
  // and re-rendering resets zoom, so redraw the physical view only when the
  // session state it depicts actually moved; otherwise refresh only the toggle.
  let lastSessionSignature = null;
  function syncArchitecture() {
    if (!selected || $("pattern-detail").hidden) return;
    if (architectureView === "physical" && !physicalAvailable()) {
      architectureView = "logical";
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

  $("view-logical").addEventListener("click", () => setArchitectureView("logical"));
  $("view-physical").addEventListener("click", () => setArchitectureView("physical"));
  $("modal-view-logical").addEventListener("click", () => setArchitectureView("logical"));
  $("modal-view-physical").addEventListener("click", () => setArchitectureView("physical"));

  // ===================== DIAGRAM PLACEMENT & COLLAPSE =====================
  // Both are browser-local viewer preferences (localStorage), not per-pattern
  // settings: the reader keeps the diagram where they like it. The panel is a
  // single self-contained section, so placement is one insertBefore move.
  const DIAGRAM_PLACE_KEY = "pe.diagramPlacement";
  const DIAGRAM_COLLAPSE_KEY = "pe.diagramCollapsed";
  const architecturePanel = document.querySelector(".architecture-panel");
  // The two locations the page layout has used: after the lede (current) and
  // below the whole description and its links (previous).
  const DIAGRAM_PLACES = ["middle", "bottom"];

  function applyDiagramPlacement(place, persist = true) {
    const lede = $("pattern-description-lede");
    architecturePanel.classList.toggle("diagram-bottom", place === "bottom");
    if (place === "bottom") $("pattern-related").after(architecturePanel);
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
    applyDiagramPlacement(DIAGRAM_PLACES.includes(savedPlace) ? savedPlace : "middle", false);
    applyDiagramCollapsed(localStorage.getItem(DIAGRAM_COLLAPSE_KEY) === "1", false);
  } catch (_error) {
    applyDiagramPlacement("middle", false);
  }

  // ===================== ROUTING & PATTERN SELECTION (detail view) =====================
  function updateRoute(slug, replace = false) {
    const url = new URL(window.location.href);
    if (slug) url.searchParams.set("pattern", slug);
    else url.searchParams.delete("pattern");
    const method = replace ? "replaceState" : "pushState";
    history[method]({}, "", url);
  }

  function showCatalogHome(updateUrl = true) {
    if (resourceInspector.open) resourceInspector.close();
    if (diagramModal.open) diagramModal.close();
    selected = null;
    document.querySelector(".app-shell").classList.add("home-view");
    $("catalog-home").hidden = false;
    $("pattern-detail").hidden = true;
    document.title = "ClickHouse Pattern Explorer";
    if (updateUrl) updateRoute(null);
    renderCatalogHome();
    renderList(search.value);
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
    references.replaceChildren(...(selected.references || []).map((reference) => {
      const link = document.createElement("a");
      link.href = reference.url;
      link.target = "_blank";
      link.rel = "noreferrer";
      link.textContent = reference.label;
      return link;
    }));
    references.hidden = !selected.references?.length;
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
    document.title = `${selected.title} — Pattern Explorer`;
    renderTradeoffs(selected);
    renderDefinition(selected);
    const flows = selected.graph?.flows || [];
    const legendHtml = flows.map((flow) => `<span><i style="background:${FLOW_COLORS[flow] || "#8b93ad"}"></i>${esc(flow)}</span>`).join("");
    $("flow-legend").innerHTML = legendHtml;
    const modalLegend = $("modal-flow-legend");
    if (modalLegend) modalLegend.innerHTML = legendHtml;
    // Each pattern opens on its logical diagram; the physical one is a
    // deliberate, server-backed step down into the container wiring.
    architectureView = "logical";
    renderArchitecture();
    if (updateUrl) updateRoute(selected.slug);
    renderList(search.value);
    session.renderSession();
    window.scrollTo(0, 0);
  }

  search.addEventListener("input", () => renderList(search.value));
  $("catalog-search").addEventListener("input", (event) => {
    catalogFilters.search = event.target.value.trim().toLowerCase();
    renderCatalogHome();
  });
  $("show-catalog-home").addEventListener("click", () => showCatalogHome());
  // "Read more" expands and hides itself; the collapse control ("Read less")
  // sits at the bottom of the expanded text, where reading ends.
  const setWhyExpanded = (open) => {
    const more = $("why-more");
    if (!more) return;
    more.hidden = !open;
    $("why-open").hidden = open;
    $("why-open").setAttribute("aria-expanded", String(open));
  };
  $("why-open")?.addEventListener("click", () => setWhyExpanded(true));
  $("why-less")?.addEventListener("click", () => setWhyExpanded(false));
  $("clone-pattern")?.addEventListener("click", () => $("clone-modal").showModal());
  $("clone-modal-close")?.addEventListener("click", () => $("clone-modal").close());
  $("clone-modal")?.addEventListener("click", (event) => {
    if (event.target === $("clone-modal")) $("clone-modal").close();
  });
  window.addEventListener("popstate", () => {
    const slug = new URL(window.location.href).searchParams.get("pattern");
    if (slug) selectPattern(slug, false);
    else showCatalogHome(false);
  });
  toggleGroups.addEventListener("click", () => setAllGroups(toggleGroups.dataset.action === "expand"));
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
    // [[slug|label]] in a description renders as a button, wired the same way
    // as a group advisory link so it opens the pattern in place.
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
    const groupLabel = PATTERN_GROUPS[selected.group]?.label || selected.category;

    const all = document.createElement("button");
    all.type = "button";
    all.className = "crumb-link";
    all.textContent = "All patterns";
    // "All patterns" means unfiltered: reset any group/topology/search filtering.
    all.addEventListener("click", () => {
      catalogFilters = { group: "all", topology: "all", search: "" };
      const searchInput = $("catalog-search");
      if (searchInput) searchInput.value = "";
      showCatalogHome();
    });

    // The group is the emphasised crumb, and clicking it returns to the catalog
    // filtered to that group.
    const group = document.createElement("button");
    group.type = "button";
    group.className = "crumb-link crumb-group";
    group.textContent = groupLabel;
    group.addEventListener("click", () => {
      catalogFilters.group = groupKey;
      showCatalogHome();
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
    const link = document.createElement("a"); link.href = URL.createObjectURL(blob); link.download = `${selected.slug}.svg`; link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  }
  $("download-svg").addEventListener("click", () => downloadDiagramSvg(canvas.querySelector("svg")));
  $("download-svg-modal")?.addEventListener("click", () =>
    downloadDiagramSvg(modalCanvas.querySelector("svg") || canvas.querySelector("svg")));

  // ---- Theme switcher: flat (default) vs soft, soft in light|dark schemes ----
  // Persisted in localStorage; the inline <head> script restores it pre-paint.
  const themeStore = {
    read() { try { return JSON.parse(localStorage.getItem("pe-theme")) || {}; } catch { return {}; } },
    write(theme, scheme) { try { localStorage.setItem("pe-theme", JSON.stringify({ theme, scheme })); } catch { /* private mode */ } },
  };
  let uiTheme = themeStore.read().theme || "soft";
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
    const art = $("catalog-hero-art");
    if (art && art.dataset.rendered) { delete art.dataset.rendered; renderHeroArt(); }
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
  document.body.appendChild(themeSwitch);
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
    renderList: () => renderList(search.value),
    renderCatalogHome,
    canInspect: canInspectSelectedPattern,
    syncArchitecture,
    patterns,
    patternGroups: PATTERN_GROUPS,
  });

  const requested = new URL(window.location.href).searchParams.get("pattern");
  renderList();
  if (requested) selectPattern(requested, false);
  else showCatalogHome(false);
  session.connectControlPlane();
})();
