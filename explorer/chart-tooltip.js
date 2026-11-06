// Chart tooltip placement and lifecycle. Callers supply DOM content and styling.
window.PE = window.PE || {};
window.PE.chartTooltip = (() => {
  "use strict";
  function create(className) {
    let element = null, anchor = null;
    function hide() {
      if (element) element.hidden = true;
      anchor = null;
    }
    function show(target, ...content) {
      if (!element) {
        element = document.createElement("div");
        element.className = className;
        element.setAttribute("role", "tooltip");
        window.addEventListener("resize", hide);
        document.addEventListener("scroll", hide, true);
      }
      anchor = target;
      // Dialog content lives in the browser's top layer, above body tooltips.
      (target.closest("dialog") || document.body).append(element);
      element.replaceChildren(...content);
      element.hidden = false;
      const box = target.getBoundingClientRect();
      const width = element.offsetWidth, height = element.offsetHeight;
      element.style.left = `${Math.max(8, Math.min(window.innerWidth - width - 8, box.right - width))}px`;
      const top = box.bottom + 8 + height <= window.innerHeight ? box.bottom + 8 : box.top - height - 8;
      element.style.top = `${Math.max(8, Math.min(window.innerHeight - height - 8, top))}px`;
    }
    return {show, hide, get anchor() { return anchor; }};
  }
  return {create};
})();
