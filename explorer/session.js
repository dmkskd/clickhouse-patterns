// Session / control-plane layer: everything that depends on a local Pattern
// Explorer server (start/validate/stop, live status bar, resource inspector,
// live reload). app.js owns `selected` and `control` and hands this module a
// small `ctx` of accessors; this module owns the timers and UI flags and wires
// its own session controls. Created once via PE.session.create(ctx).
window.PE = window.PE || {};
window.PE.session = (() => {
  "use strict";
  const { esc, displayTitle, KIND_LABELS } = window.PE.util;
  const $ = (id) => document.getElementById(id);
  const apiUrl = (path) => new URL(path.replace(/^\//, ""), document.baseURI).toString();

  // Points at the repository's setup section rather than repeating the commands
  // in the UI, so the instructions have a single home.
  const REPO_LINK =
    '<a class="repo-hint" href="https://github.com/dmkskd/clickhouse-patterns#explore-locally"' +
    ' target="_blank" rel="noopener noreferrer">' +
    '<svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor" aria-hidden="true">' +
    '<path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 ' +
    '0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 ' +
    '1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 ' +
    '0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 ' +
    '2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 ' +
    '2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 ' +
    '.21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z"/></svg>' +
    '<span>Set up locally</span></a>';

  function create(ctx) {
    // ctx: getSelected(), getControl(), setControl(c), selectPattern(slug),
    //      renderList(), renderCatalogHome(), canInspect(), syncArchitecture(),
    //      patterns, patternGroups
    const canvas = $("architecture-canvas");
    const modalCanvas = $("diagram-modal-canvas");
    const resourceInspector = $("resource-inspector");
    const resourceInspectorBody = $("resource-inspector-body");
    let refreshTimer = null;
    let liveReloadTimer = null;
    let liveRevision = null;
    let sessionLogsExpanded = false;
    let sessionLogsClosed = false;
    let clearedLogSequence = 0;
    let connInfoOpen = false;   // reveal the ClickHouse connection by clicking the Local server pill

    function setVisible(id, visible) {
      $(id).hidden = !visible;
    }

    function renderExplorerMode() {
      const control = ctx.getControl();
      const isLocal = control.mode === "local" && control.interactive;
      const badge = $("explorer-mode");
      badge.className = `explorer-mode ${isLocal ? "local" : "static"}`;
      $("explorer-mode-label").textContent = isLocal ? "Local server" : "Static catalog";
      badge.title = isLocal
        ? "A local Pattern Explorer server is connected, so you can run, validate, and stop patterns and inspect their live tables."
        : "Browsing a generated catalog; running patterns needs the local server.";
    }

    function progressMessages(snapshot) {
      const events = snapshot?.events || [];
      return events
        .filter((event) => event.sequence > clearedLogSequence && ["progress", "operation", "validation"].includes(event.type))
        .slice(-100);
    }

    function progressMessage(event) {
      let message;
      if (event.type === "progress") message = event.payload.message;
      else if (event.type === "validation") message = event.payload.passed ? "Validation passed" : `Validation failed: ${event.payload.detail}`;
      else message = `${event.payload.name} ${event.payload.status}${event.payload.error ? ` — ${event.payload.error}` : ""}`;
      return message;
    }

    function progressText(event, nextEvent, operation) {
      const duration = stepDuration(event, nextEvent, operation);
      return `${duration ? `${duration}  ` : ""}${progressMessage(event)}`;
    }

    function operationDuration(operation) {
      if (!operation?.started_at) return "";
      const start = new Date(operation.started_at).getTime();
      const end = operation.finished_at ? new Date(operation.finished_at).getTime() : Date.now();
      return formatDuration(end - start);
    }

    function formatDuration(milliseconds) {
      const seconds = Math.max(0, Math.round(milliseconds / 1000));
      if (seconds < 60) return `${seconds}s`;
      const minutes = Math.floor(seconds / 60);
      return `${minutes}m ${String(seconds % 60).padStart(2, "0")}s`;
    }

    function stepDuration(event, nextEvent, operation) {
      const started = new Date(operation?.started_at).getTime();
      const eventStarted = new Date(event.timestamp).getTime();
      const ended = nextEvent
        ? new Date(nextEvent.timestamp).getTime()
        : operation?.status === "running"
          ? Date.now()
          : new Date(operation?.finished_at).getTime();
      if (!Number.isFinite(eventStarted) || !Number.isFinite(ended) || !Number.isFinite(started)) return "";
      return formatDuration(ended - eventStarted);
    }

    // On the catalog home, a running pattern shows as a chip in the hero (top right)
    // instead of the bar below. Reuses the real Stop/Open actions; the shared bar is
    // hidden on the home while this is visible.
    function renderHeroSession() {
      const el = $("hero-session");
      if (!el) return;
      const control = ctx.getControl();
      const shell = document.querySelector(".app-shell");
      const home = shell.classList.contains("home-view");
      const snap = control.snapshot;
      const active = snap?.session;
      const busy = snap?.operation?.status === "running";
      const starting = busy || active?.phase === "starting";
      const show = home && control.interactive && Boolean(active) && active.phase !== "failed";
      // Without a control plane the same slot explains how to get one, so the
      // hero's right column is never empty on the catalog home.
      const hint = home && !control.interactive;
      shell.classList.toggle("hero-running", show || hint);
      el.hidden = !(show || hint);
      if (!show) {
        el.replaceChildren();
        if (hint) {
          el.innerHTML =
            `<span class="hero-session-label">Browse only</span>` +
            `<span class="hero-session-hint">Running a pattern needs Docker and a ` +
            `local checkout.</span>` +
            REPO_LINK;
        }
        return;
      }
      const activePattern = ctx.patterns.find((pattern) => pattern.slug === active.slug);
      const activeGroup = ctx.patternGroups[activePattern?.group];
      const groupPrefix = activeGroup ? `${esc(activeGroup.label)} / ` : "";
      const titleText = esc(activePattern ? displayTitle(activePattern) : active.slug);
      el.classList.toggle("starting", starting);
      el.innerHTML =
        `<div class="hero-session-row">` +
          `<span class="hero-session-dot"></span>` +
          `<div class="hero-session-text">` +
            `<span class="hero-session-label">${starting ? "Starting pattern" : "Running pattern"}</span>` +
            `<span class="hero-session-title"><span class="session-group">${groupPrefix}</span>${titleText}</span>` +
          `</div>` +
        `</div>` +
        `<div class="hero-session-actions">` +
          `<button type="button" class="hero-open">Open pattern</button>` +
          (starting ? "" : `<button type="button" class="hero-stop danger">Stop session</button>`) +
        `</div>`;
      el.querySelector(".hero-open").onclick = () => ctx.selectPattern(active.slug);
      el.querySelector(".hero-stop")?.addEventListener("click", () => $("stop-session").click());
    }

    function renderSession() {
      renderHeroSession();
      const panel = $("session-panel");
      const control = ctx.getControl();
      const selected = ctx.getSelected();
      const snapshot = control.snapshot;
      const isLocal = control.mode === "local" && control.interactive;
      panel.hidden = !isLocal;
      if (!isLocal) return;
      renderExplorerMode();
      $("session-detail").hidden = false;
      $("session-title").title = "";
      panel.className = "session-panel";
      if (!control.interactive || !snapshot) {
        panel.classList.add("catalog-only");
        if (selected) panel.classList.add("pattern-context");
        $("session-eyebrow").textContent = selected ? "Static preview" : "Static catalog";
        $("session-title").textContent = selected ? "Run or adapt this pattern locally" : "Browse architecture patterns";
        // Without a control plane the page can only describe patterns, so it names
        // the command that runs them end to end rather than just saying it exists.
        const hint = REPO_LINK;
        $("session-detail").innerHTML = selected
          ? `Running locally starts this pattern's services, loads its data, validates the result, and allows live table inspection from this page. ${hint}`
          : `Diagrams, trade-offs, references, and SVG export work without a local service. Running the patterns end to end needs the local explorer. ${hint}`;
        ["start-session", "validate-session", "stop-session", "view-running", "toggle-session-logs"].forEach((id) => setVisible(id, false));
        setVisible("explorer-mode", true);   // "Static catalog" indicator (no local server)
        $("session-links").replaceChildren();
        setVisible("session-progress", false);
        return;
      }

      const active = snapshot.session;
      const operation = snapshot.operation;
      const busy = operation?.status === "running";
      const starting = active?.phase === "starting";
      if (busy) panel.classList.add("busy");
      else if (active?.phase === "failed") panel.classList.add("failed");
      else if (active) panel.classList.add("active");

      const selectedDiffers = Boolean(active && selected && active.slug !== selected.slug);
      // Whenever the page shown is not the running pattern (the catalog home, or a
      // different pattern's page), the bar is compact: open the running one or stop
      // it. Full controls (SQL console, schema, logs, validate) live on its page.
      const compact = Boolean(active) && (!selected || selectedDiffers);
      const messages = progressMessages(snapshot);
      const latestProgress = [...messages].reverse().find((event) => event.type === "progress");
      if (busy) {
        $("session-eyebrow").textContent = starting ? "Starting services" : `${operation.name} in progress`;
        $("session-title").textContent = operation.pattern || active?.slug || "Pattern session";
        $("session-detail").textContent = latestProgress
          ? `Latest: ${latestProgress.payload.message}`
          : "The page will remain connected while the lifecycle operation completes.";
      } else if (active) {
        const activePattern = ctx.patterns.find((pattern) => pattern.slug === active.slug);
        const activeGroup = ctx.patternGroups[activePattern?.group];
        // The green dot already signals "live"; show <group> / <pattern title>.
        $("session-eyebrow").textContent = "";
        // On its own page, the header is <group> / <title>. When shown from elsewhere
        // (home, or a different pattern), lead with "Running pattern:" instead.
        const titleText = esc(activePattern ? displayTitle(activePattern) : active.slug);
        const groupPrefix = activeGroup ? `${esc(activeGroup.label)} / ` : "";
        // .title-link is the only part that underlines on hover; the compact
        // "Running pattern:" label sits outside it as plain status text.
        const titleLink = `<span class="title-link">${groupPrefix ? `<span class="session-group">${groupPrefix}</span>` : ""}${titleText}</span>`;
        $("session-title").innerHTML = compact
          ? `<span class="running-label">Running pattern: </span>${titleLink}`
          : titleLink;
        if (selectedDiffers) {
          // Title already names the running pattern; here name the page being viewed.
          $("session-detail").textContent = `You are viewing ${displayTitle(selected)} below.`;
        } else {
          $("session-detail").textContent =
            `${active.driver_node} at ${active.driver_url}${active.source_changed ? " · source changed" : ""}`;
          $("session-detail").hidden = !connInfoOpen;   // revealed by clicking the Local server pill
        }
      } else {
        // No running session: on the catalog home there is nothing to show.
        if (!selected) panel.classList.add("catalog-only");
        const runnable = Boolean(selected?.runnable);
        $("session-eyebrow").textContent = runnable ? "No active session" : "Reference pattern";
        // For a runnable pattern the green "Launch pattern" button carries the label,
        // so the redundant status text is hidden (idle-ready), leaving just the dot.
        // The slug (the `just test` argument) stays available as the button's tooltip.
        if (runnable) panel.classList.add("idle-ready");
        $("session-title").textContent = selected
          ? (runnable ? "Launch pattern" : selected.slug)
          : "Choose a pattern";
        // The button's presence already means a local server is connected, so the
        // separate "Local server" pill is dropped here; its explanation moves to the
        // button's hover, alongside the slug (the `just test` argument).
        $("start-session").title = selected && runnable
          ? `Launches on the connected local server, then validates. Inspect live tables or stop from here. (just test ${selected.slug})`
          : "";
        $("session-detail").textContent = runnable
          ? "Start prepares infrastructure, loads data, validates it, and leaves it live."
          : "This workspace entry documents an architecture; runtime automation is optional.";
        // Keep the idle bar to a single row; the title already says what Start does.
        $("session-detail").hidden = true;
      }

      // Launch is offered when nothing runs, or when the viewed pattern differs from
      // the running one (a switch: teardown + launch in one click). Terminal-owned
      // sessions can only be finished in their terminal, like Stop.
      setVisible("start-session", Boolean(selected?.runnable) && !busy
        && (!active || (selectedDiffers && active.owner !== "terminal")));
      setVisible("validate-session", Boolean(active) && !busy && !compact);
      // Switching is a single Launch action. Do not also offer Stop here: Launch
      // confirms and performs the teardown before starting the selected pattern.
      setVisible("stop-session", Boolean(active) && !busy && !selectedDiffers
        && active.owner !== "terminal");
      setVisible("view-running", (selectedDiffers || compact) && !busy);
      // With a local server connected the whole bar already implies it (run button,
      // SQL console, Stop), so the "Local server" pill is redundant here. It stays
      // only as the "Static catalog" indicator when there is no server (static path).
      setVisible("explorer-mode", false);
      $("view-running").textContent = compact ? "Open running pattern" : "View running";
      // On the home, the whole running-session bar is a shortcut into the pattern.
      const summaryEl = document.querySelector(".session-summary");
      summaryEl.classList.toggle("clickable", compact);
      summaryEl.onclick = compact && active ? () => ctx.selectPattern(active.slug) : null;
      $("start-session").disabled = busy;
      const switching = Boolean(active && selectedDiffers);
      $("start-session").textContent = switching ? "Launch this pattern" : "Launch pattern";
      if (switching) $("start-session").title = `Stops ${active.slug} (its containers and volumes are removed), then launches ${selected.slug}.`;
      $("validate-session").disabled = busy;
      $("stop-session").disabled = busy;
      $("stop-session").title = active?.owner === "terminal" ? "Finish this session in its `just run` terminal" : "Remove containers and volumes";
      // The Validate control doubles as the last-validation indicator: its label
      // and color reflect the session phase, and clicking re-runs (opening the logs).
      const validateBtn = $("validate-session");
      const phase = active?.phase;
      const mark = phase === "validated" ? '<span class="vtick">✓</span> '
        : phase === "failed" ? '<span class="vcross">✕</span> '
        : "";
      validateBtn.innerHTML = `${mark}Validate`;
      const lastState = phase === "validated" ? "Last validation: passed"
        : phase === "failed" ? "Last validation: failed"
        : "Not validated yet";
      validateBtn.title = `${lastState}.\nClick to re-run and show the result.`;

      const links = $("session-links");
      links.replaceChildren();
      if (active?.play_url && active?.schema_url && !compact && !starting) {
        [["SQL console", active.play_url], ["Schema", active.schema_url]].forEach(([label, href]) => {
          const link = document.createElement("a");
          link.href = href; link.target = "_blank"; link.rel = "noreferrer"; link.textContent = label;
          links.append(link);
        });
      }

      const canShowLogs = Boolean(messages.length && (active || operation?.status === "failed"));
      const logsButton = $("toggle-session-logs");
      // During a run the panel normally opens itself, but after the user closes
      // it this button must remain available to bring the live log back.
      setVisible("toggle-session-logs", canShowLogs && !compact && (!busy || sessionLogsClosed));
      logsButton.textContent = sessionLogsClosed ? "Show log" : sessionLogsExpanded ? "Hide logs" : "Show logs";
      logsButton.setAttribute("aria-expanded", String(!sessionLogsClosed && sessionLogsExpanded));
      const showProgress = !sessionLogsClosed
        && (busy || operation?.status === "failed" || (canShowLogs && sessionLogsExpanded));
      setVisible("session-progress", showProgress);
      $("operation-state").textContent = operation
        ? `${starting && operation.status === "running" ? "starting" : operation.status} · ${operationDuration(operation)}`
        : "";
      const progress = $("progress-events");
      progress.replaceChildren(...messages.map((event, index) => {
        const item = document.createElement("li");
        const failed = event.payload?.error || event.payload?.passed === false;
        const current = busy && event === latestProgress;
        const elapsed = document.createElement("time");
        elapsed.className = "progress-duration";
        const duration = stepDuration(event, messages[index + 1], operation);
        elapsed.textContent = duration ? `${duration}` : "";
        elapsed.title = current ? "Time in the current step" : "Time until the next lifecycle update";
        const message = document.createElement("span");
        message.textContent = progressMessage(event);
        item.replaceChildren(elapsed, message);
        if (current) item.classList.add("current");
        else if (!failed) item.classList.add("completed");
        if (failed) item.classList.add("error");
        return item;
      }));
      // A failed start or switch can leave containers up and a session record
      // that no longer matches them. The browser cannot tear that down, so
      // point at the terminal command that can.
      if (operation?.status === "failed") {
        const hint = document.createElement("li");
        hint.className = "progress-hint";
        hint.textContent = "If the environment is left inconsistent, run  just reset  in a terminal to remove every container and clear the session.";
        progress.append(hint);
      }
      progress.scrollTop = progress.scrollHeight;
      $("clear-session-logs").hidden = messages.length === 0;
      $("copy-session-logs").hidden = messages.length === 0;
    }

    async function refreshSession() {
      if (!ctx.getControl().interactive) return;
      try {
        const response = await fetch(apiUrl("api/session"), { cache: "no-store" });
        if (!response.ok) throw new Error(`session request failed (${response.status})`);
        ctx.getControl().snapshot = await response.json();
        ctx.renderList();
        ctx.renderCatalogHome();
        renderSession();
        syncResourceInteractivity();
        ctx.syncArchitecture();
      } catch (error) {
        ctx.setControl({ mode: "static", interactive: false, token: null, snapshot: null });
        renderSession();
        syncResourceInteractivity();
        ctx.syncArchitecture();
      }
    }

    async function command(path, payload = {}) {
      const response = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Explorer-Token": ctx.getControl().token },
        body: JSON.stringify(payload)
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || `request failed (${response.status})`);
      await refreshSession();
    }

    function renderClickHouseInspector(payload) {
      $("resource-inspector-title").textContent = `${payload.database}.${payload.table}`;
      $("resource-inspector-subtitle").textContent = payload.engine;
      const columnRows = payload.columns.map((column) => [
        column.name,
        column.type,
        column.default_kind
          ? `${column.default_kind} ${column.default_expression || ""}`.trim()
          : ""
      ]);
      const sample = payload.sample;
      resourceInspectorBody.innerHTML = `
        <section class="resource-inspector-section">
          <h3>Columns</h3>
          ${window.PE.util.dataTable(["Column", "Type", "Default"], columnRows)}
        </section>
        <section class="resource-inspector-section">
          <h3>Table definition</h3>
          <pre>${esc(payload.create_statement)}</pre>
        </section>
        <section class="resource-inspector-section">
          <h3>Live contents</h3>
          ${payload.sample_disabled ? `<p class="resource-inspector-note">${esc(payload.sample_disabled)}</p>` : ""}
          ${payload.sample_error ? `<p class="resource-inspector-note">The definition loaded, but this resource could not be sampled: ${esc(payload.sample_error)}</p>` : ""}
          ${sample ? `<p class="resource-sample-meta">Raw live sample · up to ${sample.limit} rows</p>${window.PE.util.dataTable(sample.columns, sample.rows)}` : ""}
        </section>`;
    }

    function renderObjectStoreInspector(payload) {
      $("resource-inspector-title").textContent = payload.title;
      $("resource-inspector-subtitle").textContent = payload.subtitle;
      const rows = payload.objects.map((object) => [
        object.key, String(object.size), object.modified, object.format
      ]);
      resourceInspectorBody.innerHTML = `<section class="resource-inspector-section">
        <h3>Objects</h3>
        <p class="resource-sample-meta">${esc(payload.bucket)} · ${esc(payload.prefix || "/")} · up to ${payload.object_limit} objects${payload.truncated ? " (more available)" : ""}</p>
        ${rows.length ? window.PE.util.dataTable(["Object", "Bytes", "Modified", "Format"], rows) : '<p class="resource-inspector-note">No objects match this prefix.</p>'}
      </section>`;
      resourceInspectorBody.querySelectorAll("tbody tr").forEach((row, index) => {
        const cell = row.querySelector("td");
        const object = payload.objects[index];
        if (!cell || !object) return;
        const button = document.createElement("button");
        button.className = "resource-object-link";
        button.type = "button";
        button.textContent = object.key;
        button.addEventListener("click", () => openResourceInspector(payload.resource.key, object.key));
        cell.replaceChildren(button);
      });
    }

    function renderObjectPreviewInspector(payload) {
      $("resource-inspector-title").textContent = payload.title;
      $("resource-inspector-subtitle").textContent = payload.subtitle;
      const sample = payload.sample;
      resourceInspectorBody.innerHTML = `<section class="resource-inspector-section">
        <h3>Object preview</h3>
        <p class="resource-sample-meta">${esc(payload.object.key)} · ${payload.object.size} bytes</p>
        ${payload.sample_disabled ? `<p class="resource-inspector-note">${esc(payload.sample_disabled)}</p>` : ""}
        ${payload.sample_error ? `<p class="resource-inspector-note">This object could not be decoded: ${esc(payload.sample_error)}</p>` : ""}
        ${sample ? `<p class="resource-sample-meta">Read-only sample · up to ${sample.limit} rows</p>${window.PE.util.dataTable(sample.columns, sample.rows)}` : ""}
      </section>`;
    }

    function renderResourceInspector(payload) {
      if (payload.type === "object-store") return renderObjectStoreInspector(payload);
      if (payload.type === "object-preview") return renderObjectPreviewInspector(payload);
      return renderClickHouseInspector(payload);
    }

    function showResourceInspectorMessage(title, detail) {
      $("resource-inspector-title").textContent = title;
      $("resource-inspector-subtitle").textContent = "";
      resourceInspectorBody.innerHTML = `<div class="resource-inspector-message"><div>${esc(detail)}</div></div>`;
    }

    async function openResourceInspector(resourceKey, objectKey = null) {
      const selected = ctx.getSelected();
      const resource = selected?.graph?.resources?.find((item) => item.key === resourceKey);
      if (!resource || !ctx.canInspect()) return;
      $("resource-inspector-title").textContent = resource.properties?.label || resource.name;
      $("resource-inspector-subtitle").textContent = KIND_LABELS[resource.kind] || resource.kind;
      resourceInspectorBody.innerHTML = `<div class="resource-inspector-loading"><div>Reading the live ${KIND_LABELS[resource.kind] || resource.kind} resource…</div></div>`;
      if (!resourceInspector.open) resourceInspector.showModal();

      try {
        const objectQuery = objectKey ? `&object=${encodeURIComponent(objectKey)}` : "";
        const resourceUrl = apiUrl(`api/resource?pattern=${encodeURIComponent(selected.slug)}&resource=${encodeURIComponent(resourceKey)}${objectQuery}`);
        const response = await fetch(resourceUrl, {
          cache: "no-store",
          headers: { "X-Explorer-Token": ctx.getControl().token }
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || `request failed (${response.status})`);
        renderResourceInspector(payload);
      } catch (error) {
        const detail = error instanceof Error ? error.message : String(error);
        showResourceInspectorMessage(resource.name, `Live inspection failed: ${detail}`);
      }
    }

    function syncResourceInteractivity() {
      const enabled = ctx.canInspect();
      const selected = ctx.getSelected();
      if (!enabled && resourceInspector.open) resourceInspector.close();
      [canvas, modalCanvas].forEach((container) => {
        container.querySelectorAll("[data-readable-resource-key]").forEach((node) => {
          const resourceKey = node.dataset.readableResourceKey;
          node.classList.toggle("inspectable-resource", enabled);
          if (enabled) {
            const resource = selected?.graph?.resources?.find((item) => item.key === resourceKey);
            const displayName = resource?.properties?.label || resource?.name || resourceKey;
            node.dataset.resourceKey = resourceKey;
            node.setAttribute("tabindex", "0");
            node.setAttribute("role", "button");
            node.setAttribute("aria-label", `Inspect ${displayName}`);
          } else {
            delete node.dataset.resourceKey;
            node.removeAttribute("tabindex");
            node.removeAttribute("role");
            node.removeAttribute("aria-label");
          }
        });
      });
    }

    async function connectControlPlane() {
      try {
        const response = await fetch(apiUrl("api/config"), { cache: "no-store" });
        if (!response.ok) { renderSession(); return; }
        const config = await response.json();
        ctx.setControl({ mode: config.interactive ? "local" : "static", interactive: Boolean(config.interactive), token: config.token, snapshot: null });
        if (!ctx.getControl().interactive) { renderSession(); return; }
        await refreshSession();
        await checkLiveRevision();
        const events = new EventSource(apiUrl("api/events"));
        events.onmessage = refreshSession;
        ["progress", "operation", "validation", "session"].forEach((name) => events.addEventListener(name, refreshSession));
        refreshTimer = window.setInterval(refreshSession, 4000);
        liveReloadTimer = window.setInterval(checkLiveRevision, 1500);
      } catch (_error) {
        ctx.setControl({ mode: "static", interactive: false, token: null, snapshot: null });
        renderSession();
      }
    }

    async function checkLiveRevision() {
      if (!ctx.getControl().interactive) return;
      try {
        const response = await fetch(apiUrl("api/revision"), { cache: "no-store" });
        if (!response.ok) return;
        const { revision } = await response.json();
        if (!liveRevision) { liveRevision = revision; return; }
        if (revision && revision !== liveRevision) window.location.reload();
      } catch (_error) {
        // The lifecycle connection owns capability fallback; live reload is optional.
      }
    }

    // A transient toast: a pending cue fires synchronously on click, then the
    // result (ok/error) replaces it. kind is "pending" | "ok" | "error".
    let toastTimer = null;
    function showToast(message, kind = "pending") {
      let toast = $("session-toast");
      if (!toast) {
        toast = document.createElement("div");
        toast.id = "session-toast";
        document.body.appendChild(toast);
      }
      toast.textContent = message;
      toast.className = `session-toast show ${kind}`;
      clearTimeout(toastTimer);
      const linger = kind === "pending" ? 20000 : kind === "error" ? 15000 : 5000;
      toastTimer = window.setTimeout(() => { toast.className = "session-toast"; }, linger);
    }

    // Session controls (moved from app.js wiring).
    $("start-session").addEventListener("click", async () => {
      const selected = ctx.getSelected();
      if (!selected) return;
      const active = ctx.getControl().snapshot?.session;
      sessionLogsExpanded = false;
      sessionLogsClosed = false;
      try {
        if (active && active.slug !== selected.slug) {
          // The server performs teardown + launch as one ordered operation so the
          // new run cannot race the asynchronous stop.
          if (!window.confirm(`Stop ${active.slug} and launch ${selected.slug}?\nThe ${active.slug} environment (containers and volumes) will be removed.`)) return;
          await command(apiUrl("api/session/switch"), { pattern: selected.slug });
          return;
        }
        await command(apiUrl("api/session/run"), { pattern: selected.slug });
      }
      catch (error) { showToast(error.message, "error"); }
    });
    $("validate-session").addEventListener("click", async () => {
      // Re-run validation and open the logs panel so the verify query's live output
      // and pass/fail show inline (the runner emits them as progress); the button
      // itself reflects the resulting state, and the panel can be closed afterward.
      sessionLogsExpanded = true;
      sessionLogsClosed = false;
      try { await command(apiUrl("api/session/validate")); }
      catch (error) { showToast(error.message, "error"); }
    });
    $("stop-session").addEventListener("click", async () => {
      const slug = ctx.getControl().snapshot?.session?.slug || "this pattern";
      if (!window.confirm(`Stop ${slug} and remove its containers and volumes?`)) return;
      try { await command(apiUrl("api/session/stop")); }
      catch (error) { showToast(error.message, "error"); }
    });
    $("view-running").addEventListener("click", () => {
      const slug = ctx.getControl().snapshot?.session?.slug;
      if (slug) ctx.selectPattern(slug);
    });
    $("explorer-mode").addEventListener("click", () => {
      if (!ctx.getControl().snapshot?.session) return;   // only meaningful with a live session
      connInfoOpen = !connInfoOpen;
      renderSession();
    });
    $("toggle-session-logs").addEventListener("click", () => {
      sessionLogsExpanded = !sessionLogsExpanded;
      sessionLogsClosed = !sessionLogsExpanded;
      renderSession();
    });
    $("close-session-logs").addEventListener("click", () => {
      sessionLogsExpanded = false;
      sessionLogsClosed = true;
      renderSession();
    });
    $("clear-session-logs").addEventListener("click", () => {
      const events = ctx.getControl().snapshot?.events || [];
      clearedLogSequence = Math.max(clearedLogSequence, ...events.map((event) => event.sequence || 0));
      renderSession();
    });
    $("copy-session-logs").addEventListener("click", async () => {
      const snapshot = ctx.getControl().snapshot;
      const operation = snapshot?.operation;
      const lines = progressMessages(snapshot)
        .map((event, index, events) => progressText(event, events[index + 1], operation));
      try {
        await navigator.clipboard.writeText(lines.join("\n"));
        showToast("Log copied", "ok");
      } catch (error) {
        showToast("Could not copy the log", "error");
      }
    });

    return { renderSession, connectControlPlane, openResourceInspector, syncResourceInteractivity };
  }

  return { create };
})();
