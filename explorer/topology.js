// Pure SVG renderer for a pattern's physical topology: the Compose services
// behind its profiles, as returned by /api/topology. Input is that payload;
// output is an SVG string. Holds no app state.
//
// The logical diagram (diagram.js) draws data flow between ClickHouse
// resources. This one draws containers, the ports they publish to the host,
// the config files bound into them, and their startup dependencies. The two
// graphs are deliberately different: Compose knows startup order, not queries.
window.PE = window.PE || {};
window.PE.topology = (() => {
  "use strict";
  const { esc, TOPOLOGY_PALETTES } = window.PE.util;

  const CARD_WIDTH = 280;
  const COLUMN_GAP = 104;
  const ROW_GAP = 26;
  const TOP = 30;             // room above the cards for the boundary label
  const PAD = 34;
  const BOUNDARY_INSET = 20;
  const PORT_ROW = 26;        // height of the published-ports row inside a card
  const ROLE_ROW = 16;        // height of the optional role line (chp.role label)
  const CHAR = 6.05;          // monospace advance at 10px, used for truncation

  const theme = () => TOPOLOGY_PALETTES[document.documentElement.dataset.scheme === "light" ? "light" : "dark"];

  // Health drives the status dot; a container with no healthcheck reports only
  // its run status, so "running" alone is treated as healthy-enough (blue).
  const STATE_COLORS = {
    healthy: "#3ed598", running: "#4cc3f7", starting: "#f6b73c",
    unhealthy: "#f4676b", exited: "#8b93ad", created: "#8b93ad"
  };

  function stateOf(service) {
    const state = service.state;
    if (!state) return { label: "not created", color: "#8b93ad", running: false };
    const key = state.health || state.status;
    return {
      label: state.health ? `${state.status} · ${state.health}` : state.status,
      color: STATE_COLORS[key] || "#8b93ad",
      running: state.status === "running"
    };
  }

  function truncate(value, width) {
    const limit = Math.floor(width / CHAR);
    const text = String(value ?? "");
    return text.length <= limit ? text : `${text.slice(0, Math.max(1, limit - 1))}…`;
  }

  // Bind mounts are the interesting part of this stack: they are what turn a
  // stock image into a configured node. Show the repo-relative source and the
  // leaf of the container path, which is enough to identify the file.
  function mountLine(mount) {
    const target = mount.target.split("/").filter(Boolean).slice(-2).join("/");
    if (mount.type !== "bind") return `volume ${mount.source || "(anonymous)"} → ${target}`;
    return `${mount.source} → ${target}${mount.read_only ? " (ro)" : ""}`;
  }

  // What the container is for, when the image and service name do not say it.
  // The PeerDB stack runs two Postgres containers with unrelated jobs.
  function roleSvg(service, box, inner) {
    if (!service.role) return "";
    return `<text x="${box.x + 13}" y="${box.y + 55}" class="service-role">${esc(truncate(service.role, inner))}</text>`;
  }

  function serviceLines(service) {
    const lines = [];
    (service.mounts || []).slice(0, 3).forEach((mount) => lines.push(["mount", mountLine(mount)]));
    if ((service.mounts || []).length > 3) {
      lines.push(["", `+${service.mounts.length - 3} more mounts`]);
    }
    if (service.command) lines.push(["cmd", service.command]);
    if (service.healthcheck) lines.push(["check", service.healthcheck]);
    return lines;
  }

  function cardHeight(service) {
    const ports = service.ports?.length ? PORT_ROW : 0;
    const role = service.role ? ROLE_ROW : 0;
    return 52 + role + ports + serviceLines(service).length * 13 + 20;
  }

  // Rank by startup dependency: a service sits one column right of everything
  // it waits for. Compose rejects cyclic depends_on, so this always terminates.
  function ranks(services, edges) {
    const rank = Object.fromEntries(services.map((service) => [service.name, 0]));
    for (let pass = 0; pass <= services.length; pass += 1) {
      let changed = false;
      edges.forEach((edge) => {
        if (rank[edge.source] === undefined || rank[edge.target] === undefined) return;
        if (rank[edge.source] + 1 > rank[edge.target]) {
          rank[edge.target] = rank[edge.source] + 1;
          changed = true;
        }
      });
      if (!changed) break;
    }
    return rank;
  }

  function layout(services, edges) {
    const rank = ranks(services, edges);
    const columns = new Map();
    services.forEach((service) => {
      const column = rank[service.name];
      if (!columns.has(column)) columns.set(column, []);
      columns.get(column).push(service);
    });
    const boxes = {};
    let contentBottom = 0;
    [...columns.keys()].sort((a, b) => a - b).forEach((column) => {
      const items = columns.get(column).sort((a, b) => a.name.localeCompare(b.name));
      const x = PAD + column * (CARD_WIDTH + COLUMN_GAP);
      let y = TOP + 34;   // clears the boundary label
      items.forEach((service) => {
        const height = cardHeight(service);
        boxes[service.name] = { x, y, width: CARD_WIDTH, height };
        y += height + ROW_GAP;
        contentBottom = Math.max(contentBottom, y);
      });
    });
    const width = PAD * 2 + (columns.size - 1) * (CARD_WIDTH + COLUMN_GAP) + CARD_WIDTH;
    return { boxes, width, height: contentBottom - ROW_GAP + 34 };
  }

  function cardSvg(service, box) {
    const state = stateOf(service);
    const lines = serviceLines(service);
    const inner = CARD_WIDTH - 26;
    const roleRow = service.role ? ROLE_ROW : 0;
    const portRow = service.ports?.length ? PORT_ROW : 0;
    const body = lines.map(([key, value], index) => {
      const y = box.y + 52 + roleRow + portRow + index * 13;
      const prefix = key ? `<tspan class="key">${esc(key)} </tspan>` : "";
      const room = inner - (key.length + 1) * CHAR;
      return `<text x="${box.x + 13}" y="${y}" class="service-line">${prefix}${esc(truncate(value, room))}</text>`;
    }).join("");
    const stateY = box.y + box.height - 11;
    const stateLabel = state.label + (service.state ? ` · ${service.state.container}` : "");
    return `<g class="topology-service" data-service="${esc(service.name)}">
      <rect x="${box.x}" y="${box.y}" width="${box.width}" height="${box.height}" rx="12" class="card${state.running ? "" : " stopped"}"/>
      <circle cx="${box.x + 15}" cy="${box.y + 19}" r="4.5" fill="${state.color}"/>
      <text x="${box.x + 27}" y="${box.y + 23}" class="service-name">${esc(service.name)}</text>
      <text x="${box.x + 13}" y="${box.y + 39}" class="service-image">${esc(truncate(service.image, inner))}</text>
      ${roleSvg(service, box, inner)}
      ${portsSvg(service, box)}
      ${body}
      <text x="${box.x + 13}" y="${stateY}" class="service-line">${esc(truncate(stateLabel, inner))}</text>
    </g>`;
  }

  const CONDITION_LABELS = {
    service_healthy: "waits for healthy",
    service_completed_successfully: "waits for exit 0",
    service_started: "waits for start"
  };

  // Labels sit in the gutter just left of the target rather than at the edge's
  // midpoint: a dependency that skips columns would otherwise land its label on
  // top of an unrelated card. One label per target and condition, since several
  // services often wait on the same node for the same reason.
  function dependenciesSvg(edges, boxes) {
    const paths = [];
    const labels = [];
    const labelled = new Set();
    edges.forEach((edge) => {
      const source = boxes[edge.source], target = boxes[edge.target];
      if (!source || !target) return;
      const x1 = source.x + source.width, y1 = source.y + source.height / 2;
      const x2 = target.x - 9, y2 = target.y + target.height / 2;
      const bend = Math.max(34, (x2 - x1) * 0.45);
      paths.push(`<path d="M ${x1},${y1} C ${x1 + bend},${y1} ${x2 - bend},${y2} ${x2},${y2}" class="dep" marker-end="url(#topology-arrow)"/>`);
      const key = `${edge.target}|${edge.condition}`;
      if (labelled.has(key)) return;
      labelled.add(key);
      // A service can wait on several others under different conditions; those
      // labels share one anchor, so stack them instead of overprinting.
      const stack = [...labelled].filter((item) => item.startsWith(`${edge.target}|`)).length - 1;
      const label = CONDITION_LABELS[edge.condition] || edge.condition;
      labels.push(`<text x="${x2 - 6}" y="${y2 - 9 - stack * 12}" text-anchor="end" class="dep-label">${esc(label)}</text>`);
    });
    return { paths: paths.join(""), labels: labels.join("") };
  }

  // Published ports are the pattern's only host-visible surface, and the detail
  // the logical diagram cannot show. They are drawn as pills inside the card
  // that publishes them: an earlier version put them in a host band with lines
  // routed down to each container, which became unreadable as soon as several
  // services published ports.
  function portsSvg(service, box) {
    if (!service.ports?.length) return "";
    const y = box.y + 46;
    const parts = [`<text x="${box.x + 13}" y="${y + 13}" class="service-line"><tspan class="key">host</tspan></text>`];
    const limit = box.x + box.width - 10;
    let cursor = box.x + 13 + 5 * CHAR;
    let dropped = 0;
    service.ports.forEach((port) => {
      const label = `${port.host} → ${port.container}`;
      const width = label.length * CHAR + 14;
      // A row that would overflow the card is counted rather than clipped, so a
      // service publishing many ports never silently loses some.
      if (dropped || cursor + width > limit) { dropped += 1; return; }
      parts.push(`<rect x="${cursor}" y="${y}" width="${width}" height="18" rx="9" class="port-pill"/>
        <text x="${cursor + width / 2}" y="${y + 12.5}" text-anchor="middle" class="port-text">${esc(label)}</text>`);
      cursor += width + 6;
    });
    if (dropped) {
      parts.push(`<text x="${cursor}" y="${y + 13}" class="service-line">+${dropped}</text>`);
    }
    return parts.join("");
  }

  function topologySvg(payload) {
    const services = payload.services || [];
    if (!services.length) return "";
    const edges = payload.edges || [];
    const { boxes, width, height } = layout(services, edges);
    const dependencies = dependenciesSvg(edges, boxes);
    const network = payload.networks?.[0]?.name || "default";
    const boundaryTop = TOP - 20;
    const inset = PAD - BOUNDARY_INSET;
    const boundary = `<g>
      <rect x="${inset}" y="${boundaryTop}" width="${width - inset * 2}" height="${height - boundaryTop - 12}" rx="18" class="boundary"/>
      <text x="${inset + 14}" y="${boundaryTop + 17}" class="boundary-label">NETWORK · ${esc(network.toUpperCase())} · HOST PORTS PUBLISHED TO 127.0.0.1</text>
    </g>`;
    const arrowColor = document.documentElement.dataset.scheme === "light" ? "#7d8598" : "#8b93ad";
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="Container topology for ${esc(payload.pattern || "this pattern")}">
      <defs><marker id="topology-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="${arrowColor}"/></marker></defs>
      <style>${theme().style}</style>
      ${boundary}
      <g class="dependency-layer">${dependencies.paths}</g>
      <g class="service-layer">${services.map((service) => cardSvg(service, boxes[service.name])).join("")}</g>
      <g class="annotation-layer">${dependencies.labels}</g>
    </svg>`;
  }

  return { render: topologySvg };
})();
