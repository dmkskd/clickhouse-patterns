// Pattern page: everything drawn for the open pattern outside the architecture
// panel. Title, status, description, breadcrumb, references, related and
// superseded links, trade-offs and the definition dialog. app.js calls
// render(pattern) from selectPattern; links navigate through deps callbacks.
window.PE = window.PE || {};
window.PE.patternPage = (() => {
  "use strict";
  const { esc, displayTitle, formatDescInline } = window.PE.util;
  const { PATTERN_GROUPS, patterns, patternGroupKey, patternStatusBadge } = window.PE.catalog;
  const $ = (id) => document.getElementById(id);

  function create(deps) {
    // deps: openPattern(slug), openGroup(key), showHome()
    function renderTradeoffs(pattern) {
      const section = $("tradeoffs");
      const values = pattern.tradeoffs;
      if (!values || (!values.benefits?.length && !values.limitations?.length)) { section.hidden = true; return; }
      section.hidden = false;
      const fill = (element, items) => {
        element.replaceChildren(...(items || []).map((item) => {
          const li = document.createElement("li"); li.textContent = item; return li;
        }));
      };
      fill($("benefits"), values.benefits); fill($("limitations"), values.limitations);
    }

    // The Definition strip under the diagram shows the pattern's source files in
    // lifecycle order: Structure (schema) -> Load -> Verify (query + expected),
    // plus any per-service customization the pattern mounts (ClickHouse config
    // fragments, database init scripts).
    function codeBlock(file, code, lang) {
      const source = code || "";
      // Highlight.js escapes input before returning its markup. Keep the fallback
      // escaped as well, so source files are never interpreted as page HTML.
      const highlighted = window.hljs && ["yaml", "sql", "python", "xml"].includes(lang)
        ? window.hljs.highlight(source, { language: lang, ignoreIllegals: true }).value
        : esc(source);
      return `<figure class="code-file"><figcaption>${esc(file)}</figcaption>`
        + `<pre class="code lang-${esc(lang)}"><code class="hljs language-${esc(lang)}">${highlighted}</code></pre></figure>`;
    }

    function expectedTable(file, tsv) {
      const text = (tsv || "").trim();
      const rows = text ? text.split("\n").map((line) => {
        // '#' lines are annotations (usually a column header); show them as a
        // dimmed row, still split on tabs so the labels align with the columns.
        const comment = line.startsWith("#");
        const cells = (comment ? line.replace(/^#\s?/, "") : line).split("\t");
        return `<tr${comment ? ' class="expected-comment"' : ""}>${cells.map((cell) => `<td>${esc(cell)}</td>`).join("")}</tr>`;
      }) : [];
      const body = rows.length
        ? rows.join("")
        : `<tr><td>(empty)</td></tr>`;
      return `<figure class="code-file"><figcaption>${esc(file)}</figcaption>`
        + `<div class="expected-scroll"><table class="expected-table"><tbody>${body}</tbody></table></div></figure>`;
    }

    // Source files open in a dialog over the diagram. They used to expand a strip
    // under the panel, which pushed the page around and put the file far from the
    // control that asked for it.
    const definitionModal = $("definition-modal");
    const DEFINITION_TABS = [
      ["manifest", "Manifest", "Manifest: YAML pattern definition"],
      ["config", "Configuration", "Configuration: ClickHouse and service config files"],
      ["structure", "DDL", "DDL: table and view definitions"],
      ["load", "Loader", "Loader: data load script"],
      ["verify", "Validation", "Validation: check query and expected output"]
    ];

    function showDefinition(pattern, key) {
      const def = pattern.definition || {};
      const body = $("definition-body");
      // Clicking the tab that is already open closes the dialog again.
      if (definitionModal.open && definitionModal.dataset.key === key) { definitionModal.close(); return; }
      definitionModal.dataset.key = key;
      $("definition-modal-title").textContent = pattern.title;
      if (key === "verify") {
        const v = def.verify;
        body.className = "definition-body verify";
        body.innerHTML = codeBlock(v.sqlFile, v.sql, "sql")
          + (v.expected != null ? expectedTable(v.expectedFile, v.expected) : "");
      } else if (key === "config") {
        body.className = "definition-body configuration";
        body.innerHTML = def.config.map((item) =>
          codeBlock((item.mountPath
            ? `${item.file} · ${item.node} → ${item.mountPath}`
            : `${item.file} · read by ${item.reader}`)
            + (item.dependsOn?.length ? ` · after ${item.dependsOn.join(", ")}` : ""), item.code, item.lang)
        ).join("");
      } else {
        const d = def[key];
        body.className = "definition-body";
        body.innerHTML = codeBlock(d.file, d.code, d.lang);
      }
      body.scrollTop = 0;
      // The dialog has its own copy of the tabs, so a reader can move between
      // files without closing it.
      const inModal = $("definition-modal-tabs");
      inModal.replaceChildren(...DEFINITION_TABS.filter(([k]) => def[k]).map(([k, label, hint]) => {
        const button = document.createElement("button");
        button.type = "button";
        button.dataset.def = k;
        button.textContent = label;
        button.title = hint;
        button.className = k === key ? "active" : "";
        button.addEventListener("click", () => showDefinition(pattern, k));
        return button;
      }));
      document.querySelectorAll("#definition-tabs button").forEach((b) =>
        b.classList.toggle("active", b.dataset.def === key));
      if (!definitionModal.open) definitionModal.showModal();
      // showModal() autofocuses the first control, which puts a focus ring on the
      // first tab. The file itself is the thing being read, so it takes focus.
      body.focus({ preventScroll: true });
    }

    function renderDefinition(pattern) {
      const def = pattern.definition || {};
      const tabs = DEFINITION_TABS.filter(([key]) => def[key]);
      $("definition-tabs").replaceChildren(...tabs.map(([key, label, hint]) => {
        const b = document.createElement("button");
        b.type = "button"; b.dataset.def = key; b.textContent = label;
        b.title = hint;
        b.addEventListener("click", () => showDefinition(pattern, key));
        return b;
      }));
      // Nothing is loaded until a tab is clicked; switching pattern closes any
      // file left open from the previous one.
      if (definitionModal.open) definitionModal.close();
      delete definitionModal.dataset.key;
      $("definition-body").innerHTML = "";
      // The row holds the legend and the tabs; it hides only with neither.
      $("control-strip").hidden = !tabs.length && !$("flow-legend").childElementCount;
    }

    function renderRequires(req) {
      const el = $("pattern-requires");
      if (!req || (!req.clickhouse_min && !req.clickhouse_max)) { el.hidden = true; el.replaceChildren(); return; }
      const parts = [];
      if (req.clickhouse_min) parts.push(`ClickHouse ≥ ${req.clickhouse_min}`);
      if (req.clickhouse_max) parts.push(`ClickHouse ≤ ${req.clickhouse_max}`);
      const badge = document.createElement("span");
      badge.className = "requires-badge";
      badge.textContent = parts.join("   ·   ");
      el.replaceChildren(badge);
      if (req.note) {
        const note = document.createElement("span");
        note.className = "requires-note";
        note.textContent = req.note;
        el.append(note);
      }
      el.hidden = false;
    }

    // renderDescription paints the styled paragraphs into the DOM; the inline
    // markup and plain-text helpers it uses live in util.js.
    // Blank lines separate description blocks. A ``` fence keeps its lines as
    // written, blank lines included. ":::fold Title" ... ":::" puts the blocks
    // between the two markers in a collapsed <details> titled Title.
    function descriptionNodes(text) {
      const nodes = [];
      const lines = String(text ?? "").split("\n");
      let block = [];
      const flush = () => {
        if (block.join("").trim()) nodes.push(blockNode(block.join("\n").trim()));
        block = [];
      };
      // Index of the line that closes the fence or fold opened at `start`;
      // fences inside a fold are skipped, so their lines cannot close it.
      const closing = (start, marker) => {
        for (let index = start + 1; index < lines.length; index += 1) {
          const line = lines[index].trim();
          if (marker === ":::" && line.startsWith("```")) index = closing(index, "```");
          else if (line === marker) return index;
        }
        return lines.length;
      };
      for (let index = 0; index < lines.length; index += 1) {
        const line = lines[index].trim();
        if (line.startsWith("```")) {
          flush();
          const end = closing(index, "```");
          const pre = document.createElement("pre");
          const code = document.createElement("code");
          code.textContent = lines.slice(index + 1, end).join("\n");
          pre.append(code);
          nodes.push(pre);
          index = end;
        } else if (line.startsWith(":::fold")) {
          flush();
          const end = closing(index, ":::");
          const fold = document.createElement("details");
          fold.className = "pattern-description-fold";
          const summary = document.createElement("summary");
          summary.innerHTML = formatDescInline(line.slice(":::fold".length).trim() || "Details");
          fold.append(summary, ...descriptionNodes(lines.slice(index + 1, end).join("\n")));
          nodes.push(fold);
          index = end;
        } else if (!line) {
          flush();
        } else {
          block.push(lines[index]);
        }
      }
      flush();
      return nodes;
    }

    function blockNode(block) {
      const lines = block.split("\n").map((line) => line.trim()).filter(Boolean);
      // A "### " block is a section heading within the description, and a
      // "#### " block a subsection of the section above it.
      const marker = lines.length === 1 && /^(###|####) /.exec(lines[0]);
      if (marker) {
        const sub = marker[1] === "####";
        const heading = document.createElement(sub ? "h4" : "h3");
        heading.className = `pattern-description-heading${sub ? " sub" : ""}`;
        heading.innerHTML = formatDescInline(lines[0].slice(marker[0].length));
        return heading;
      }
      if (!lines[0]?.startsWith("- ")) {
        const para = document.createElement("p");
        para.innerHTML = formatDescInline(block);
        return para;
      }

      const list = document.createElement("ul");
      const items = [];
      for (const line of lines) {
        if (line.startsWith("- ")) {
          items.push(line.slice(2));
        } else if (items.length) {
          items[items.length - 1] += ` ${line}`;
        }
      }
      for (const item of items) {
        const li = document.createElement("li");
        li.innerHTML = formatDescInline(item);
        list.append(li);
      }
      return list;
    }

    function renderDescription(text) {
      const el = $("pattern-description");
      const nodes = descriptionNodes(text);
      // The first block is the lede and renders above the architecture panel;
      // the rest of the description follows it.
      const lede = $("pattern-description-lede");
      const [first, ...rest] = nodes;
      lede.replaceChildren(...(first ? [first] : []));
      el.replaceChildren(...rest);
      // [[slug|label]] in a description renders as a button that opens the
      // pattern in place.
      [lede, el].forEach((root) =>
        root.querySelectorAll(".pattern-inline-link").forEach((btn) =>
          btn.addEventListener("click", () => deps.openPattern(btn.dataset.pattern))
        )
      );
    }

    function renderPatternMeta(pattern) {
      const el = $("pattern-status-detail");
      const provenance = document.createElement("span");
      provenance.className = "pattern-provenance";
      provenance.textContent = pattern.location === "workspace" ? "Workspace" : "Curated";
      const status = patternStatusBadge(pattern.status);
      el.replaceChildren(provenance, ...(status ? [status] : []));
      el.hidden = false;
    }

    function renderPatternTags(tags) {
      const el = $("pattern-tags");
      el.replaceChildren();
      if (!tags?.length) {
        el.hidden = true;
        return;
      }
      tags.forEach((tag) => {
        const item = document.createElement("span");
        item.className = "pattern-tag";
        item.textContent = tag;
        el.append(item);
      });
      el.hidden = false;
    }

    function crumbSep() {
      const sep = document.createElement("span");
      sep.className = "crumb-sep";
      sep.setAttribute("aria-hidden", "true");
      sep.textContent = "›";
      return sep;
    }

    function renderBreadcrumb(pattern) {
      const nav = $("pattern-breadcrumb");
      const groupKey = patternGroupKey(pattern);
      const groupLabel = PATTERN_GROUPS[pattern.group]?.label || pattern.group;

      const all = document.createElement("button");
      all.type = "button";
      all.className = "crumb-link";
      all.textContent = "All patterns";
      // "All patterns" means unfiltered: reset any group/topology/search filtering.
      all.addEventListener("click", deps.showHome);

      // The group is the emphasised crumb, and clicking it returns to the catalog
      // filtered to that group.
      const group = document.createElement("button");
      group.type = "button";
      group.className = "crumb-link crumb-group";
      group.textContent = groupLabel;
      group.addEventListener("click", () => deps.openGroup(groupKey));

      nav.replaceChildren(all, crumbSep(), group);
    }

    function renderExperimental(pattern) {
      const el = $("pattern-experimental");
      if (!pattern.experimental) { el.hidden = true; el.replaceChildren(); return; }
      const badge = document.createElement("span");
      badge.className = "experimental-badge";
      badge.textContent = "Experimental";
      const note = document.createElement("span");
      note.className = "experimental-note";
      note.textContent = "Newer pattern, not yet battle-tested; the mechanics may change.";
      el.replaceChildren(badge, note);
      el.hidden = false;
    }

    function renderSuperseded(pattern) {
      const el = $("pattern-superseded");
      const target = pattern.supersededBy && patterns.find((p) => p.slug === pattern.supersededBy);
      if (!target) { el.hidden = true; el.replaceChildren(); return; }
      const lead = document.createElement("span");
      lead.className = "superseded-lead";
      lead.textContent = "Superseded by";
      const link = document.createElement("button");
      link.type = "button";
      link.className = "superseded-link";
      link.textContent = displayTitle(target);
      link.addEventListener("click", () => deps.openPattern(target.slug));
      const since = document.createElement("span");
      since.className = "superseded-since";
      since.textContent = pattern.supersededSince ? `· native in ClickHouse ${pattern.supersededSince}+` : "";
      el.replaceChildren(lead, link);
      if (since.textContent) el.append(since);
      el.hidden = false;
    }

    function renderLinks(pattern) {
      const references = $("pattern-references");
      const entries = (pattern.references || []).map((reference) => {
        const link = document.createElement("a");
        link.href = reference.url;
        link.target = "_blank";
        link.rel = "noreferrer";
        link.textContent = reference.label;
        return link;
      });
      const referencesHead = document.createElement("span");
      referencesHead.className = "references-head";
      referencesHead.textContent = "References";
      references.replaceChildren(...(entries.length ? [referencesHead, ...entries] : []));
      references.hidden = !entries.length;
      const relatedPatterns = $("pattern-related");
      const related = (pattern.related_patterns || [])
        .map((relation) => ({ relation, target: patterns.find((item) => item.slug === relation.slug) }))
        .filter(({ target }) => target);
      relatedPatterns.replaceChildren();
      if (related.length) {
        const label = document.createElement("span");
        label.textContent = "Related guidance";
        relatedPatterns.append(label);
        related.forEach(({ relation, target }) => {
          const button = document.createElement("button");
          button.type = "button";
          button.textContent = target.title;
          button.title = relation.note || `Open ${target.title}`;
          button.addEventListener("click", () => deps.openPattern(target.slug));
          relatedPatterns.append(button);
        });
      }
      relatedPatterns.hidden = !related.length;
      $("pattern-links").hidden = references.hidden && relatedPatterns.hidden;
    }

    function render(pattern) {
      renderBreadcrumb(pattern);
      $("pattern-title").textContent = pattern.title;
      renderPatternMeta(pattern);
      renderPatternTags(pattern.tags);
      renderDescription(pattern.description);
      renderRequires(pattern.requires);
      renderExperimental(pattern);
      renderSuperseded(pattern);
      renderLinks(pattern);
      document.title = `${pattern.title} — Pattern Explorer`;
      renderTradeoffs(pattern);
      renderDefinition(pattern);
    }

    $("definition-modal-close")?.addEventListener("click", () => definitionModal.close());
    definitionModal.addEventListener("click", (event) => {
      if (event.target === definitionModal) definitionModal.close();
    });
    definitionModal.addEventListener("close", () => {
      delete definitionModal.dataset.key;
      document.querySelectorAll("#definition-tabs button").forEach((b) => b.classList.remove("active"));
    });

    return { render };
  }

  return { create };
})();
