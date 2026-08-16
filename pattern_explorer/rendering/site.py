"""Compile pattern manifests into the browser-ready catalog and static site.

The browser application (``explorer/``) is the single SVG renderer. Python only
compiles the graph DSL and manifests into ``catalog.js`` and packages the static
site the browser consumes; it no longer draws diagrams itself.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from urllib.parse import quote

from ..catalog.graph import parse_resource_graph


_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = _ROOT / ".runtime" / "architecture"
EXPLORER_DIR = _ROOT / "explorer"


def _read_pattern_file(pattern, name: str | None) -> str | None:
    """Read one of a pattern's source files, or None if it is absent."""
    path = pattern.path(name)
    if path is None or not path.exists():
        return None
    return path.read_text()


def _definition(pattern) -> dict:
    """The pattern's source files, grouped by lifecycle phase, for the browser's
    Structure / Load / Verify / Configuration strip. Absent files are dropped."""
    def block(name, lang):
        code = _read_pattern_file(pattern, name)
        return {"file": name, "code": code, "lang": lang} if code is not None else None

    load_lang = "python" if (pattern.load or "").endswith(".py") else "sql"
    verify_sql = _read_pattern_file(pattern, pattern.verify.sql)
    verify_expected = _read_pattern_file(pattern, pattern.verify.expected)
    verify = None
    if verify_sql is not None or verify_expected is not None:
        verify = {
            "sqlFile": pattern.verify.sql, "sql": verify_sql,
            "expectedFile": pattern.verify.expected, "expected": verify_expected,
        }
    config = [
        {
            "file": item.file,
            "code": _read_pattern_file(pattern, item.file),
            "lang": "xml",
            "node": item.node,
            "mountPath": f"/etc/clickhouse-server/{item.directory}/99-pattern-{item.destination_name}",
            "dependsOn": item.depends_on,
        }
        for item in pattern.clickhouse_config
    ]
    return {
        "manifest": block("pattern.yaml", "yaml"),
        "structure": block(pattern.schema_sql, "sql"),
        "load": block(pattern.load, load_lang),
        "verify": verify,
        "config": config or None,
    }


def _browser_pattern(pattern) -> dict:
    graph = parse_resource_graph(pattern.graph) if pattern.graph else None
    return {
        "definition": _definition(pattern),
        "slug": pattern.slug,
        "location": pattern.location,
        "group": pattern.group,
        "title": pattern.title,
        "description": pattern.description,
        "status": pattern.status,
        "category": pattern.category,
        "flow": pattern.flow,
        "topology": pattern.topology,
        "order": pattern.order,
        "experimental": pattern.experimental,
        "tags": pattern.tags,
        "profiles": pattern.profiles,
        "runnable": pattern.runnable,
        "graphSource": pattern.graph,
        "graph": (
            {
                "flows": graph.flows,
                "resources": [vars(resource) for resource in graph.resources.values()],
                "connections": [vars(connection) for connection in graph.connections],
            }
            if graph
            else None
        ),
        "tradeoffs": (
            {
                "benefits": pattern.tradeoffs.benefits,
                "drawbacks": pattern.tradeoffs.drawbacks,
            }
            if pattern.tradeoffs
            else None
        ),
        "references": [reference.model_dump() for reference in pattern.references],
        "supersededBy": pattern.superseded_by or None,
        "supersededSince": pattern.superseded_since or None,
        "requires": (
            {
                "clickhouse_min": pattern.requires.clickhouse_min,
                "clickhouse_max": pattern.requires.clickhouse_max,
                "note": pattern.requires.note,
            }
            if (pattern.requires.clickhouse_min or pattern.requires.clickhouse_max)
            else None
        ),
    }


def _browser_group(group) -> dict:
    return {
        "key": group.key,
        "title": group.title,
        "label": group.label or group.title,
        "description": group.description,
        "icon": group.icon,
        "order": group.order,
        "intro": group.intro,
        "related": [{"group": link.group, "note": link.note} for link in group.related],
    }


# Workspace patterns are a location-based family, not a group folder, so their
# group card is synthesized rather than loaded from a group.yaml.
_WORKSPACES_GROUP = {
    "key": "workspaces",
    "title": "Workspace patterns",
    "label": "Workspace",
    "description": "Company and team extensions",
    "icon": "clone",
    "order": 100,
    "intro": "Company and team extensions derived from the shared library. These "
             "stay local to this repository and are not part of the curated catalog.",
    "related": [],
}


def architecture_url(html_path: Path, slug: str) -> str:
    return f"{html_path.as_uri()}?pattern={quote(slug)}"


def explorer_catalog_json() -> str:
    from ..catalog.manifest import (
        discover_groups,
        discover_patterns,
        discover_workspace_patterns,
    )

    patterns = [*discover_patterns(), *discover_workspace_patterns()]
    groups = [_browser_group(group) for group in discover_groups()] + [_WORKSPACES_GROUP]
    catalog = {
        "generatedAt": "build",
        "patterns": [_browser_pattern(item) for item in patterns],
        "groups": groups,
    }
    return json.dumps(catalog, ensure_ascii=False).replace("</", "<\\/")


def write_explorer_catalog(output_path: Path) -> Path:
    """Compile pattern manifests into browser-ready data; never write UI markup."""
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        f"window.CLICKHOUSE_PATTERN_CATALOG = {explorer_catalog_json()};\n"
    )
    return output_path


def build_explorer_site(output_dir: Path) -> Path:
    """Ask the JavaScript packer to assemble a static site around catalog data."""
    output_dir.mkdir(parents=True, exist_ok=True)
    catalog_path = write_explorer_catalog(output_dir / "catalog.js")
    subprocess.run(
        [
            "node",
            str(EXPLORER_DIR / "scripts" / "build-static.mjs"),
            "--catalog",
            str(catalog_path),
            "--output-dir",
            str(output_dir),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return (output_dir / "index.html").resolve()


def build_pattern_site(pattern, output_dir: Path) -> Path:
    """Validate the pattern graph and build the browser site that renders it.

    Returns the generated ``index.html`` path. The browser application owns all
    SVG rendering; deep-link to this pattern with :func:`architecture_url`.
    """
    if not pattern.graph:
        raise ValueError(f"pattern `{pattern.slug}` does not define a compact resource graph")
    parse_resource_graph(pattern.graph)  # fail fast on a malformed graph DSL
    return build_explorer_site(output_dir)
