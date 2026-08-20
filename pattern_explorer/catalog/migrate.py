"""Rewrite pattern.yaml files from the flat v1 layout to the v2 metadata/spec layout.

v2 groups the flat v1 keys: catalog fields under `metadata:`, runtime fields
under `spec:` (with `services:` and the ordered `steps:` lifecycle). The rewrite
uses ruamel round-trip mode so the comments pattern authors wrote — which the
explorer shows verbatim in the Definition tab — survive the move.
"""
from __future__ import annotations

from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from .manifest import (
    CURRENT_MANIFEST_VERSION,
    PATTERNS_DIR,
    workspace_pattern_dirs,
)

# v1 key -> v2 home. Catalog keys keep their names under metadata:; the ordered
# lifecycle moves under spec.steps (schema_sql loses the suffix); runtime wiring
# stays flat under spec:.
_METADATA_KEYS = (
    "title", "description", "graph", "status", "topology",
    "order", "experimental", "tags", "references", "related_patterns",
    "superseded_by", "superseded_since", "tradeoffs",
)
_SPEC_KEYS = ("mode", "profiles", "driver_node", "requires")
_STEP_KEYS = {"schema_sql": "schema", "load": "load", "ready_when": "ready_when", "verify": "verify"}
# v1 taxonomy keys that v2 removed; migration discards them (and their comments).
_DROPPED_KEYS = ("category", "flow")


def _move(src: CommentedMap, key: str, dst: CommentedMap, dst_key: str | None = None) -> None:
    """Move one key between maps, carrying the comments attached to it."""
    if key not in src:
        return
    target = dst_key or key
    comment = src.ca.items.get(key)
    dst[target] = src[key]
    del src[key]
    if comment is not None:
        dst.ca.items[target] = comment


def _indent_orphan_comments(text: str) -> str:
    """Re-indent top-level comment lines that landed inside metadata:/spec:.

    ruamel emits moved comments at their original column (0), which scatters
    them across the nested sections they moved into. A comment documents the key
    that follows it, so adopt that line's indentation. Header comments above
    `metadata:` keep column 0.
    """
    lines = text.splitlines()
    try:
        first_section = next(i for i, line in enumerate(lines) if line in ("metadata:", "spec:"))
    except StopIteration:
        return text
    result: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if i > first_section and line.startswith("#"):
            block: list[str] = []
            while i < len(lines) and (lines[i].startswith("#") or not lines[i].strip()):
                block.append(lines[i])
                i += 1
            indent = ""
            if i < len(lines) and lines[i].startswith((" ", "\t")):
                indent = lines[i][: len(lines[i]) - len(lines[i].lstrip())]
            result.extend((indent + comment if comment.startswith("#") else comment) for comment in block)
            continue
        result.append(line)
        i += 1
    return "\n".join(result) + "\n"


def migrate_manifest(path: Path) -> bool:
    """Rewrite `path` to the current manifest format in place.

    Returns True when the file was rewritten, False when it already declared
    the current version (the command is idempotent).
    """
    yaml_rt = YAML()
    # Match the repo's hand-written style: no line wrapping, sequences indented
    # under their key (`key:` then `  - item`).
    yaml_rt.width = 1 << 20
    yaml_rt.indent(mapping=2, sequence=4, offset=2)
    data = yaml_rt.load(path.read_text())
    if not isinstance(data, CommentedMap):
        raise ValueError(f"{path}: expected a mapping at the top level")
    version = data.get("manifest_version", 1)
    if not isinstance(version, int):
        raise ValueError(f"{path}: manifest_version must be an integer")
    if version >= CURRENT_MANIFEST_VERSION:
        return False

    metadata = CommentedMap()
    spec = CommentedMap()
    services = CommentedMap()
    steps = CommentedMap()

    for key in _METADATA_KEYS:
        _move(data, key, metadata)
    for key in _SPEC_KEYS:
        _move(data, key, spec)
    if "clickhouse_config" in data:
        clickhouse = CommentedMap()
        _move(data, "clickhouse_config", clickhouse, "config")
        services["clickhouse"] = clickhouse
    for old_key, new_key in _STEP_KEYS.items():
        _move(data, old_key, steps, new_key)
    for key in _DROPPED_KEYS:
        data.pop(key, None)
    if services:
        spec["services"] = services
    if steps:
        spec["steps"] = steps

    migrated = CommentedMap()
    migrated["manifest_version"] = CURRENT_MANIFEST_VERSION
    version_comment = data.ca.items.get("manifest_version")
    if version_comment is not None:
        migrated.ca.items["manifest_version"] = version_comment
    if data.ca.comment:
        migrated.ca.comment = data.ca.comment
    migrated["metadata"] = metadata
    migrated["spec"] = spec

    unknown = [key for key in data if key != "manifest_version"]
    if unknown:
        raise ValueError(f"{path}: no v2 home for key(s) {unknown}; migrate them by hand")

    with path.open("w") as handle:
        yaml_rt.dump(migrated, handle)
    path.write_text(_indent_orphan_comments(path.read_text()))
    return True


def iter_manifest_paths(slugs: list[str]) -> list[Path]:
    """Resolve pattern slugs to manifest paths, or every manifest when empty."""
    if not slugs:
        paths = sorted(PATTERNS_DIR.glob("*/*/pattern.yaml"))
        for root in workspace_pattern_dirs():
            paths.extend(sorted(root.glob("*/pattern.yaml")))
        unique: list[Path] = []
        seen: set[Path] = set()
        for path in paths:
            if path.resolve() not in seen:
                seen.add(path.resolve())
                unique.append(path)
        return unique
    paths = []
    for slug in slugs:
        candidates = sorted(PATTERNS_DIR.glob(f"*/{slug}/pattern.yaml"))
        for root in workspace_pattern_dirs():
            candidate = root / slug / "pattern.yaml"
            if candidate.exists():
                candidates.append(candidate)
        if not candidates:
            raise FileNotFoundError(f"no pattern {slug!r} found")
        if len(candidates) > 1:
            raise ValueError(f"pattern {slug!r} is ambiguous; found in {candidates}")
        paths.append(candidates[0])
    return paths
