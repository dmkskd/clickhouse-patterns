// Static-first browser client; a local server progressively enables lifecycle controls.
(() => {
  "use strict";

  // Shared constant tables and esc() live in util.js (window.PE.util) and the
  // sorted catalog in catalog-data.js (window.PE.catalog). The views live in
  // guide.js, catalog-view.js, pattern-page.js and architecture.js; the control
  // plane in session.js. This file keeps the selection, the filters, routing,
  // the theme and the boot sequence.
  const { TOPOLOGIES } = window.PE.util;
  const { PATTERN_GROUPS, patterns, patternGroupKey } = window.PE.catalog;
  const $ = (id) => document.getElementById(id);
  const search = $("pattern-search");
  const resourceInspector = $("resource-inspector");
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
  let control = { mode: "static", interactive: false, token: null, snapshot: null };

  function canInspectSelectedPattern() {
    const active = control.snapshot?.session;
    return Boolean(
      control.interactive && control.token && selected && active
      && active.slug === selected.slug && active.reachable && active.phase !== "failed"
    );
  }

  // Single entry point for a catalog state change: merge, write the URL, redraw.
  // `replace` is for keystroke-rate changes (typing in the search box), which
  // should not leave one history entry per character.
  function applyFilters(patch, { replace = false, home = false } = {}) {
    catalogFilters = { ...catalogFilters, ...patch };
    if (home && selected) showCatalogHome(false);
    updateRoute(selected?.slug || "", replace);
    catalogView.renderCatalogHome();
    catalogView.renderSidebar();
  }

  // "All patterns": back to the home page with nothing narrowed.
  function showHome() {
    search.value = "";
    applyFilters({ group: "all", topology: "all", search: "" }, { home: true });
  }

  function openGroup(key) {
    applyFilters({ group: key }, { home: true });
    $("catalog-home")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // ===================== VIEWS =====================
  // Constructors only wire listeners; they never call back into this file, so
  // the order below only has to give each module the ones it takes.
  const guide = window.PE.guide.create({ patterns, openPattern: selectPattern });
  const catalogView = window.PE.catalogView.create({
    getSelected: () => selected,
    getFilters: () => catalogFilters,
    getControl: () => control,
    applyFilters,
    openPattern: selectPattern,
    showHome,
    guide,
  });
  const page = window.PE.patternPage.create({ openPattern: selectPattern, openGroup, showHome });
  const architecture = window.PE.architecture.create({
    getSelected: () => selected,
    getControl: () => control,
    canInspect: canInspectSelectedPattern,
    openInspector: (resourceKey) => session.openResourceInspector(resourceKey),
    onPlacementChange: () => catalogView.refreshSections(),
  });
  architecture.restoreLayout();

  // ===================== ROUTING & PATTERN SELECTION (detail view) =====================
  // The whole catalog state is the route, so a link encodes the group, the
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
    if (architecture.isModalOpen()) architecture.closeModal();
    selected = null;
    document.querySelector(".app-shell").classList.add("home-view");
    $("catalog-home").hidden = false;
    $("pattern-detail").hidden = true;
    document.title = "ClickHouse Pattern Explorer";
    if (updateUrl) updateRoute("");
    catalogView.renderCatalogHome();
    catalogView.renderSidebar();
    session.renderSession();
  }


  function selectPattern(slug, updateUrl = true) {
    if (resourceInspector.open) resourceInspector.close();
    selected = patterns.find((pattern) => pattern.slug === slug);
    if (!selected) { showCatalogHome(updateUrl); return; }
    document.querySelector(".app-shell").classList.remove("home-view");
    $("catalog-home").hidden = true;
    $("pattern-detail").hidden = false;
    page.render(selected);
    architecture.openPattern(selected);
    if (updateUrl) updateRoute(selected.slug);
    catalogView.renderSidebar();
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
  // The brand is "start over": back to the home page with nothing narrowed.
  $("show-catalog-home").addEventListener("click", showHome);
  $("clone-pattern")?.addEventListener("click", () => $("clone-modal").showModal());
  $("clone-modal-close")?.addEventListener("click", () => $("clone-modal").close());
  $("clone-modal")?.addEventListener("click", (event) => {
    if (event.target === $("clone-modal")) $("clone-modal").close();
  });
  window.addEventListener("popstate", (event) => {
    const route = readRoute();
    catalogFilters = { group: route.group, topology: route.topology, search: route.search };
    search.value = route.search;
    if (route.pattern) { selectPattern(route.pattern, false); return; }
    showCatalogHome(false);
    // Coming back from a pattern: return to where the reader left the catalog.
    const scroll = event.state?.scroll;
    if (typeof scroll === "number") requestAnimationFrame(() => window.scrollTo(0, scroll));
  });
  // Esc on a pattern page returns to its group, mirroring the group breadcrumb.
  // Dialogs close themselves on Esc, and a text field's own Esc handling wins.
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !selected) return;
    if (architecture.isModalOpen() || resourceInspector.open) return;
    const tag = (event.target?.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select") return;
    event.preventDefault();
    catalogFilters.group = patternGroupKey(selected);
    showCatalogHome();
    $("catalog-home")?.scrollIntoView({ behavior: "smooth", block: "start" });
  });
  $("resource-inspector-close").addEventListener("click", () => resourceInspector.close());
  resourceInspector.addEventListener("click", (event) => {
    if (event.target === resourceInspector) resourceInspector.close();
  });

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
    renderList: () => catalogView.renderSidebar(),
    renderCatalogHome: () => catalogView.renderCatalogHome(),
    canInspect: canInspectSelectedPattern,
    syncArchitecture: () => architecture.sync(),
    patterns,
    patternGroups: PATTERN_GROUPS,
  });

  const route = readRoute();
  search.value = route.search;
  catalogView.renderSidebar();
  if (route.pattern) selectPattern(route.pattern, false);
  else showCatalogHome(false);
  session.connectControlPlane();
})();
