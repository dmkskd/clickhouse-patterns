// View adapters extend results with columns, legends and scalar clipboard data.
// Registration is application code; manifests select a renderer and supply data.
window.PE = window.PE || {};
window.PE.experimentViews = (() => {
  "use strict";
  const renderers = new Map();

  function register(type, renderer) {
    if (renderers.has(type)) throw new Error(`Duplicate experiment view: ${type}`);
    renderers.set(type, renderer);
  }

  function prepare(experiment, runs) {
    // Preserve stage charts for existing workspace manifests. An explicit []
    // disables views; other structured results require an explicit declaration.
    const declarations = experiment.views ?? [{type: "stages", source: "stages"}];
    const columns = [], legends = [];
    declarations.forEach((view, index) => {
      const renderer = renderers.get(view.type);
      if (!renderer) throw new Error(`Unknown experiment view: ${view.type}`);
      const prepared = renderer.prepare(view, runs, experiment);
      if (!prepared) return;
      columns.push({key: `view_${index}`, group: "Timeline", ...prepared.column});
      if (prepared.legend) legends.push(prepared.legend);
    });
    return {columns, legends};
  }

  function reset() {
    renderers.forEach((renderer) => renderer.reset?.());
  }

  return {register, prepare, reset};
})();
