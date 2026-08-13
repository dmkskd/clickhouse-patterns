"""Create and inspect editable workspace patterns."""
from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import manifest

_METADATA_FILE = ".workspace.yaml"
_LEGACY_METADATA_FILE = ".clone.yaml"


@dataclass(frozen=True)
class CloneInfo:
    slug: str
    source: str
    directory: Path
    created_at: str


class CloneError(RuntimeError):
    """A clone operation would affect something other than a managed clone."""


def _workspace_destination(slug: str) -> Path:
    manifest.validate_pattern_slug(slug)
    collisions = [match.parent for match in manifest.PATTERNS_DIR.glob(f"*/{slug}/pattern.yaml")]
    collisions.extend(root / slug for root in manifest.workspace_pattern_dirs())
    existing = [path for path in collisions if path.exists()]
    if existing:
        raise FileExistsError(f"pattern name {slug!r} already exists at {existing[0]}")
    return manifest.workspace_pattern_write_dir() / slug


def _write_workspace_metadata(directory: Path, source: str, created_at: str) -> None:
    (directory / _METADATA_FILE).write_text(
        yaml.safe_dump(
            {"derived_from": None if source == "scratch" else source, "created_at": created_at},
            sort_keys=False,
        )
    )


def read_clone_info(directory: Path) -> CloneInfo | None:
    metadata = directory / _METADATA_FILE
    if not metadata.exists():
        metadata = directory / _LEGACY_METADATA_FILE
    if not metadata.exists():
        return None
    data = yaml.safe_load(metadata.read_text()) or {}
    return CloneInfo(
        slug=directory.name,
        source=str(data.get("derived_from") or data.get("source") or "scratch"),
        directory=directory,
        created_at=str(data.get("created_at", "unknown")),
    )


def clone_pattern(source_slug: str, clone_slug: str) -> CloneInfo:
    """Derive an editable workspace pattern from an existing pattern."""
    source = manifest.load_pattern(source_slug)
    destination = _workspace_destination(clone_slug)

    created_at = datetime.now(timezone.utc).isoformat()
    workspace_root = destination.parent
    workspace_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{clone_slug}-", dir=workspace_root
    ) as temporary:
        staged = Path(temporary) / clone_slug
        shutil.copytree(
            source.dir,
            staged,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
        )
        _write_workspace_metadata(staged, source.slug, created_at)
        staged.replace(destination)

    return CloneInfo(
        slug=clone_slug,
        source=source.slug,
        directory=destination.resolve(),
        created_at=created_at,
    )


def create_workspace_pattern(slug: str) -> CloneInfo:
    """Create a documentation-first workspace pattern from a safe scaffold."""
    destination = _workspace_destination(slug)
    created_at = datetime.now(timezone.utc).isoformat()
    title = slug.replace("-", " ").title()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{slug}-", dir=destination.parent) as temporary:
        staged = Path(temporary) / slug
        staged.mkdir()
        pattern = {
            "title": title,
            "description": (
                "Document what this architecture demonstrates, when to use it, "
                "and the operational trade-offs."
            ),
            "graph": (
                "architecture:\n"
                "  client:source(label=replace with the real source)\n"
                "    -> mergetree:destination(label=replace with the real destination)\n"
            ),
            "mode": "reference",
            "category": "custom",
            "flow": "ingestion",
            "topology": "single",
            "tags": ["workspace"],
            "profiles": [],
        }
        (staged / "pattern.yaml").write_text(yaml.safe_dump(pattern, sort_keys=False))
        _write_workspace_metadata(staged, "scratch", created_at)
        staged.replace(destination)
    return CloneInfo(
        slug=slug,
        source="scratch",
        directory=destination.resolve(),
        created_at=created_at,
    )


def delete_clone(clone_slug: str) -> CloneInfo:
    """Delete a managed pattern from the configured writable workspace root."""
    manifest.validate_pattern_slug(clone_slug)
    workspace_root = manifest.workspace_pattern_write_dir()
    destination = workspace_root / clone_slug

    if any(manifest.PATTERNS_DIR.glob(f"*/{clone_slug}/pattern.yaml")):
        raise CloneError(
            f"{clone_slug!r} is a library pattern; only local clones can be deleted"
        )
    if not destination.exists() and workspace_root == manifest.WORKSPACE_PATTERNS_DIR.resolve():
        legacy = manifest.LEGACY_CLONED_PATTERNS_DIR / clone_slug
        destination = legacy if legacy.exists() else destination
    if not destination.exists():
        raise FileNotFoundError(f"workspace pattern {clone_slug!r} does not exist")
    if destination.is_symlink():
        raise CloneError(f"refusing to delete symlinked workspace pattern {destination}")

    info = read_clone_info(destination)
    if info is None:
        raise CloneError(
            f"{destination} is missing {_METADATA_FILE} metadata; refusing automatic deletion"
        )

    shutil.rmtree(destination)
    return CloneInfo(
        slug=info.slug,
        source=info.source,
        directory=destination.resolve(),
        created_at=info.created_at,
    )
