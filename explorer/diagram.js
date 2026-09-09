// Pure SVG renderer for a pattern's resource graph. Input: a pattern with a
// parsed `graph`; output: an SVG string. Holds no app state; whether nodes are
// inspectable is injected via render(pattern, { inspectable }).
window.PE = window.PE || {};
window.PE.diagram = (() => {
  "use strict";
  const {
    esc, FLOW_COLORS, KIND_COLORS, KIND_LABELS, INSPECTABLE_KINDS, REPEAT, REPEAT_Y,
    DIAGRAM_PALETTES, SCHEMATIC_PALETTES, SHAPE_LABELS, shapeOf
  } = window.PE.util;
  // Palette is read at render time so a scheme switch re-renders with the new colors.
  const palette = () => DIAGRAM_PALETTES[document.documentElement.dataset.scheme === "light" ? "light" : "dark"];

  // Split a system's node positions into runs separated by a wide gap, so a
  // system appearing on both sides of another one draws a box per run instead of
  // a single box spanning the systems in between.
  // `pitch` is the spacing between adjacent columns, which varies with graph
  // depth, so the split threshold has to be derived from it rather than fixed:
  // only a genuinely skipped column starts a new box.
  function clusterXs(values, pitch) {
    const sorted = [...values].sort((a, b) => a - b);
    const clusters = [];
    sorted.forEach((x) => {
      const last = clusters.at(-1);
      if (!last || x - last.at(-1) > pitch * 1.5) clusters.push([x]);
      else last.push(x);
    });
    return clusters;
  }

  // The distance between neighbouring columns, taken from the positions
  // themselves so it stays in step with layout().
  function columnPitch(positions) {
    const xs = [...new Set(Object.values(positions).map(([x]) => x))].sort((a, b) => a - b);
    const gaps = xs.slice(1).map((x, i) => x - xs[i]);
    return gaps.length ? Math.min(...gaps) : Infinity;
  }

  function ranks(graph) {
    const result = Object.fromEntries(graph.resources.map((resource) => [resource.key, 0]));
    for (let pass = 0; pass <= graph.resources.length; pass += 1) {
      let changed = false;
      graph.connections.forEach((edge) => {
        const next = result[edge.source] + 1;
        if (next > result[edge.target]) { result[edge.target] = next; changed = true; }
      });
      if (!changed) return result;
    }
    throw new Error("The resource graph contains a cycle");
  }

  function layout(graph) {
    const rank = ranks(graph);
    const maxRank = Math.max(1, ...Object.values(rank));
    const groups = new Map();
    const resourceFlows = new Map(graph.resources.map((item) => [item.key, new Set()]));
    graph.connections.forEach((edge) => {
      resourceFlows.get(edge.source).add(edge.flow);
      resourceFlows.get(edge.target).add(edge.flow);
    });
    graph.resources.forEach((resource) => {
      if (!groups.has(rank[resource.key])) groups.set(rank[resource.key], []);
      groups.get(rank[resource.key]).push(resource);
    });
    const positions = {};
    groups.forEach((resources, column) => {
      resources.sort((a, b) => {
        const score = (item) => {
          const flows = resourceFlows.get(item.key);
          if (flows.size === 1 && flows.has("snapshot")) return 0;
          if (flows.size === 1 && flows.has("changes")) return 1;
          if (flows.size === 1 && flows.has("query")) return 4;
          if (flows.has("query")) return 3;
          return 2;
        };
        return score(a) - score(b) || a.key.localeCompare(b.key);
      });
      // Long CDC pipelines need room for actor and operation labels. Keep
      // shorter graphs compact and expand the SVG for deeper graphs.
      const columnGap = Math.max(790 / maxRank, 220);
      const x = 325 + columnGap * column;
      let ys;
      if (resources.length === 1) ys = [275 + (column % 2 ? 18 : -8)];
      else {
        // Nodes used to be spread across a fixed span regardless of how many
        // there were, so three in one column got a 78px pitch and their labels
        // ran into the cube below. Keep the two-node spacing exactly as it was
        // and give anything denser a pitch that clears a cube plus its labels;
        // the canvas grows to fit in diagramSvg.
        const span = column === 0 ? 225 : 155;
        const top = column === 0 ? 205 : 260;
        const pitch = Math.max(span / (resources.length - 1), MIN_ROW_PITCH);
        const total = pitch * (resources.length - 1);
        const start = Math.max(top, top + span / 2 - total / 2);
        ys = resources.map((_, i) => start + i * pitch);
      }
      resources.forEach((resource, index) => {
        let y = ys[index];
        if (resource.kind === "topic") y = Math.max(y, 250);
        positions[resource.key] = [x, y];
      });
    });
    return positions;
  }

  // A cube is 68px tall above its anchor and its name/kind labels run to about
  // 82px below it, so anything under ~155px of pitch overlaps.
  const MIN_ROW_PITCH = 155;

  function instances(resource, position, flow) {
    if (!["shards", "replicas"].includes(resource.scope)) return [position];
    const positions = [[position[0] - REPEAT, position[1] - REPEAT_Y], [position[0] + REPEAT, position[1] + REPEAT_Y]];
    return resource.scope === "replicas" && flow !== "query" ? positions.slice(0, 1) : positions;
  }

  function cube(resource, x, y, offset = 0, glow = true) {
    const [top, right, left] = KIND_COLORS[resource.kind] || ["#cbd5e1", "#8190a8", "#566278"];
    const width = 62, depth = 32, height = resource.kind === "client" ? 52 : 68;
    const cx = x + offset, base = y + offset * 0.42, topY = base - height;
    return `<g${glow ? ' filter="url(#glow)"' : ""}>
      <polygon points="${cx-width/2},${topY+depth/2} ${cx},${topY} ${cx+width/2},${topY+depth/2} ${cx},${topY+depth}" fill="${top}"/>
      <polygon points="${cx-width/2},${topY+depth/2} ${cx},${topY+depth} ${cx},${base+depth} ${cx-width/2},${base+depth/2}" fill="${left}"/>
      <polygon points="${cx},${topY+depth} ${cx+width/2},${topY+depth/2} ${cx+width/2},${base+depth/2} ${cx},${base+depth}" fill="${right}"/>
    </g>`;
  }

  function resourceSvg(resource, position, layer, inspectable) {
    const [x, y] = position;
    const repeated = ["shards", "replicas"].includes(resource.scope);
    const failoverGroup = resource.kind === "consumer-group";
    let cubes = cube(resource, x, y);
    let instanceLabels = "";
    if (failoverGroup) {
      const assigned = -25, unassigned = 25;
      const assignedLabel = (resource.properties?.member1 || "ASSIGNED").toUpperCase();
      const unassignedLabel = (resource.properties?.member2 || "UNASSIGNED").toUpperCase();
      cubes = cube(resource, x, y, unassigned, false) + cube(resource, x, y, assigned, true);
      instanceLabels = `<text x="${x+assigned}" y="${y+assigned*.42-48}" text-anchor="middle" class="instance assigned-label">${esc(assignedLabel)}</text>
        <text x="${x+unassigned}" y="${y+unassigned*.42-48}" text-anchor="middle" class="instance unassigned-label">${esc(unassignedLabel)}</text>`;
    } else if (repeated) {
      const secondary = cube(resource, x, y, REPEAT, false);
      cubes = `${resource.scope === "replicas" ? '<g class="ghost-replica">' : ""}${secondary}${resource.scope === "replicas" ? "</g>" : ""}` + cube(resource, x, y, -REPEAT, true);
      instanceLabels = [-REPEAT, REPEAT].map((offset, index) =>
        `<text x="${x+offset}" y="${y+offset*.42-48}" text-anchor="middle" class="instance">${resource.scope === "replicas" ? "REPLICA" : "SHARD"} ${index+1}</text>`
      ).join("");
    }
    const displayName = resource.properties?.label || resource.name;
    const kind = KIND_LABELS[resource.kind] || resource.kind.replaceAll("-", " ");
    const scope = resource.scope ? ` · ${resource.scope}` : "";
    const details = Object.entries(resource.properties || {})
      // `table` names the resource for live inspection; drawing it under a
      // label that already shows the same name is pure duplication.
      .filter(([key, value]) => key !== "label" && key !== "note" && !(key === "table" && value === displayName) && (!failoverGroup || !["member1", "member2"].includes(key)))
      .map(([key, value]) => `${key.replaceAll("-", " ")} ${value}`);
    if (repeated) details.push(`2 ${resource.scope}`);
    const detailSpans = details.map((detail, index) =>
      `<tspan x="${x}" dy="${index ? 12 : 0}">${esc(detail)}</tspan>`
    ).join("");
    const labelY = y + 62;
    const note = resource.properties?.note;
    if (layer === "geometry") {
      const replicaLink = resource.scope === "replicas"
        ? `<path d="M ${x-34},${y+19} Q ${x},${y+46} ${x+34},${y+19}" class="replica-sync" marker-start="url(#arrow-replication)" marker-end="url(#arrow-replication)"/>`
        : "";
      const readableResource = INSPECTABLE_KINDS.has(resource.kind);
      const nodeInspectable = readableResource && inspectable;
      const noteBadge = note
        ? `<g class="note-badge" aria-hidden="true"><circle cx="${x+30}" cy="${y-44}" r="7.5"/><text x="${x+30}" y="${y-40.5}" text-anchor="middle">i</text></g>`
        : "";
      return `<g class="resource${nodeInspectable ? " inspectable-resource" : ""}${note ? " has-note" : ""}" id="resource-${esc(resource.key)}"${readableResource ? ` data-readable-resource-key="${esc(resource.key)}"` : ""}${note ? ` data-note="${esc(note)}"` : ""}${nodeInspectable ? ` data-resource-key="${esc(resource.key)}" tabindex="0" role="button" aria-label="Inspect ${esc(displayName)}"` : ""}>
        ${nodeInspectable ? `<title>Inspect live definition and rows for ${esc(displayName)}</title>` : ""}
        <ellipse cx="${x}" cy="${y+33}" rx="${repeated || failoverGroup ? 70 : 48}" ry="12" fill="${palette().nodeShadow}" filter="url(#blur)"/>
        ${replicaLink}${cubes}${noteBadge}
      </g>`;
    }
    return `<g class="resource-labels" aria-hidden="true">
      ${instanceLabels}
      <text x="${x}" y="${labelY}" text-anchor="middle" class="resource-name">${esc(displayName)}</text>
      <text x="${x}" y="${labelY+17}" text-anchor="middle" class="resource-kind">${esc(kind + scope)}</text>
      ${details.length ? `<text x="${x}" y="${labelY+33}" text-anchor="middle" class="resource-detail">${detailSpans}</text>` : ""}
    </g>`;
  }

  function edgePath(source, target, offset, sourcePadding, targetPadding) {
    let [x1, y1] = source, [x2, y2] = target;
    x1 += sourcePadding; x2 -= targetPadding; y1 += offset - 19; y2 += offset - 19;
    const bend = Math.max(48, Math.abs(x2 - x1) * .42);
    return `M ${x1},${y1} C ${x1+bend},${y1} ${x2-bend},${y2} ${x2},${y2}`;
  }

  function edgeLabelSvg(label, x, y, maxChars = 32) {
    if (label.length <= maxChars) {
      return `<text x="${x}" y="${y}" text-anchor="middle" class="edge-label">${esc(label)}</text>`;
    }
    const lines = [];
    label.split(/\s+/).forEach((word) => {
      const current = lines.at(-1);
      if (!current || `${current} ${word}`.length > maxChars) lines.push(word);
      else lines[lines.length - 1] = `${current} ${word}`;
    });
    const startY = y - (lines.length - 1) * 6;
    const spans = lines.map((line, index) => `<tspan x="${x}" dy="${index ? 13 : 0}">${esc(line)}</tspan>`).join("");
    return `<text x="${x}" y="${startY}" text-anchor="middle" class="edge-label">${spans}</text>`;
  }

  function clickHouseMark(x, y) {
    return `<g transform="translate(${x} ${y})" fill="${palette().icon}"><rect width="4" height="26"/><rect x="7" width="4" height="26"/><rect x="14" width="4" height="26"/><rect x="21" width="4" height="26"/><rect x="28" y="9" width="4" height="8"/></g>`;
  }

  function kafkaMark(x, y) {
    return `<g transform="translate(${x} ${y})" fill="none" stroke="${palette().icon}" stroke-width="2.3"><path d="M7 5v4M7 16v4M10 11l4-3M10 14l4 3"/><circle cx="7" cy="3" r="2"/><circle cx="7" cy="12.5" r="3"/><circle cx="7" cy="22" r="2"/><circle cx="16" cy="7" r="2.5"/><circle cx="16" cy="18" r="2.5"/></g>`;
  }

  function databaseToClickHouseMark(x, y) {
    return `<g transform="translate(${x} ${y})" fill="none" stroke="${palette().icon}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-label="Database changes to ClickHouse"><title>Database changes to ClickHouse</title><ellipse cx="5" cy="5" rx="4" ry="2.2"/><path d="M1 5v11c0 1.3 1.8 2.2 4 2.2s4-.9 4-2.2V5M1 10.5c0 1.3 1.8 2.2 4 2.2s4-.9 4-2.2"/><path d="M10.5 11.5h4.5m-2-2 2 2-2 2"/><path d="M17 4v15M20.5 4v15M24 4v15M27.5 9v5" stroke-width="2.3"/></g>`;
  }

  function externalMark(kind, x, y, system = "") {
    if (kind === "connector" && system.toLowerCase() === "kafka connect") {
      return kafkaMark(x, y);
    }
    if (kind === "connector" && system.toLowerCase() === "altinity cdc") {
      return databaseToClickHouseMark(x, y);
    }
    if (kind === "postgres" || kind === "mysql") {
      return `<g transform="translate(${x} ${y})" fill="none" stroke="${palette().icon}" stroke-width="1.8"><ellipse cx="10" cy="5" rx="7" ry="3.5"/><path d="M3 5v14c0 2 3.1 3.5 7 3.5s7-1.5 7-3.5V5M3 12c0 2 3.1 3.5 7 3.5s7-1.5 7-3.5"/></g>`;
    }
    if (kind === "minio") {
      return `<g transform="translate(${x} ${y})" fill="none" stroke="${palette().icon}" stroke-width="1.8"><path d="M3 8h20l-2 14H5zM7 8V4h12v4M8 13h10"/></g>`;
    }
    if (kind === "connector") {
      return `<g transform="translate(${x} ${y})" fill="none" stroke="${palette().icon}" stroke-width="1.8"><path d="M6 3v6m8-6v6M3 9h14v4a7 7 0 0 1-7 7v3m0 0h7"/></g>`;
    }
    return `<g transform="translate(${x} ${y})" fill="none" stroke="${palette().icon}" stroke-width="1.8"><circle cx="7" cy="13" r="4"/><circle cx="20" cy="13" r="4"/><path d="M11 13h5m-2-3 3 3-3 3"/></g>`;
  }

  function diagramSvg(pattern, { inspectable = false } = {}) {
    const graph = pattern.graph;
    const positions = layout(graph);
    const pitch = columnPitch(positions);
    const diagramWidth = Math.max(1400, ...Object.values(positions).map(([x]) => x + 235));
    // Boundary boxes and the viewBox were fixed at 420/510, which clipped any
    // column tall enough to need more than two rows.
    const lowestNode = Math.max(...Object.values(positions).map(([, y]) => y));
    const boundaryHeight = Math.max(420, lowestNode + 95 - 85);
    const diagramHeight = Math.max(510, boundaryHeight + 30);
    const resources = Object.fromEntries(graph.resources.map((resource) => [resource.key, resource]));
    const pairCounts = new Map();
    graph.connections.forEach((edge) => {
      const key = `${edge.source}|${edge.target}`;
      pairCounts.set(key, (pairCounts.get(key) || 0) + 1);
    });
    const pairIndexes = new Map();
    const paths = [];
    const edgeLabels = [];
    const labelledOperations = new Set();
    graph.connections.forEach((edge, edgeIndex) => {
      const pair = `${edge.source}|${edge.target}`;
      const lane = pairIndexes.get(pair) || 0;
      pairIndexes.set(pair, lane + 1);
      const pairOffset = (lane - (pairCounts.get(pair) - 1) / 2) * 13;
      const flowOffset = edge.flow === "snapshot" ? -16 : edge.flow === "changes" ? 16 : 0;
      const offset = pairOffset + flowOffset;
      const sourceInstances = instances(resources[edge.source], positions[edge.source], edge.flow);
      const targetInstances = instances(resources[edge.target], positions[edge.target], edge.flow);
      let routes;
      if (sourceInstances.length === targetInstances.length) routes = sourceInstances.map((source, i) => [source, targetInstances[i]]);
      else if (sourceInstances.length > 1) routes = sourceInstances.map((source) => [source, targetInstances[0]]);
      else routes = targetInstances.map((target) => [sourceInstances[0], target]);
      routes.forEach(([source, target], routeIndex) => {
        const id = `edge-${edgeIndex}-${routeIndex}`;
        const color = FLOW_COLORS[edge.flow] || "#8b93ad";
        const d = edgePath(source, target, offset, sourceInstances.length > 1 ? 30 : 37, targetInstances.length > 1 ? 30 : 37);
        const startMarker = edge.flow === "query" ? ' marker-start="url(#arrow-query)"' : "";
        paths.push(`<path id="${id}" d="${d}" class="edge" stroke="${color}"${startMarker} marker-end="url(#arrow-${edge.flow in FLOW_COLORS ? edge.flow : "default"})"/>
          <circle r="3.2" fill="${color}" class="packet"><animateMotion dur="${2.2 + edgeIndex*.13}s" begin="-${edgeIndex*.31 + routeIndex*.16}s" repeatCount="indefinite"><mpath href="#${id}"/></animateMotion></circle>`);
      });
      const labelKey = `${edge.source}|${edge.label || ""}`;
      if (edge.label && !labelledOperations.has(labelKey)) {
        labelledOperations.add(labelKey);
        const [x1, y1] = positions[edge.source], [x2, y2] = positions[edge.target];
        const repeated = targetInstances.length > 1;
        const laneOffset = edge.flow === "snapshot" ? -42 : edge.flow === "changes" ? 28 : 0;
        let labelY = (y1+y2)/2-42+offset+laneOffset;
        if (edge.flow === "changes" && edge.label.length > 24) labelY = Math.max(y1, y2) + 20;
        const labelX = (x1+x2)/2-(repeated?34:0);
        edgeLabels.push(edgeLabelSvg(edge.label, labelX, labelY));
      }
    });

    const ch = graph.resources.filter((item) => ["kafka-table","mv","refreshable-mv","distributed","mergetree","replicated-mergetree","part","keepermap","consumer-group","remote-table"].includes(item.kind));
    const topics = graph.resources.filter((item) => item.kind === "topic");
    const topicXs = topics.map((item) => positions[item.key][0]).sort((a, b) => a - b);
    const external = graph.resources.filter((item) => ["postgres", "mysql", "peerdb", "minio", "connector"].includes(item.kind));
    const externalXs = external.map((item) => positions[item.key][0]);
    const chXs = ch.map((item) => positions[item.key][0]);
    let boundaries = "";
    if (ch.length) {
      const outsideXs = [...topicXs, ...externalXs];
      // A system whose nodes sit on both sides of another system (this pattern
      // reads from an S3 prefix and writes back into it) would otherwise draw one
      // box swallowing everything between. Split on gaps and box each run.
      clusterXs(chXs, pitch).forEach((cluster, index) => {
        const minCh = Math.min(...cluster), maxCh = Math.max(...cluster);
        // Clamp against this system's other clusters too, or two boxes of the
        // same system each reach toward the far side and overlap each other.
        const neighbours = [...outsideXs, ...chXs.filter((x) => x < minCh || x > maxCh)];
        const leftTopics = neighbours.filter((x) => x < minCh);
        const rightTopics = neighbours.filter((x) => x > maxCh);
        let min = minCh - 92, max = maxCh + 105;
        if (leftTopics.length) min = Math.max(min, (Math.max(...leftTopics) + minCh) / 2 + 6);
        if (rightTopics.length) max = Math.min(max, (maxCh + Math.min(...rightTopics)) / 2 - 6);
        const label = `${clickHouseMark(min+14,101)}<text x="${min+54}" y="121" class="boundary-label">CLICKHOUSE · ${esc(pattern.topology.toUpperCase())}</text>`;
        boundaries += `<g><rect x="${min}" y="85" width="${max-min}" height="${boundaryHeight}" rx="23" class="system clickhouse"/>${label}</g>`;
      });
    }
    if (topics.length) {
      const groups = [];
      topicXs.forEach((x) => {
        const group = groups.at(-1);
        if (!group || x - group.at(-1) > 220) groups.push([x]);
        else group.push(x);
      });
      groups.forEach((group) => {
        let min = Math.min(...group) - 72, max = Math.max(...group) + 92;
        if (chXs.length) {
          const minCh = Math.min(...chXs), maxCh = Math.max(...chXs);
          if (Math.max(...group) < minCh) max = Math.min(max, (Math.max(...group) + minCh) / 2 - 6);
          else if (Math.min(...group) > maxCh) min = Math.max(min, (maxCh + Math.min(...group)) / 2 + 6);
        }
        boundaries += `<g><rect x="${min}" y="85" width="${max-min}" height="245" rx="21" class="system kafka"/>${kafkaMark(min+14,99)}<text x="${min+47}" y="121" class="boundary-label">KAFKA CLUSTER</text></g>`;
      });
    }
    const externalInfo = {
      postgres: ["POSTGRES", "postgres-system"],
      mysql: ["MYSQL", "mysql-system"],
      peerdb: ["PEERDB", "peerdb-system"],
      minio: ["MINIO · S3", "minio-system"],
      connector: ["CONNECTOR", "connector-system"]
    };
    const externalGroups = new Map();
    external.forEach((resource) => {
      if (!externalGroups.has(resource.kind)) externalGroups.set(resource.kind, []);
      externalGroups.get(resource.kind).push(resource);
    });
    externalGroups.forEach((items, kind) => {
      const otherXs = [...external, ...ch]
        .filter((item) => item.kind !== kind)
        .map((item) => positions[item.key][0]);
      const ownXs = items.map((item) => positions[item.key][0]);
      clusterXs(ownXs, pitch).forEach((cluster, index) => {
        const lo = Math.min(...cluster), hi = Math.max(...cluster);
        let min = lo - 72, max = hi + 72;
        // Same-system clusters bound each other, as with the ClickHouse boxes.
        const neighbours = [...otherXs, ...ownXs.filter((x) => x < lo || x > hi)];
        const left = neighbours.filter((value) => value < min);
        const right = neighbours.filter((value) => value > max);
        if (left.length) min = Math.max(min, (Math.max(...left) + lo) / 2 + 4);
        if (right.length) max = Math.min(max, (hi + Math.min(...right)) / 2 - 4);
        let [label, className] = externalInfo[kind];
        let labelOffset = 43;
        if (kind === "connector") {
          const system = items[0].properties.system || label;
          label = system.toLowerCase() === "kafka connect" ? "CONNECT" : system.toUpperCase();
          if (system.toLowerCase() === "altinity cdc") labelOffset = 49;
        }
        const id = index === 0 ? `system-${kind}` : `system-${kind}-${index}`;
        boundaries += `<g id="${id}"><rect x="${min}" y="85" width="${max-min}" height="${boundaryHeight}" rx="18" class="system ${className}"/>${externalMark(kind,min+12,99,items[0].properties.system || "")}<text x="${min+labelOffset}" y="121" class="boundary-label">${label}</text></g>`;
      });
    });
    const markers = Object.entries({...FLOW_COLORS, default: "#8b93ad"}).map(([name, color]) =>
      `<marker id="arrow-${name}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="${color}"/></marker>`
    ).join("");
    // The isometric floor grid was removed: its width scaled with the diagram
    // while its height stayed fixed, so wide diagrams distorted the rhombus and
    // its grid lines. Cube shadows + boundary boxes carry the depth instead.
    const grid = "";
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 55 ${diagramWidth} ${diagramHeight}" role="img" aria-label="${esc(pattern.title)} architecture">
      <defs>${markers}<filter id="glow" x="-80%" y="-80%" width="260%" height="260%"><feGaussianBlur stdDeviation="5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter><filter id="blur"><feGaussianBlur stdDeviation="8"/></filter></defs>
      <style>${palette().style}</style>
      ${grid}${boundaries}
      <g class="edge-layer">${paths.join("")}</g>
      <g class="resource-layer">${graph.resources.map((resource) => resourceSvg(resource, positions[resource.key], "geometry", inspectable)).join("")}</g>
      <g class="annotation-layer">${edgeLabels.join("")}${graph.resources.map((resource) => resourceSvg(resource, positions[resource.key], "labels", inspectable)).join("")}</g>
    </svg>`;
  }


  // ===================== TYPED VIEW =====================
  // A second renderer over the same graph: instead of one isometric cube per
  // resource, each node is drawn in the silhouette of its kind (table, topic,
  // processor, reader, client, store), so the diagram carries its types in its
  // shapes rather than in color alone. Same node attributes as the isometric
  // renderer, so inspection, notes and the modal work unchanged.
  const T = { W: 178, H: 106, HGAP: 188, VGAP: 40, LEFT: 44, TOP: 122 };
  const schematicPalette = () => SCHEMATIC_PALETTES[document.documentElement.dataset.scheme === "light" ? "light" : "dark"];

  function clip(text, max) {
    const value = String(text ?? "");
    return value.length > max ? `${value.slice(0, max - 1)}…` : value;
  }

  // Same column ordering as the isometric view, so the two views place a
  // pattern's resources in the same reading order.
  function columnOrder(graph) {
    const rank = ranks(graph);
    const resourceFlows = new Map(graph.resources.map((item) => [item.key, new Set()]));
    graph.connections.forEach((edge) => {
      resourceFlows.get(edge.source).add(edge.flow);
      resourceFlows.get(edge.target).add(edge.flow);
    });
    const columns = new Map();
    graph.resources.forEach((resource) => {
      const column = rank[resource.key];
      if (!columns.has(column)) columns.set(column, []);
      columns.get(column).push(resource);
    });
    columns.forEach((resources) => resources.sort((a, b) => {
      const score = (item) => {
        const flows = resourceFlows.get(item.key);
        if (flows.size === 1 && flows.has("snapshot")) return 0;
        if (flows.size === 1 && flows.has("changes")) return 1;
        if (flows.size === 1 && flows.has("query")) return 4;
        if (flows.has("query")) return 3;
        return 2;
      };
      return score(a) - score(b) || a.key.localeCompare(b.key);
    }));
    return columns;
  }

  function schematicLayout(graph) {
    const columns = columnOrder(graph);
    const tallest = Math.max(...[...columns.values()].map((items) => items.length));
    const columnHeight = tallest * T.H + (tallest - 1) * T.VGAP;
    const positions = {};
    [...columns.keys()].sort((a, b) => a - b).forEach((column) => {
      const items = columns.get(column);
      const height = items.length * T.H + (items.length - 1) * T.VGAP;
      const top = T.TOP + (columnHeight - height) / 2;
      items.forEach((resource, index) => {
        positions[resource.key] = [T.LEFT + column * (T.W + T.HGAP), top + index * (T.H + T.VGAP)];
      });
    });
    return positions;
  }

  // Silhouettes. Every shape fills the same box, so text placement and edge
  // anchors stay identical across kinds. `attrs` carries the paint, so one
  // outline can be drawn twice: an opaque base that hides edges passing behind
  // the node, then the tinted face on top.
  function schematicSilhouette(shape, x, y, attrs) {
    const w = T.W, h = T.H;
    if (shape === "processor") {
      return `<rect ${attrs} x="${x}" y="${y}" width="${w}" height="${h}" rx="26"/>`;
    }
    if (shape === "topic") {
      return `<path ${attrs} d="M ${x + 5},${y} H ${x + w - 26} A 26,26 0 0 1 ${x + w},${y + 26}`
        + ` V ${y + h - 26} A 26,26 0 0 1 ${x + w - 26},${y + h} H ${x + 5}`
        + ` A 5,5 0 0 1 ${x},${y + h - 5} V ${y + 5} A 5,5 0 0 1 ${x + 5},${y} Z"/>`;
    }
    if (shape === "client") {
      return `<path ${attrs} d="M ${x + 8},${y} H ${x + w - 8} A 8,8 0 0 1 ${x + w},${y + 8}`
        + ` V ${y + h - 30} A 30,30 0 0 1 ${x + w - 30},${y + h} H ${x + 30}`
        + ` A 30,30 0 0 1 ${x},${y + h - 30} V ${y + 8} A 8,8 0 0 1 ${x + 8},${y} Z"/>`;
    }
    if (shape === "store") {
      return `<path ${attrs} d="M ${x + 22},${y} H ${x + w - 7} A 7,7 0 0 1 ${x + w},${y + 7}`
        + ` V ${y + h - 7} A 7,7 0 0 1 ${x + w - 7},${y + h} H ${x + 7}`
        + ` A 7,7 0 0 1 ${x},${y + h - 7} V ${y + 22} Z"/>`;
    }
    return `<rect ${attrs} x="${x}" y="${y}" width="${w}" height="${h}" rx="7"/>`;
  }

  // The motif inside the silhouette: ruled rows for a table, record slots for a
  // topic, a doubled edge for a stream reader, a lid for an object store.
  function schematicMotif(shape, x, y, color) {
    const w = T.W, h = T.H;
    if (shape === "table") {
      const left = x + 16, right = x + w - 16;
      const rows = [h - 26, h - 16].map((dy) => `<path d="M ${left},${y + dy} H ${right}"/>`).join("");
      const ticks = [0.36, 0.7].map((at) =>
        `<path d="M ${left + (right - left) * at},${y + h - 30} V ${y + h - 12}"/>`).join("");
      return `<g class="t-rule" fill="none">${rows}${ticks}</g>`;
    }
    if (shape === "topic") {
      const slots = Array.from({ length: 6 }, (_, index) =>
        `<rect x="${x + 16 + index * 15}" y="${y + h - 24}" width="10" height="13" rx="2" fill="${color}" fill-opacity=".55"/>`
      ).join("");
      return `<g>${slots}</g>`;
    }
    if (shape === "reader") {
      return `<g class="t-rule" fill="none"><path d="M ${x + 8},${y + 12} V ${y + h - 12}"/>`
        + `<path d="M ${x + 13},${y + 12} V ${y + h - 12}"/></g>`;
    }
    if (shape === "store") {
      return `<g class="t-rule" fill="none"><path d="M ${x + 16},${y + h - 20} H ${x + w - 16}"/></g>`;
    }
    return "";
  }

  function schematicNode(resource, position, inspectable) {
    const [x, y] = position;
    const shape = shapeOf(resource.kind);
    const color = (KIND_COLORS[resource.kind] || ["#cbd5e1", "#8190a8", "#566278"])[1];
    const displayName = resource.properties?.label || resource.name;
    const kind = KIND_LABELS[resource.kind] || resource.kind.replaceAll("-", " ");
    const repeated = ["shards", "replicas"].includes(resource.scope);
    const details = Object.entries(resource.properties || {})
      .filter(([key, value]) => key !== "label" && key !== "note" && !(key === "table" && value === displayName))
      .map(([key, value]) => `${key.replaceAll("-", " ")} ${value}`);
    const detailLines = details.slice(0, 2)
      .map((detail, index) => `<text x="${x + 16}" y="${y + 60 + index * 12}" class="t-detail">${esc(clip(detail, 26))}</text>`)
      .join("");
    const note = resource.properties?.note;
    const readable = INSPECTABLE_KINDS.has(resource.kind);
    const nodeInspectable = readable && inspectable;
    const ghost = repeated
      ? schematicSilhouette(shape, x + 11, y - 11, `class="t-shape" fill="${color}" fill-opacity=".07" stroke="${color}"`)
      : "";
    const scopeTag = repeated
      ? `<text x="${x + T.W - 16}" y="${y + 22}" text-anchor="end" class="t-scope">×2 ${esc(resource.scope.toUpperCase())}</text>`
      : "";
    const noteBadge = note
      ? `<g class="note-badge" aria-hidden="true"><circle cx="${x + T.W - 15}" cy="${y + T.H - 15}" r="7.5"/>`
        + `<text x="${x + T.W - 15}" y="${y + T.H - 11.5}" text-anchor="middle">i</text></g>`
      : "";
    return `<g class="t-node resource${nodeInspectable ? " inspectable-resource" : ""}${note ? " has-note" : ""}"`
      + ` id="schematic-${esc(resource.key)}"`
      + `${readable ? ` data-readable-resource-key="${esc(resource.key)}"` : ""}`
      + `${note ? ` data-note="${esc(note)}"` : ""}`
      + `${nodeInspectable ? ` data-resource-key="${esc(resource.key)}" tabindex="0" role="button" aria-label="Inspect ${esc(displayName)}"` : ""}>`
      + (nodeInspectable ? `<title>Inspect live definition and rows for ${esc(displayName)}</title>` : "")
      + `<g class="t-ghost">${ghost}</g>`
      + schematicSilhouette(shape, x, y, `class="t-base" fill="${schematicPalette().nodeBase}"`)
      + schematicSilhouette(shape, x, y, `class="t-shape" fill="${color}" fill-opacity=".16" stroke="${color}"`)
      + schematicMotif(shape, x, y, color)
      + `<text x="${x + 16}" y="${y + 22}" class="t-kind">${esc(kind.toUpperCase())}</text>`
      + `<text x="${x + 16}" y="${y + 44}" class="t-name">${esc(clip(displayName, 21))}</text>`
      + detailLines + scopeTag + noteBadge
      + `</g>`;
  }

  // System boxes: contiguous runs of columns belonging to one system, padded
  // around the member nodes. Padding stays under half the column gap, so two
  // systems in neighbouring columns cannot draw into each other.
  function schematicBoundaries(pattern, graph, positions) {
    const CH_KINDS = ["kafka-table", "mv", "refreshable-mv", "distributed", "mergetree",
      "replicated-mergetree", "part", "keepermap", "consumer-group", "remote-table"];
    const systems = [];
    const clickhouse = graph.resources.filter((item) => CH_KINDS.includes(item.kind));
    if (clickhouse.length) {
      systems.push({ items: clickhouse, label: `CLICKHOUSE · ${pattern.topology.toUpperCase()}`, className: "" });
    }
    const topics = graph.resources.filter((item) => item.kind === "topic");
    if (topics.length) systems.push({ items: topics, label: "KAFKA CLUSTER", className: "" });
    const externalLabels = {
      postgres: "POSTGRES", mysql: "MYSQL", peerdb: "PEERDB",
      minio: "MINIO · S3", connector: "CONNECTOR"
    };
    Object.entries(externalLabels).forEach(([kind, label]) => {
      const items = graph.resources.filter((item) => item.kind === kind);
      if (!items.length) return;
      const system = kind === "connector" ? (items[0].properties.system || "").toUpperCase() : "";
      systems.push({ items, label: system || label, className: "" });
    });
    const pitch = T.W + T.HGAP;
    let markup = "";
    systems.forEach(({ items, label }) => {
      const xs = [...new Set(items.map((item) => positions[item.key][0]))].sort((a, b) => a - b);
      const runs = [];
      xs.forEach((x) => {
        const last = runs.at(-1);
        if (!last || x - last.at(-1) > pitch * 1.5) runs.push([x]);
        else last.push(x);
      });
      runs.forEach((run) => {
        const members = items.filter((item) => run.includes(positions[item.key][0]));
        const left = Math.min(...members.map((item) => positions[item.key][0])) - 26;
        const right = Math.max(...members.map((item) => positions[item.key][0])) + T.W + 26;
        const top = Math.min(...members.map((item) => positions[item.key][1])) - 44;
        const bottom = Math.max(...members.map((item) => positions[item.key][1])) + T.H + 22;
        markup += `<g><rect class="t-boundary" x="${left}" y="${top}" width="${right - left}" height="${bottom - top}" rx="16"/>`
          + `<text x="${left + 14}" y="${top + 22}" class="t-boundary-label">${esc(label)}</text></g>`;
      });
    });
    return markup;
  }

  function schematicLegend(graph, width) {
    const shapes = [...new Set(graph.resources.map((item) => shapeOf(item.kind)))];
    const order = ["table", "processor", "topic", "reader", "client", "store"];
    const used = order.filter((shape) => shapes.includes(shape));
    let x = T.LEFT;
    const entries = used.map((shape) => {
      const label = SHAPE_LABELS[shape] || shape;
      const mark = shape === "processor"
        ? `<rect class="t-legend-mark" x="${x}" y="26" width="26" height="14" rx="7"/>`
        : shape === "topic"
          ? `<path class="t-legend-mark" d="M ${x + 2},26 H ${x + 19} A 7,7 0 0 1 ${x + 26},33 A 7,7 0 0 1 ${x + 19},40 H ${x + 2} A 2,2 0 0 1 ${x},38 V 28 A 2,2 0 0 1 ${x + 2},26 Z"/>`
          : shape === "client"
            ? `<path class="t-legend-mark" d="M ${x + 3},26 H ${x + 23} A 3,3 0 0 1 ${x + 26},29 V 33 A 7,7 0 0 1 ${x + 19},40 H ${x + 7} A 7,7 0 0 1 ${x},33 V 29 A 3,3 0 0 1 ${x + 3},26 Z"/>`
            : shape === "store"
              ? `<path class="t-legend-mark" d="M ${x + 8},26 H ${x + 24} A 2,2 0 0 1 ${x + 26},28 V 38 A 2,2 0 0 1 ${x + 24},40 H ${x + 2} A 2,2 0 0 1 ${x},38 V 34 Z"/>`
              : `<rect class="t-legend-mark" x="${x}" y="26" width="26" height="14" rx="3"/>`;
      const text = `<text x="${x + 33}" y="37" class="t-legend">${esc(label)}</text>`;
      x += 33 + label.length * 5.6 + 26;
      return mark + text;
    }).join("");
    return x > width ? "" : entries;
  }

  function schematicSvg(pattern, { inspectable = false } = {}) {
    const graph = pattern.graph;
    const positions = schematicLayout(graph);
    // The right margin also clears the offset ghost drawn for @shards/@replicas.
    const width = Math.max(...Object.values(positions).map(([x]) => x)) + T.W + T.LEFT + 14;
    const height = Math.max(...Object.values(positions).map(([, y]) => y)) + T.H + 46;
    const pairCounts = new Map();
    graph.connections.forEach((edge) => {
      const key = `${edge.source}|${edge.target}`;
      pairCounts.set(key, (pairCounts.get(key) || 0) + 1);
    });
    const pairIndexes = new Map();
    const paths = [];
    const labels = [];
    const labelled = new Set();
    const labelRows = new Map();
    graph.connections.forEach((edge, edgeIndex) => {
      const pair = `${edge.source}|${edge.target}`;
      const lane = pairIndexes.get(pair) || 0;
      pairIndexes.set(pair, lane + 1);
      const offset = (lane - (pairCounts.get(pair) - 1) / 2) * 14;
      const [sx, sy] = positions[edge.source];
      const [tx, ty] = positions[edge.target];
      const x1 = sx + T.W, y1 = sy + T.H / 2 + offset;
      const x2 = tx, y2 = ty + T.H / 2 + offset;
      const bend = Math.max(38, (x2 - x1) * 0.45);
      const id = `schematic-edge-${edgeIndex}`;
      const color = FLOW_COLORS[edge.flow] || "#8b93ad";
      const marker = edge.flow in FLOW_COLORS ? edge.flow : "default";
      paths.push(`<path id="${id}" d="M ${x1},${y1} C ${x1 + bend},${y1} ${x2 - bend},${y2} ${x2 - 9},${y2}"`
        + ` class="t-edge" stroke="${color}"${edge.flow === "query" ? ' marker-start="url(#arrow-query)"' : ""}`
        + ` marker-end="url(#arrow-${marker})"/>`
        + `<circle r="3.2" fill="${color}" class="packet"><animateMotion dur="${2.2 + edgeIndex * 0.13}s"`
        + ` begin="-${edgeIndex * 0.31}s" repeatCount="indefinite"><mpath href="#${id}"/></animateMotion></circle>`);
      const labelKey = `${edge.source}|${edge.label || ""}`;
      if (edge.label && !labelled.has(labelKey)) {
        labelled.add(labelKey);
        // An edge spanning several columns passes over the nodes in between, so
        // its label goes in the first gap after the source — always empty — and
        // follows the edge there rather than sitting at the span's midpoint.
        const labelX = x1 + Math.min(T.HGAP, x2 - x1) / 2;
        let labelY = y1 + (y2 - y1) * ((labelX - x1) / Math.max(1, x2 - x1)) - 16;
        // Two labels in the same gap would print on top of each other; nudge the
        // later one down until it clears what is already there.
        const gap = Math.round(labelX / T.HGAP);
        const taken = labelRows.get(gap) || [];
        const lines = Math.ceil(edge.label.length / 22);
        const span = 14 * lines + 8;
        while (taken.some(([top, bottom]) => labelY < bottom && labelY + span > top)) labelY += span;
        taken.push([labelY, labelY + span]);
        labelRows.set(gap, taken);
        labels.push(edgeLabelSvg(edge.label, labelX, labelY, 22));
      }
    });
    const markers = Object.entries({ ...FLOW_COLORS, default: "#8b93ad" }).map(([name, color]) =>
      `<marker id="arrow-${name}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="${color}"/></marker>`
    ).join("");
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(pattern.title)} architecture, schematic view">
      <defs>${markers}<filter id="glow" x="-80%" y="-80%" width="260%" height="260%"><feGaussianBlur stdDeviation="4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>
      <style>${schematicPalette().style}</style>
      ${schematicLegend(graph, width)}
      ${schematicBoundaries(pattern, graph, positions)}
      <g class="edge-layer">${paths.join("")}</g>
      <g class="resource-layer">${graph.resources.map((resource) => schematicNode(resource, positions[resource.key], inspectable)).join("")}</g>
      <g class="annotation-layer">${labels.join("")}</g>
    </svg>`;
  }

  return { render: diagramSvg, renderSchematic: schematicSvg };
})();
