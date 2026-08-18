// Shared constants and pure helpers for the Pattern Explorer UI. Loaded before
// diagram.js and app.js; exposes everything on window.PE.util. No DOM, no state.
window.PE = window.PE || {};
window.PE.util = (() => {
  "use strict";

  const FLOW_COLORS = {
    ingestion: "#3ed598", input: "#3ed598", output: "#f6b73c",
    snapshot: "#a78bfa", changes: "#3ed598", transformation: "#f6b73c",
    query: "#4cc3f7", replication: "#a78bfa", evaluation: "#a78bfa",
    state: "#a78bfa", transitions: "#f472b6", test: "#8b93ad",
    // Pattern-specific flow names, colored so each diagram's flows stay distinct.
    prices: "#3ed598", trades: "#f472b6", refresh: "#a78bfa",
    ingest: "#3ed598", load: "#3ed598", cascade: "#f6b73c",
    "rollup-1m": "#f6b73c", "rollup-5m": "#a78bfa",
    "query-1m": "#4cc3f7", "query-5m": "#a78bfa",
    backup: "#f6b73c", restore: "#a78bfa"
  };
  const KIND_COLORS = {
    client: ["#e8edff", "#8893b6", "#5b6484"],
    validator: ["#e8edff", "#8893b6", "#5b6484"],
    topic: ["#d9ccff", "#a78bfa", "#7054c8"],
    "kafka-table": ["#c8eaff", "#55c7f7", "#238fc6"],
    mv: ["#c1f6dc", "#3ed598", "#1f9e6b"],
    "refreshable-mv": ["#c1f6dc", "#3ed598", "#1f9e6b"],
    distributed: ["#c3d6ff", "#7ba6f5", "#4a6fd0"],
    mergetree: ["#ffe1a1", "#f6b73c", "#c98f1d"],
    "replicated-mergetree": ["#ffe1a1", "#f6b73c", "#c98f1d"],
    part: ["#fff0c8", "#e4a42b", "#a66c11"],
    keepermap: ["#d8caff", "#a78bfa", "#7054c8"],
    "remote-table": ["#cfe0ff", "#6f91d8", "#496bad"],
    postgres: ["#c3d6ff", "#6f91d8", "#496bad"],
    mysql: ["#c8eaff", "#55bfe8", "#297ea6"],
    peerdb: ["#ffc9be", "#f47f6b", "#bd4b3b"],
    minio: ["#ffbdc2", "#e95d68", "#ad3340"],
    connector: ["#d9ccff", "#a78bfa", "#7054c8"],
    "consumer-group": ["#c8eaff", "#55c7f7", "#238fc6"]
  };
  const KIND_LABELS = {
    client: "Client", validator: "Validation query", topic: "Kafka topic", "kafka-table": "Kafka engine",
    mv: "Materialized view", "refreshable-mv": "Refreshable MV",
    distributed: "Distributed table", mergetree: "MergeTree",
    "replicated-mergetree": "ReplicatedMergeTree", keepermap: "KeeperMap state",
    part: "MergeTree part",
    "remote-table": "External table engine", postgres: "Postgres",
    mysql: "MySQL", peerdb: "PeerDB", minio: "Object storage", connector: "Connector",
    "consumer-group": "Kafka engine tables", s3queue: "S3Queue()"
  };
  const REPEAT = 38;
  const REPEAT_Y = REPEAT * 0.42;
  const INSPECTABLE_KINDS = new Set([
    "kafka-table", "mv", "refreshable-mv", "distributed", "mergetree", "replicated-mergetree", "keepermap",
    "remote-table", "minio"
  ]);
  const TOPOLOGIES = {
    single: { label: "Single node", help: "One ClickHouse node" },
    replicated: { label: "Replicated", help: "Multiple copies of the same data" },
    sharded: { label: "Sharded", help: "Data distributed across ClickHouse shards" }
  };
  const DIRECTIONS = {
    pull: { label: "Pull", help: "ClickHouse's Kafka engine reads on its own initiative" },
    push: { label: "Push", help: "An external system (Kafka Connect) writes into ClickHouse" }
  };

  // Diagram palettes: every theme-tuned color in the SVG renderer lives here.
  // `style` is the full per-scheme <style> block; icon/nodeShadow/grid* are
  // used by diagram.js markup directly. Selected by document's data-scheme.
  const DIAGRAM_STYLE_SHARED = "text{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}.edge{fill:none;stroke-width:1.8;stroke-dasharray:4 8;opacity:.78}.packet{filter:url(#glow)}.annotation-layer{pointer-events:none}.ghost-replica{opacity:.3}.replica-sync{fill:none;stroke:#a78bfa;stroke-width:1.5;opacity:.9}[data-resource-key]{cursor:pointer}.inspectable-resource{cursor:pointer;outline:none;transform-box:fill-box;transform-origin:center;transition:transform .12s ease,filter .12s ease}.inspectable-resource:hover,.inspectable-resource:focus-visible{transform:scale(1.07);filter:brightness(1.3)}.note-badge{cursor:help}";
  const DIAGRAM_PALETTES = {
    dark: {
      icon: "#f3f5ff",
      nodeShadow: "rgba(3,5,10,.5)",
      gridFill: "#11172b", gridStroke: "#7080c0",
      style: DIAGRAM_STYLE_SHARED + ".system{fill:#11162a;fill-opacity:.22;stroke-dasharray:7 7}.clickhouse{stroke:#7486c9;stroke-opacity:.28}.kafka{fill:#17132a;stroke:#a78bfa;stroke-opacity:.32}.postgres-system{fill:#111a2d;stroke:#6f91d8;stroke-opacity:.34}.mysql-system{fill:#10202a;stroke:#55bfe8;stroke-opacity:.34}.peerdb-system{fill:#24131a;stroke:#f47f6b;stroke-opacity:.34}.minio-system{fill:#241216;stroke:#e95d68;stroke-opacity:.3}.connector-system{fill:#241816;stroke:#f49a6b;stroke-opacity:.34}.boundary-label{fill:#7580a2;font-size:10px;letter-spacing:1.5px}.edge-label{fill:#c4cce1;font-size:10px;paint-order:stroke;stroke:#07080f;stroke-width:5px}.resource-name{fill:#f0f3ff;font-size:12px;font-weight:700;paint-order:stroke;stroke:#07080f;stroke-width:5px}.resource-kind{fill:#9ba5c2;font-size:10px;paint-order:stroke;stroke:#07080f;stroke-width:5px}.resource-detail{fill:#6f7998;font-size:9px;paint-order:stroke;stroke:#07080f;stroke-width:5px}.instance{fill:#493600;font-size:8px;font-weight:800;paint-order:stroke;stroke:#fff0c8;stroke-width:2px}.unassigned-label{fill:#555e78;stroke:#dfe5f5}[data-clickhouse-resource-key]:hover polygon{stroke:#9fb0dd;stroke-width:1.3px}.inspectable-resource:hover polygon,.inspectable-resource:focus-visible polygon{stroke:#fff;stroke-width:2px}.inspectable-resource:hover ellipse,.inspectable-resource:focus-visible ellipse{fill:#3ed598;opacity:.34}.note-badge circle{fill:#161b2e;stroke:#7580a2;stroke-width:1}.note-badge text{fill:#c4cce1;font-size:9px;font-weight:700}.has-note:hover .note-badge circle{fill:#233056;stroke:#aab4d6}"
    },
    light: {
      icon: "#3c4453",
      nodeShadow: "rgba(90,100,120,.35)",
      gridFill: "#b9c3d4", gridStroke: "#6b7a99",
      style: DIAGRAM_STYLE_SHARED + ".system{fill:#c9d2e0;fill-opacity:.14;stroke-dasharray:7 7}.clickhouse{stroke:#4a6fd0;stroke-opacity:.5}.kafka{fill:#ddd3f5;stroke:#7054c8;stroke-opacity:.45}.postgres-system{fill:#d3dfff;stroke:#496bad;stroke-opacity:.5}.mysql-system{fill:#d0eafa;stroke:#297ea6;stroke-opacity:.5}.peerdb-system{fill:#f8dcd7;stroke:#bd4b3b;stroke-opacity:.5}.minio-system{fill:#f8d7da;stroke:#ad3340;stroke-opacity:.5}.connector-system{fill:#f5e0d3;stroke:#c96a3b;stroke-opacity:.5}.boundary-label{fill:#6b7280;font-size:10px;letter-spacing:1.5px}.edge-label{fill:#454e5d;font-size:10px;paint-order:stroke;stroke:#eceff3;stroke-width:3.5px}.resource-name{fill:#232833;font-size:12px;font-weight:700;paint-order:stroke;stroke:#eceff3;stroke-width:3.5px}.resource-kind{fill:#5a6478;font-size:10px;paint-order:stroke;stroke:#eceff3;stroke-width:3.5px}.resource-detail{fill:#7d8598;font-size:9px;paint-order:stroke;stroke:#eceff3;stroke-width:3.5px}.instance{fill:#7a5c12;font-size:8px;font-weight:800;paint-order:stroke;stroke:#ffffff;stroke-width:2px}.unassigned-label{fill:#6b7280;stroke:#ffffff}[data-clickhouse-resource-key]:hover polygon{stroke:#4a6fd0;stroke-width:1.3px}.inspectable-resource:hover polygon,.inspectable-resource:focus-visible polygon{stroke:#232833;stroke-width:2px}.inspectable-resource:hover ellipse,.inspectable-resource:focus-visible ellipse{fill:#3d9e6d;opacity:.3}.note-badge circle{fill:#ffffff;stroke:#8a93a8;stroke-width:1}.note-badge text{fill:#5a6478;font-size:9px;font-weight:700}.has-note:hover .note-badge circle{fill:#fdf6e7;stroke:#c07a12}"
    }
  };

  // Topology (physical view) palette. Same rationale as DIAGRAM_PALETTES:
  // the SVG is downloadable and embeddable, so it carries its own <style>.
  const TOPOLOGY_PALETTES = {
    dark: {
      style: `
        text{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
        .card{fill:#141a2c;fill-opacity:.9;stroke:#39456d;stroke-width:1}
        .card.stopped{stroke-dasharray:5 5;stroke:#39456d;fill-opacity:.55}
        .service-name{fill:#f0f3ff;font-size:12px;font-weight:700}
        .service-image{fill:#9ba5c2;font-size:9.5px}
        .service-role{fill:#7ba6f5;font-size:9.5px;font-weight:700}
        .service-line{fill:#6f7998;font-size:9.5px}
        .service-line .key{fill:#8b93ad}
        .boundary{fill:#11162a;fill-opacity:.22;stroke:#7486c9;stroke-opacity:.28;stroke-dasharray:7 7}
        .host-band{fill:#161b2e;fill-opacity:.3;stroke:#7580a2;stroke-opacity:.3;stroke-dasharray:5 5}
        .boundary-label{fill:#7580a2;font-size:10px;letter-spacing:1.5px}
        .port-pill{fill:#1d2540;stroke:#4cc3f7;stroke-opacity:.55;stroke-width:1}
        .port-text{fill:#9fdcf7;font-size:9.5px;font-weight:700}
        .port-link{stroke:#4cc3f7;stroke-opacity:.45;stroke-width:1.3;stroke-dasharray:3 4;fill:none}
        .dep{fill:none;stroke:#8b93ad;stroke-width:1.6;stroke-dasharray:4 6;opacity:.8}
        .dep-label{fill:#8b93ad;font-size:9px;paint-order:stroke;stroke:#07080f;stroke-width:4px}
      `
    },
    light: {
      style: `
        text{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
        .card{fill:#ffffff;fill-opacity:.92;stroke:#c0c9db;stroke-width:1}
        .card.stopped{stroke-dasharray:5 5;fill-opacity:.6}
        .service-name{fill:#232833;font-size:12px;font-weight:700}
        .service-image{fill:#5a6478;font-size:9.5px}
        .service-role{fill:#3f6bbd;font-size:9.5px;font-weight:700}
        .service-line{fill:#7d8598;font-size:9.5px}
        .service-line .key{fill:#5a6478}
        .boundary{fill:#c9d2e0;fill-opacity:.16;stroke:#4a6fd0;stroke-opacity:.45;stroke-dasharray:7 7}
        .host-band{fill:#e7ebf2;fill-opacity:.5;stroke:#8a93a8;stroke-opacity:.45;stroke-dasharray:5 5}
        .boundary-label{fill:#6b7280;font-size:10px;letter-spacing:1.5px}
        .port-pill{fill:#e4f4fd;stroke:#2b90bd;stroke-opacity:.6;stroke-width:1}
        .port-text{fill:#1c6f96;font-size:9.5px;font-weight:700}
        .port-link{stroke:#2b90bd;stroke-opacity:.5;stroke-width:1.3;stroke-dasharray:3 4;fill:none}
        .dep{fill:none;stroke:#7d8598;stroke-width:1.6;stroke-dasharray:4 6;opacity:.85}
        .dep-label{fill:#5a6478;font-size:9px;paint-order:stroke;stroke:#eceff3;stroke-width:3.5px}
      `
    }
  };

  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[char]);

  // Titles are shown as authored. A leading `CDC -` used to be stripped on the
  // assumption the category chip already said it, but the database group now
  // mixes CDC and non-CDC patterns, so the prefix is the distinguishing part.
  function displayTitle(pattern) {
    return pattern.title;
  }

  function directionOf(pattern) {
    const tags = pattern.tags || [];
    return tags.includes("push") ? "push" : tags.includes("pull") ? "pull" : null;
  }

  // Description markup: `code` for keywords, **bold** for emphasis,
  // [[slug|label]] for a link to another pattern; the plain form (for catalog
  // cards) strips it back to prose.
  function formatDescInline(s) {
    return esc(s.replace(/\s*\n\s*/g, " "))
      // Descriptions are trusted authoring, like group.yaml intros: inline
      // [label](url) markdown renders as an external link.
      .replace(
        /\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,
        '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'
      )
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(
        /\[\[([a-z0-9-]+)\|([^\]]+)\]\]/g,
        '<button type="button" class="pattern-inline-link" data-pattern="$1">$2</button>'
      );
  }
  function plainDesc(s) {
    return String(s ?? "")
      .replace(/\[\[[a-z0-9-]+\|([^\]]+)\]\]/g, "$1")
      .replace(/\[([^\]]+)\]\([^)\s]+\)/g, "$1")
      .replace(/[`*]/g, "")
      .replace(/\s*\n\s*/g, " ")
      .trim();
  }

  // Resource-inspector value/table formatting.
  function valueText(value) {
    if (value === null) return "NULL";
    if (typeof value === "object") return JSON.stringify(value);
    return String(value);
  }
  function dataTable(columns, rows) {
    const header = columns.map((column) => `<th scope="col">${esc(column)}</th>`).join("");
    const body = rows.length
      ? rows.map((row) => `<tr>${row.map((value) => `<td${value === null ? ' class="empty-value"' : ""} title="${esc(valueText(value))}">${esc(valueText(value))}</td>`).join("")}</tr>`).join("")
      : `<tr><td class="empty-value" colspan="${Math.max(1, columns.length)}">No rows returned</td></tr>`;
    return `<div class="resource-table-wrap"><table class="resource-table"><thead><tr>${header}</tr></thead><tbody>${body}</tbody></table></div>`;
  }

  function patternGroupIcon(kind) {
    const clickhouse = '<g class="destination"><path d="M35 8v16M39 8v16M43 8v16M47 8v16M51 14v5"/></g>';
    const arrow = '<path class="group-arrow" d="M20 16h10m-3-3 3 3-3 3"/>';
    if (kind === "database") {
      return `<svg class="pattern-group-icon" viewBox="0 0 58 32" aria-hidden="true"><g class="source"><ellipse cx="10" cy="9" rx="6" ry="3"/><path d="M4 9v12c0 1.7 2.7 3 6 3s6-1.3 6-3V9M4 15c0 1.7 2.7 3 6 3s6-1.3 6-3"/></g>${arrow}${clickhouse}</svg>`;
    }
    if (kind === "s3") {
      // Object storage as a bucket (tapered pail) feeding ClickHouse.
      const bucket = '<g class="source"><ellipse cx="10" cy="8" rx="6.5" ry="2.5"/><path d="M3.5 8 6 24 Q10 26 14 24 L16.5 8"/></g>';
      return `<svg class="pattern-group-icon" viewBox="0 0 58 32" aria-hidden="true">${bucket}${arrow}${clickhouse}</svg>`;
    }
    if (kind === "clone") {
      return '<svg class="pattern-group-icon" viewBox="0 0 58 32" aria-hidden="true"><rect x="12" y="7" width="18" height="18" rx="3"/><rect x="24" y="11" width="18" height="18" rx="3"/></svg>';
    }
    if (kind === "transform") {
      // ClickHouse -> ClickHouse: the transform happens inside the database,
      // so there is no external source cylinder.
      const source = '<g class="destination"><path d="M5 8v16M9 8v16M13 8v16M17 8v16M21 14v5"/></g>';
      return `<svg class="pattern-group-icon" viewBox="0 0 58 32" aria-hidden="true">${source}${arrow}${clickhouse}</svg>`;
    }
    const kafka = '<g class="source kafka"><circle cx="9" cy="8" r="2"/><circle cx="9" cy="16" r="2.5"/><circle cx="9" cy="24" r="2"/><circle cx="16" cy="12" r="2"/><circle cx="16" cy="21" r="2"/><path d="M9 10v3.5m0 5v3.5m2-7 3-2m-3 5 3 2"/></g>';
    if (kind === "kafka-out") {
      return '<svg class="pattern-group-icon" viewBox="0 0 58 32" aria-hidden="true"><g class="destination"><path d="M5 8v16M9 8v16M13 8v16M17 8v16M21 14v5"/></g><path class="group-arrow" d="M25 16h10m-3-3 3 3-3 3"/><g class="source kafka" transform="translate(35)"><circle cx="7" cy="8" r="2"/><circle cx="7" cy="16" r="2.5"/><circle cx="7" cy="24" r="2"/><circle cx="14" cy="12" r="2"/><circle cx="14" cy="21" r="2"/><path d="M7 10v3.5m0 5v3.5m2-7 3-2m-3 5 3 2"/></g></svg>';
    }
    return `<svg class="pattern-group-icon" viewBox="0 0 58 32" aria-hidden="true">${kafka}${arrow}${clickhouse}</svg>`;
  }

  return {
    FLOW_COLORS, KIND_COLORS, KIND_LABELS, REPEAT, REPEAT_Y,
    INSPECTABLE_KINDS, TOPOLOGIES, DIRECTIONS, DIAGRAM_PALETTES,
    TOPOLOGY_PALETTES, esc,
    displayTitle, directionOf, formatDescInline, plainDesc,
    valueText, dataTable, patternGroupIcon
  };
})();
