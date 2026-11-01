// Catalog data shared by every view: the patterns in display order, the group
// definitions, and the lookups and status badge built from them. Loaded after
// the generated catalog.js; exposes everything on window.PE.catalog. No state.
window.PE = window.PE || {};
window.PE.catalog = (() => {
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

  return {
    GROUPS, PATTERN_GROUPS, patterns, fallbackGroup, patternGroup, patternGroupKey, patternStatusBadge
  };
})();
