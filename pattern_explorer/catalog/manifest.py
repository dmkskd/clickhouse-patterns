"""Discover and validate curated and workspace pattern manifests."""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

_ROOT = Path(__file__).resolve().parents[2]
PATTERNS_DIR = _ROOT / "patterns"
WORKSPACE_PATTERNS_DIR = _ROOT / "workspace-patterns"
# Compatibility alias for external callers; internal code uses the canonical name.
CLONED_PATTERNS_DIR = WORKSPACE_PATTERNS_DIR
LEGACY_CLONED_PATTERNS_DIR = _ROOT / "cloned-patterns"
_DEFAULT_WORKSPACE_PATTERNS_DIR = WORKSPACE_PATTERNS_DIR
COMPOSE_FILE = _ROOT / "compose" / "stack.yml"
_PATTERN_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

# The pattern.yaml manifest format version this build understands. Bump it
# whenever the shape of pattern.yaml changes incompatibly, and gate the old shape
# behind the older number so a file declares which parser it expects. Files
# without the field are treated as version 1 (the shape before it was introduced).
CURRENT_MANIFEST_VERSION = 1


class PatternManifestError(ValueError):
    """A pattern.yaml that could not be parsed or validated, named by path.

    Pydantic reports the failing field but not the file it came from, and a
    caller loading every manifest at once cannot tell which of them broke. This
    carries the path in the first line of the message, where terse error
    reporting can still see it.
    """


def _manifest_path(manifest: Path) -> str:
    """Name the manifest the way the reader would type it, when it is in-tree."""
    try:
        return str(manifest.relative_to(_ROOT))
    except ValueError:
        return str(manifest)


def _manifest_error(manifest: Path, exc: ValidationError) -> PatternManifestError:
    problems = "; ".join(
        f"{'.'.join(str(part) for part in error['loc']) or '<root>'} {error['msg']}"
        for error in exc.errors()[:3]
    )
    if len(exc.errors()) > 3:
        problems += f"; (+{len(exc.errors()) - 3} more)"
    return PatternManifestError(f"{_manifest_path(manifest)}: {problems}")


def validate_pattern_slug(slug: str) -> None:
    if not _PATTERN_SLUG.fullmatch(slug):
        raise ValueError(
            "pattern name must use lowercase letters, numbers, and single hyphens, "
            "and must start and end with a letter or number"
        )


@lru_cache(maxsize=1)
def known_profiles() -> frozenset[str]:
    """All profiles declared across services in the compose file."""
    data = yaml.safe_load(COMPOSE_FILE.read_text()) or {}
    return frozenset(
        p
        for svc in (data.get("services") or {}).values()
        for p in ((svc or {}).get("profiles") or [])
    )


@lru_cache(maxsize=1)
def known_nodes() -> frozenset[str]:
    """ClickHouse services available as pattern driver nodes."""
    data = yaml.safe_load(COMPOSE_FILE.read_text()) or {}
    return frozenset(
        name
        for name, service in (data.get("services") or {}).items()
        if str((service or {}).get("image", "")).startswith("clickhouse/clickhouse-server:")
    )


@lru_cache(maxsize=1)
def known_services() -> frozenset[str]:
    """All Compose services available for pattern-local dependency wiring."""
    data = yaml.safe_load(COMPOSE_FILE.read_text()) or {}
    return frozenset((data.get("services") or {}).keys())


class Expectation(BaseModel):
    """A convergence check: poll `query` on `node` until it equals `value`."""

    model_config = ConfigDict(extra="forbid")

    query: str
    value: int | str
    node: str | None = None    # node to poll; defaults to the pattern's driver_node
    timeout: int = 60          # seconds
    # NB: field is `node`, not `on` - YAML parses a bare `on:` key as boolean True
    # (and extra="forbid" now rejects it rather than silently ignoring it).


class Reference(BaseModel):
    """External documentation or background for a pattern."""

    model_config = ConfigDict(extra="forbid")

    label: str
    url: str


class RelatedPattern(BaseModel):
    """A contextual link to another pattern in the catalog."""

    model_config = ConfigDict(extra="forbid")

    slug: str
    note: str = ""


class GroupAdvisory(BaseModel):
    """A compact, expandable operational notice on a group landing page."""

    model_config = ConfigDict(extra="forbid")

    title: str
    summary: str = ""
    body: str = ""
    link_label: str = "Read more"
    link: str = ""
    link_pattern: str = ""


