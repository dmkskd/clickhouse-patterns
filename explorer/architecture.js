// Architecture panel: the logical, schematic and physical drawings of the open
// pattern, zoom and panning, the expanded diagram modal, note tooltips, SVG
// download, and the panel's placement and collapse preferences. app.js owns
// the selection and the control-plane state and passes them in as accessors.
window.PE = window.PE || {};
window.PE.architecture = (() => {
  "use strict";
  const { esc, FLOW_COLORS } = window.PE.util;
  const $ = (id) => document.getElementById(id);
  const apiUrl = (path) => new URL(path.replace(/^\//, ""), document.baseURI).toString();
  const MIN_ZOOM = 0.5;
  const MAX_ZOOM = 2.5;
  const ZOOM_STEP = 0.1;

  function create(deps) {
    // deps: getSelected(), getControl(), canInspect(), openInspector(resourceKey),
    //       onPlacementChange()
    const canvas = $("architecture-canvas");
    const diagramModal = $("diagram-modal");
    const modalCanvas = $("diagram-modal-canvas");
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
      const active = deps.getControl().snapshot?.session;
      return Boolean(
        deps.getControl().interactive && deps.getControl().token && deps.getSelected()?.profiles?.length
        && active && active.slug === deps.getSelected().slug
      );
    }

    function canvasMessage(title, detail) {
      return `<div class="empty-state"><div><strong>${esc(title)}</strong><br><span>${esc(detail)}</span></div></div>`;
    }

    async function renderPhysical() {
      const slug = deps.getSelected()?.slug;
      if (!slug) return;
      const request = (topologyRequest += 1);
      const stale = () =>
        request !== topologyRequest || deps.getSelected()?.slug !== slug || architectureView !== "physical";
      canvas.innerHTML = canvasMessage("Reading the Compose wiring…", `docker compose config for ${slug}`);
      $("download-svg").disabled = true;
      try {
        const response = await fetch(apiUrl(`api/topology?pattern=${encodeURIComponent(slug)}`), {
          cache: "no-store",
          headers: { "X-Explorer-Token": deps.getControl().token }
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

    // The panel and the expanded modal have the same switch, driven by the one
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
      if (!deps.getSelected()) return "Resource flow";
      if (architectureView === "physical") return `${deps.getSelected().title} · containers`;
      return architectureView === "schematic" ? `${deps.getSelected().title} · diagram` : deps.getSelected().title;
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
      if (deps.getSelected()?.graph) canvas.innerHTML = draw(deps.getSelected(), { inspectable: deps.canInspect() });
      else canvas.innerHTML = canvasMessage("Architecture pending", "This pattern has not declared a compact resource graph yet.");
      resetDiagramZoom();
      $("download-svg").disabled = !deps.getSelected()?.graph;
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
      if (!deps.getSelected() || $("pattern-detail").hidden) return;
      if (architectureView === "physical" && !physicalAvailable()) {
        architectureView = graphView;
        renderArchitecture();
        return;
      }
      const snapshot = deps.getControl().snapshot;
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
      deps.onPlacementChange();
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
      if (resourceKey && deps.canInspect() && (event.key === "Enter" || event.key === " ")) {
        event.preventDefault();
        deps.openInspector(resourceKey);
        return;
      }
      if (event.key === "+" || event.key === "=") { event.preventDefault(); setDiagramZoom(diagramZoom + ZOOM_STEP); }
      else if (event.key === "-") { event.preventDefault(); setDiagramZoom(diagramZoom - ZOOM_STEP); }
      else if (event.key === "0") { event.preventDefault(); resetDiagramZoom(); }
      else if (event.key === "Enter" || event.key === " ") { event.preventDefault(); openDiagramModal(); }
    });
    function openDiagramModal() {
      if (!canvas.querySelector("svg")) return;
      diagramModal.showModal();
      syncModalDiagram();
      updateViewToggle();
    }
    canvas.addEventListener("click", (event) => {
      const resourceNode = event.target.closest?.(".resource");
      const resourceKey = resourceNode?.dataset.resourceKey;
      if (resourceKey && deps.canInspect()) { deps.openInspector(resourceKey); return; }
      if (resourceNode) return;
      if (event.target.closest?.("svg")) openDiagramModal();
    });
    $("modal-zoom-out").addEventListener("click", () => setModalZoom(modalZoom - ZOOM_STEP));
    $("modal-zoom-reset").addEventListener("click", resetModalZoom);
    $("modal-zoom-in").addEventListener("click", () => setModalZoom(modalZoom + ZOOM_STEP));
    $("diagram-modal-close").addEventListener("click", () => diagramModal.close());
    diagramModal.addEventListener("click", (event) => {
      if (event.target === diagramModal) diagramModal.close();
    });
    modalCanvas.addEventListener("click", (event) => {
      const resourceNode = event.target.closest?.(".resource");
      const resourceKey = resourceNode?.dataset.resourceKey;
      if (resourceKey && deps.canInspect()) deps.openInspector(resourceKey);
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
      if (resourceKey && deps.canInspect() && (event.key === "Enter" || event.key === " ")) {
        event.preventDefault();
        deps.openInspector(resourceKey);
        return;
      }
      if (event.key === "+" || event.key === "=") { event.preventDefault(); setModalZoom(modalZoom + ZOOM_STEP); }
      else if (event.key === "-") { event.preventDefault(); setModalZoom(modalZoom - ZOOM_STEP); }
      else if (event.key === "0") { event.preventDefault(); resetModalZoom(); }
    });
    function downloadDiagramSvg(svg) {
      if (!svg || !deps.getSelected()) return;
      const exportedSvg = svg.cloneNode(true);
      exportedSvg.removeAttribute("style");
      const blob = new Blob([new XMLSerializer().serializeToString(exportedSvg)], { type: "image/svg+xml" });
      const link = document.createElement("a"); link.href = URL.createObjectURL(blob); const suffix = { logical: "", schematic: "-diagram", physical: "-containers" }[architectureView] || "";
      link.download = `${deps.getSelected().slug}${suffix}.svg`; link.click();
      setTimeout(() => URL.revokeObjectURL(link.href), 1000);
    }
    $("download-svg").addEventListener("click", () => downloadDiagramSvg(canvas.querySelector("svg")));
    $("download-svg-modal")?.addEventListener("click", () =>
      downloadDiagramSvg(modalCanvas.querySelector("svg") || canvas.querySelector("svg")));

    // Restores the saved placement and collapse state. app.js calls it once,
    // after every module exists, because a placement change refreshes the
    // section nav through deps.onPlacementChange().
    function restoreLayout() {
      try {
        const savedPlace = localStorage.getItem(DIAGRAM_PLACE_KEY);
        applyDiagramPlacement(DIAGRAM_PLACES.includes(savedPlace) ? savedPlace : "bottom", false);
        applyDiagramCollapsed(localStorage.getItem(DIAGRAM_COLLAPSE_KEY) === "1", false);
      } catch (_error) {
        applyDiagramPlacement("bottom", false);
      }
    }

    // Each pattern opens on the reader's preferred drawing of the graph; the
    // physical view is a deliberate, server-backed step down into the wiring.
    function openPattern(pattern) {
      const flows = pattern.graph?.flows || [];
      const legendHtml = flows.map((flow) => `<span><i style="background:${FLOW_COLORS[flow] || "#8b93ad"}"></i>${esc(flow)}</span>`).join("");
      $("flow-legend").innerHTML = legendHtml;
      const modalLegend = $("modal-flow-legend");
      if (modalLegend) modalLegend.innerHTML = legendHtml;
      architectureView = graphView;
      renderArchitecture();
    }

    return {
      openPattern, render: renderArchitecture, sync: syncArchitecture, restoreLayout,
      isModalOpen: () => diagramModal.open, closeModal: () => diagramModal.close(),
    };
  }

  return { create };
})();
