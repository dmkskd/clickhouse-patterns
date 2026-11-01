// Catalog views: the home and group pages (filters, cards, group intro,
// guide, footer) and the sidebar rail with the open pattern's section nav.
// app.js owns the filters and the selection and passes them in as accessors.
window.PE = window.PE || {};
window.PE.catalogView = (() => {
  "use strict";
  const {
    esc, TOPOLOGIES, DIRECTIONS, displayTitle, directionOf, plainDesc, patternGroupIcon
  } = window.PE.util;
  const {
    GROUPS, PATTERN_GROUPS, patterns, patternGroup, patternGroupKey, patternStatusBadge
  } = window.PE.catalog;
  const $ = (id) => document.getElementById(id);

  function create(deps) {
    // deps: getSelected(), getFilters(), getControl(), applyFilters(patch, options),
    //       openPattern(slug), showHome(), guide
    function directionBadge(pattern) {
      const dir = directionOf(pattern);
      if (!dir) return null;
      const badge = document.createElement("span");
      badge.className = `direction-badge ${dir}`;
      badge.textContent = DIRECTIONS[dir].label;
      badge.title = DIRECTIONS[dir].help;
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
      const needle = deps.getFilters().search.trim().toLowerCase();
      return (!needle || haystack.includes(needle))
        && (deps.getFilters().group === "all" || patternGroupKey(pattern) === deps.getFilters().group)
        && (deps.getFilters().topology === "all" || pattern.topology === deps.getFilters().topology);
    }

    const anyFilterSet = () =>
      deps.getFilters().group !== "all" || deps.getFilters().topology !== "all" || deps.getFilters().search.trim() !== "";

    function catalogFilterButton(value, label, count, type) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = deps.getFilters()[type] === value ? "active" : "";
      button.dataset.value = value;
      button.setAttribute("aria-pressed", String(deps.getFilters()[type] === value));
      button.innerHTML = `<span>${esc(label)}</span><small>${count}</small>`;
      button.addEventListener("click", () => deps.applyFilters({ [type]: value }));
      return button;
    }

    // ===================== CATALOG (filters, cards, groups, list) =====================
    // The group axis moved to the sidebar rail, so the catalog's own filter row
    // holds the topology axis and a reset for whatever is currently narrowing
    // the results — group, topology or search.
    function renderCatalogFilters() {
      const needle = deps.getFilters().search.trim().toLowerCase();
      const inScope = (item) =>
        (deps.getFilters().group === "all" || patternGroupKey(item) === deps.getFilters().group)
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
        clear.addEventListener("click", deps.showHome);
        buttons.push(clear);
      }
      topologyFilters.replaceChildren(...buttons);
    }

    function patternCard(pattern, { showGroup = true } = {}) {
      const [key, info] = patternGroup(pattern);
      const topology = TOPOLOGIES[pattern.topology] || { label: pattern.topology, help: pattern.topology };
      const activeSession = deps.getControl().snapshot?.session;
      const running = activeSession?.slug === pattern.slug;
      const card = document.createElement("button");
      card.type = "button";
      card.className = `catalog-card${pattern.graph ? "" : " pending"}${running ? " running" : ""}`;
      card.addEventListener("click", () => deps.openPattern(pattern.slug));

      const header = document.createElement("span");
      // Without the group mark the header is two columns, not three, or the
      // badges end up in the middle column instead of against the right edge.
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
      const openGroup = () => deps.applyFilters({ group: key });
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

    // The home page is described like a group, so the same title / lede /
    // intro rendering covers both and the two pages cannot drift apart.
    const HOME_GROUP = {
      key: "all",
      title: "All patterns",
      description: "In ClickHouse, architecting data pipelines is as challenging as data modelling and query design.",
      intro: "These patterns are end-to-end examples of ingestion, retention, and replication designs in ClickHouse, each with its benefits and limitations.\n\n"
        + "Patterns can be run locally to see how each architecture behaves in practice, then cloned and edited to validate a new idea or a planned refactoring.\n\n"
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
        (info.notice ? `<aside class="group-notice" role="note">${renderIntro(info.notice)}</aside>` : "") +
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
      const preview = slot.querySelector(".group-intro-preview");
      attachShowMore(preview, info.key);
      // The repository link is the page's call to action, so it stays outside the
      // collapsible preview instead of hiding behind Show more.
      slot.querySelectorAll(".group-intro-preview p.group-intro-action").forEach((para) => slot.append(para));
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
        deps.applyFilters({ group: btn.dataset.group });
        $("catalog-home")?.scrollIntoView({ behavior: "smooth", block: "start" });
      }));
      return footer;
    }

    function renderCatalogHome() {
      renderCatalogFilters();
      const visible = patterns.filter(matchesCatalogFilters);
      const query = deps.getFilters().search.trim();
      const group = deps.getFilters().group === "all" ? HOME_GROUP : PATTERN_GROUPS[deps.getFilters().group];
      // The page heading is the thing being read: the group's title on a group
      // page, the home question on the home page, the query when searching.
      const lede = $("catalog-browser-lede");
      const title = $("catalog-browser-title");
      title.textContent = query ? `Results for “${query}”` : group ? group.title : "";
      title.hidden = !title.textContent;
      lede.textContent = !query && group ? group.description || "" : "";
      lede.hidden = !lede.textContent;
      renderGroupIntro(query ? null : group);
      deps.guide.render(query ? null : group);
      const hasGuide = Boolean(!query && group?.guide);
      $("catalog-patterns-heading").hidden = !hasGuide;
      $("catalog-patterns").classList.toggle("guide-patterns", hasGuide);
      $("catalog-results-summary").textContent = `${visible.length} ${visible.length === 1 ? "pattern" : "patterns"}`;
      const grid = $("catalog-grid");
      if (!visible.length) {
        grid.classList.remove("as-groups");
        renderGroupIntro(null);
        deps.guide.render(null);
        grid.innerHTML = '<div class="catalog-empty"><strong>No matching patterns</strong><span>Try another search term or clear a filter.</span><button type="button">Clear filters</button></div>';
        grid.querySelector(".catalog-empty button")?.addEventListener("click", () => {
          $("pattern-search").value = "";
          deps.applyFilters({ group: "all", topology: "all", search: "" });
        });
        return;
      }
      const byGroup = new Map();
      visible.forEach((pattern) => {
        const key = patternGroupKey(pattern);
        if (!byGroup.has(key)) byGroup.set(key, []);
        byGroup.get(key).push(pattern);
      });
      if (deps.getFilters().group === "all") {
        // Home: give the space to the groups. One tile per family, its
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
      button.className = `pattern-option${pattern.slug === deps.getSelected()?.slug ? " active" : ""}${pattern.graph ? "" : " pending"}`;
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
      const activeSession = deps.getControl().snapshot?.session;
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
      button.addEventListener("click", () => deps.openPattern(pattern.slug));
      return button;
    }

    function renderSidebar() {
      const nav = $("group-nav");
      if (!nav) return;
      const needle = deps.getFilters().search.trim().toLowerCase();
      const matches = (pattern) =>
        [pattern.slug, pattern.title, pattern.description, pattern.topology, ...(pattern.tags || [])]
          .join(" ").toLowerCase().includes(needle);
      const visible = patterns.filter(matches);
      const active = deps.getSelected() ? patternGroupKey(deps.getSelected()) : deps.getFilters().group;

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

      const rows = [heading, link("all", "All patterns", patterns.length, deps.showHome,
        !deps.getSelected() && active === "all" && !needle)];

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
          () => deps.applyFilters({ group: group.key }, { home: true }), group.key === active));
        if (unfold) {
          const options = document.createElement("div");
          options.className = "pattern-options";
          items.forEach((pattern) => {
            options.append(patternOption(pattern));
            if (pattern.slug === deps.getSelected()?.slug) options.append(sectionNav());
          });
          item.append(options);
        }
        rows.push(item);
      });
      nav.replaceChildren(...rows);
      renderSectionNav();
    }

    // The open pattern lists its sections under its sidebar entry. The list is
    // read from the live page, because the diagram placement toggle reorders it
    // and the description's own "### " headings differ per pattern.
    function sectionNav() {
      const list = document.createElement("nav");
      list.id = "pattern-sections";
      list.className = "pattern-sections";
      list.setAttribute("aria-label", "Sections");
      return list;
    }

    function sectionTargets() {
      if (!deps.getSelected() || $("pattern-detail").hidden) return [];
      const targets = [
        [document.querySelector(".architecture-panel"), "Architecture"],
        ...[...$("pattern-description").querySelectorAll(".pattern-description-heading")]
          .map((heading) => [heading, heading.textContent]),
        [$("tradeoffs"), "Trade-offs"],
        [$("pattern-links"), "References"],
      ].filter(([element]) => element && !element.hidden);
      return targets.sort(([a], [b]) =>
        a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1);
    }

    function renderSectionNav() {
      const list = $("pattern-sections");
      if (!list) return;
      list.replaceChildren(...sectionTargets().map(([element, label]) => {
        const button = document.createElement("button");
        button.type = "button";
        // Subsections are indented under their section.
        button.className = `pattern-section-link${element.classList.contains("sub") ? " sub" : ""}`;
        button.textContent = label;
        button.addEventListener("click", () => {
          // A heading inside a closed fold has no position until the fold opens.
          element.closest("details")?.setAttribute("open", "");
          element.scrollIntoView({ behavior: "smooth", block: "start" });
        });
        button.sectionTarget = element;
        return button;
      }));
      markCurrentSection();
    }

    // The current section is the last one whose top has passed below the
    // sticky header.
    function markCurrentSection() {
      const links = [...($("pattern-sections")?.children || [])];
      if (!links.length) return;
      const line = 140;
      let current = links[0];
      links.forEach((link) => {
        if (link.sectionTarget.getBoundingClientRect().top <= line) current = link;
      });
      if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2) current = links[links.length - 1];
      links.forEach((link) => link.classList.toggle("active", link === current));
    }

    let sectionFrame = 0;
    window.addEventListener("scroll", () => {
      if (sectionFrame) return;
      sectionFrame = requestAnimationFrame(() => { sectionFrame = 0; markCurrentSection(); });
    }, { passive: true });

    const heroProse = $("catalog-hero-prose");
    if (heroProse) attachShowMore(heroProse, "catalog-hero");

    return { renderCatalogHome, renderSidebar, refreshSections: renderSectionNav };
  }

  return { create };
})();