class Tradeoffs(BaseModel):
    """Concrete benefits and limitations of choosing a pattern."""

    model_config = ConfigDict(extra="forbid")

    benefits: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class Verify(BaseModel):
    """The pattern's output check: run `sql` and require its result to equal `expected`."""

    model_config = ConfigDict(extra="forbid")

    sql: str | None = "verify.sql"
    expected: str | None = "expected.txt"


def _version_key(text: str) -> tuple[int, ...]:
    """The numeric components of a ClickHouse version string, e.g. 26.8.1.918."""
    return tuple(int(part) for part in re.findall(r"\d+", text))


def check_clickhouse_version(running: str, minimum: str = "", maximum: str = "") -> str | None:
    """Return None if `running` is within [minimum, maximum], else a reason.

    Each bound is compared only on the components it specifies, so `25.3` covers
    the whole 25.3.x series and `26.8` means 26.8 or newer. Empty bounds are ignored.
    """
    r = _version_key(running)

    def compare(bound: str) -> int:
        b = _version_key(bound)
        rr = r[: len(b)]
        rr = rr + (0,) * (len(b) - len(rr))
        return (rr > b) - (rr < b)

    if minimum and compare(minimum) < 0:
        return f"needs ClickHouse >= {minimum}, but the server reports {running}"
    if maximum and compare(maximum) > 0:
        return f"needs ClickHouse <= {maximum}, but the server reports {running}"
    return None


class Requires(BaseModel):
    """ClickHouse version bounds this pattern needs, checked against the running
    server before schema is applied.

    `clickhouse_min` is a hard floor (a feature absent below it). `clickhouse_max`
    is a ceiling, often driven by an external component the pattern pins rather than
    ClickHouse itself, so record the reason in `note`. Either bound may be empty.
    """

    model_config = ConfigDict(extra="forbid")

    clickhouse_min: str = ""
    clickhouse_max: str = ""
    note: str = ""

    @model_validator(mode="after")
    def _validate(self):
        for label, value in (("clickhouse_min", self.clickhouse_min), ("clickhouse_max", self.clickhouse_max)):
            if value and not re.fullmatch(r"\d+(\.\d+)*", value):
                raise ValueError(f"{label} must be a dotted version like '26.8', got {value!r}")
        if self.clickhouse_min and self.clickhouse_max and _version_key(self.clickhouse_min) > _version_key(self.clickhouse_max):
            raise ValueError(
                f"clickhouse_min {self.clickhouse_min} is greater than clickhouse_max {self.clickhouse_max}"
            )
        return self


class ClickHouseConfigOverride(BaseModel):
    """An additive server configuration fragment mounted for one CH service.

    Full config.xml replacement would make a pattern depend on incidental stack
    defaults.  Fragments are instead mounted into config.d or users.d, where
    ClickHouse merges them with the shared development configuration.
    """

    model_config = ConfigDict(extra="forbid")

    node: str
    file: str
    directory: Literal["config.d", "users.d"] = "config.d"
    name: str = ""  # destination filename; defaults to the source basename
    depends_on: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate(self):
        if not self.file.endswith(".xml"):
            raise ValueError("clickhouse_config file must be an .xml fragment")
        if Path(self.file).is_absolute() or ".." in Path(self.file).parts:
            raise ValueError("clickhouse_config file must be relative to the pattern directory")
        destination = self.name or Path(self.file).name
        if Path(destination).name != destination or not destination.endswith(".xml"):
            raise ValueError("clickhouse_config name must be one .xml filename")
        unknown_dependencies = set(self.depends_on) - known_services()
        if unknown_dependencies:
            raise ValueError(
                f"unknown clickhouse_config dependency service(s) {sorted(unknown_dependencies)}; "
                f"known: {sorted(known_services())}"
            )
        if self.node in self.depends_on:
            raise ValueError("clickhouse_config cannot depend on its own node")
        return self

    @property
    def destination_name(self) -> str:
        return self.name or Path(self.file).name


class Pattern(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Which pattern.yaml manifest format this file is written against; see CURRENT_MANIFEST_VERSION.
    manifest_version: int = 1
    title: str
    description: str
    graph: str | None = None
    mode: Literal["runnable", "reference"] = "runnable"
    status: Literal["wip", "under-review", "stable"] = "wip"
    category: str
    flow: str
    topology: str
    order: int = 1000    # sort position within a group; lower shows first
    experimental: bool = False   # newer/less-proven pattern; shown with an Experimental badge
    tags: list[str] = Field(default_factory=list)
    references: list[Reference] = Field(default_factory=list)
    related_patterns: list[RelatedPattern] = Field(default_factory=list)
    # Advisory: this pattern still runs, but a better native option now exists.
    superseded_by: str = ""       # slug of the pattern that replaces this one
    superseded_since: str = ""    # ClickHouse version the replacement is available from
    tradeoffs: Tradeoffs | None = None
    profiles: list[str] = Field(default_factory=list)
    driver_node: str | None = "ch"  # node schema/verification runs against

    # Step files (resolved relative to the pattern dir). Any may be omitted.
    schema_sql: str | None = "schema.sql"       # single file, run on driver_node
    load: str | None = None    # .sql (run on driver) | .py (run as subprocess)
    verify: Verify = Field(default_factory=Verify)

    requires: Requires = Field(default_factory=Requires)  # ClickHouse version bounds

    # Additive config fragments, mounted only while this pattern's stack is up.
    clickhouse_config: list[ClickHouseConfigOverride] = Field(default_factory=list)

    ready_when: list[Expectation] = Field(default_factory=list)

    # Filled in by the loader, not read from YAML.
    slug: str = ""
    dir: Path = Path()
    location: str = "library"
    group: str = ""      # the group folder this pattern lives in

    def path(self, name: str | None) -> Path | None:
        return self.dir / name if name else None

    @property
    def runnable(self) -> bool:
        return self.mode == "runnable"

    def require_runnable(self) -> None:
        if not self.runnable:
            raise ValueError(
                f"pattern {self.slug!r} is documentation-only; add a runtime "
                "configuration before using run, start, up, or test"
            )

    @model_validator(mode="after")
    def _validate(self):
        if self.manifest_version > CURRENT_MANIFEST_VERSION:
            raise ValueError(
                f"manifest_version {self.manifest_version} is newer than this build "
                f"understands (max {CURRENT_MANIFEST_VERSION}); upgrade the pattern "
                "explorer to read this pattern"
            )
        if self.manifest_version < 1:
            raise ValueError("manifest_version must be a positive integer")
        if self.superseded_by:
            validate_pattern_slug(self.superseded_by)
        if self.superseded_since and not re.fullmatch(r"\d+(\.\d+)*", self.superseded_since):
            raise ValueError(
                f"superseded_since must be a dotted version like '26.8', got {self.superseded_since!r}"
            )
        if not self.graph:
            raise ValueError("a pattern must define a `graph`")
        if self.runnable and not self.profiles:
            raise ValueError("runnable patterns must declare at least one profile")
        if self.runnable and not self.driver_node:
            raise ValueError("runnable patterns must declare a driver_node")
        unknown_profiles = set(self.profiles) - known_profiles()
        if unknown_profiles:
            raise ValueError(
                f"unknown profile(s) {sorted(unknown_profiles)}; "
                f"known: {sorted(known_profiles())}"
            )

        nodes = known_nodes()
        referenced = {self.driver_node} if self.driver_node else set()
        referenced |= {e.node for e in self.ready_when if e.node}
        unknown_nodes = referenced - nodes
        if unknown_nodes:
            raise ValueError(
                f"unknown node(s) {sorted(unknown_nodes)}; known: {sorted(nodes)}"
            )

        config_nodes = {item.node for item in self.clickhouse_config}
        unknown_config_nodes = config_nodes - nodes
        if unknown_config_nodes:
            raise ValueError(
                f"unknown clickhouse_config node(s) {sorted(unknown_config_nodes)}; "
                f"known: {sorted(nodes)}"
            )
        destinations = [(item.node, item.directory, item.destination_name) for item in self.clickhouse_config]
        if len(destinations) != len(set(destinations)):
            raise ValueError("clickhouse_config cannot mount two fragments at the same destination")

        # Only check single-file fields the author set explicitly. Defaults that
        # happen to be absent are fine; the runner skips them.
        if self.dir != Path():
            missing = []
            for field in ("schema_sql", "load"):
                if field in self.model_fields_set:
                    val = getattr(self, field)
                    if val and not (self.dir / val).exists():
                        missing.append(val)
            if "verify" in self.model_fields_set:
                for val in (self.verify.sql, self.verify.expected):
                    if val and not (self.dir / val).exists():
                        missing.append(val)
            for item in self.clickhouse_config:
                if not (self.dir / item.file).is_file():
                    missing.append(item.file)
            if missing:
                raise ValueError(
                    f"referenced file(s) not found in {self.dir}: "
                    f"{sorted(set(missing))}"
                )
        return self


class GroupLink(BaseModel):
    """A cross-reference from one group to another, with a lead-in note."""

    model_config = ConfigDict(extra="forbid")

    group: str
    note: str = ""


class Group(BaseModel):
    """A family of patterns, defined by a `group.yaml` in a group folder."""

    model_config = ConfigDict(extra="forbid")

    title: str
    label: str = ""          # short filter-chip label; defaults to title
    description: str = ""
    icon: str = "database"
    order: int = 1000
    intro: str = ""
    advisories: list[GroupAdvisory] = Field(default_factory=list)
    related: list[GroupLink] = Field(default_factory=list)
    key: str = ""    # filled by the loader (the group folder name)


def discover_groups() -> list[Group]:
    """Discover curated group definitions from patterns/<group>/group.yaml."""
    groups = [
        Group(key=gy.parent.name, **(yaml.safe_load(gy.read_text()) or {}))
        for gy in sorted(PATTERNS_DIR.glob("*/group.yaml"))
    ]
    return sorted(groups, key=lambda group: (group.order, group.title))


def _load_pattern_dir(directory: Path, slug: str, location: str, group: str = "") -> Pattern:
    manifest = directory / "pattern.yaml"
    if not manifest.exists():
        raise FileNotFoundError(f"no pattern.yaml in {directory}")
    try:
        data = yaml.safe_load(manifest.read_text()) or {}
    except yaml.YAMLError as exc:
        raise PatternManifestError(f"{_manifest_path(manifest)}: {str(exc).splitlines()[0]}") from exc
    if not group:
        group = directory.parent.name if location == "library" else "workspaces"
    try:
        return Pattern(slug=slug, dir=directory, location=location, group=group, **data)
    except ValidationError as exc:
        raise _manifest_error(manifest, exc) from exc


def load_pattern_dir(directory: Path, slug: str, location: str = "library") -> Pattern:
    """Load a pattern from an exact directory, as recorded by a live session."""
    return _load_pattern_dir(directory.resolve(), slug, location)


def load_pattern(slug: str) -> Pattern:
    validate_pattern_slug(slug)
    candidates = [(m.parent, "library") for m in PATTERNS_DIR.glob(f"*/{slug}/pattern.yaml")]
    candidates.extend((root / slug, "workspace") for root in workspace_pattern_dirs())
    matches = [(directory, location) for directory, location in candidates
               if (directory / "pattern.yaml").exists()]
    if not matches:
        searched = ", ".join(str(directory) for directory, _ in candidates)
        raise FileNotFoundError(f"no pattern {slug!r}; searched {searched}")
    if len(matches) > 1:
        paths = ", ".join(str(directory) for directory, _ in matches)
        raise ValueError(f"pattern {slug!r} is ambiguous; found in {paths}")
    directory, location = matches[0]
    return _load_pattern_dir(directory, slug, location)


def discover_patterns() -> list[Pattern]:
    """Discover curated library patterns only."""
    return [
        _load_pattern_dir(p.parent, p.parent.name, "library")
        for p in sorted(PATTERNS_DIR.glob("*/*/pattern.yaml"))
    ]


def discover_cloned_patterns() -> list[Pattern]:
    """Compatibility alias for workspace-pattern discovery."""
    return discover_workspace_patterns()


def workspace_pattern_dirs() -> list[Path]:
    """Return writable, canonical, legacy, and explicitly configured workspace roots."""
    roots = [workspace_pattern_write_dir(), WORKSPACE_PATTERNS_DIR]
    # Tests and embedders that replace the canonical root should remain isolated.
    if WORKSPACE_PATTERNS_DIR == _DEFAULT_WORKSPACE_PATTERNS_DIR:
        roots.append(LEGACY_CLONED_PATTERNS_DIR)
    configured = os.environ.get("CLICKHOUSE_PATTERN_WORKSPACES", "")
    roots.extend(Path(value).expanduser() for value in configured.split(os.pathsep) if value)
    unique: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        resolved = root.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return unique


def workspace_pattern_write_dir() -> Path:
    """Return the root used by workspace-creation commands.

    An external root makes it possible to keep private workspace patterns in a
    separate Git repository while the public catalog remains unchanged.
    """
    configured = os.environ.get("CLICKHOUSE_PATTERN_WORKSPACE_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return WORKSPACE_PATTERNS_DIR.resolve()


def discover_workspace_patterns() -> list[Pattern]:
    """Discover company/team workspace patterns outside the curated library."""
    patterns: list[Pattern] = []
    seen: dict[str, Path] = {}
    for root in workspace_pattern_dirs():
        for manifest in sorted(root.glob("*/pattern.yaml")):
            slug = manifest.parent.name
            if slug in seen:
                raise ValueError(
                    f"workspace pattern {slug!r} is ambiguous; found in "
                    f"{seen[slug]} and {manifest.parent}"
                )
            seen[slug] = manifest.parent
            patterns.append(_load_pattern_dir(manifest.parent, slug, "workspace"))
    return patterns
