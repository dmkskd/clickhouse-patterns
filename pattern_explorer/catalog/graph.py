"""Parse the compact resource-flow DSL into a normalized graph AST."""
from __future__ import annotations

import re
from dataclasses import dataclass, field


_FLOW = re.compile(r"^([a-z][a-z0-9_-]*):\s*(.*)$", re.IGNORECASE)
_EDGE = re.compile(r"\s*(?:-\[([^]]+)\]->|->)\s*")
_RESOURCE = re.compile(
    r"^(?:(?P<kind>[a-z][a-z0-9-]*):)?"
    r"(?P<name>[a-zA-Z0-9_.-]+)"
    r"(?:@(?P<scope>[a-zA-Z0-9_.-]+))?"
    r"(?:\((?P<properties>.*)\))?$"
)


class GraphSyntaxError(ValueError):
    """A compact graph declaration could not be parsed."""


@dataclass
class Resource:
    key: str
    kind: str
    name: str
    scope: str | None = None
    properties: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Connection:
    source: str
    target: str
    flow: str
    label: str | None = None


@dataclass
class ResourceGraph:
    resources: dict[str, Resource] = field(default_factory=dict)
    connections: list[Connection] = field(default_factory=list)
    flows: list[str] = field(default_factory=list)


# A comma only starts a new property when a `key=` follows it. Without this,
# ordinary prose in a `note=` value ("Peers, mirror config, history") was split
# into bogus valueless properties and rendered as `mirror config true`.
_PROPERTY_SEPARATOR = re.compile(r",(?=\s*[a-zA-Z][a-zA-Z0-9_-]*\s*=)")


def _properties(value: str | None) -> dict[str, str]:
    if not value:
        return {}
    result: dict[str, str] = {}
    for item in _PROPERTY_SEPARATOR.split(value):
        item = item.strip()
        if not item:
            continue
        if "=" in item:
            key, prop_value = item.split("=", 1)
        else:
            key, prop_value = item, "true"
        key = key.strip()
        if not key:
            raise GraphSyntaxError(f"invalid property list ({value})")
        result[key] = prop_value.strip()
    return result


def _resource(token: str) -> Resource:
    token = token.strip()
    match = _RESOURCE.fullmatch(token)
    if not match:
        raise GraphSyntaxError(f"invalid resource `{token}`")
    kind = match.group("kind") or match.group("name")
    name = match.group("name")
    scope = match.group("scope")
    key = f"{kind}:{name}" + (f"@{scope}" if scope else "")
    return Resource(
        key=key,
        kind=kind,
        name=name,
        scope=scope,
        properties=_properties(match.group("properties")),
    )


def _targets(token: str) -> list[Resource]:
    token = token.strip()
    if token.startswith("{") and token.endswith("}"):
        values = [part.strip() for part in token[1:-1].split(",")]
        if not all(values):
            raise GraphSyntaxError(f"invalid fan-out `{token}`")
        return [_resource(value) for value in values]
    return [_resource(token)]


def parse_resource_graph(source: str) -> ResourceGraph:
    """Parse named Mermaid-like paths into a normalized resource graph."""
    graph = ResourceGraph()
    expressions: list[tuple[str, str]] = []
    current_flow: str | None = None
    current: list[str] = []

    def flush() -> None:
        nonlocal current
        if current_flow and current:
            expressions.append((current_flow, " ".join(current)))
        current = []

    for raw in source.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        top_level = raw == raw.lstrip()
        match = _FLOW.fullmatch(raw.strip()) if top_level else None
        if match:
            flush()
            current_flow = match.group(1).lower()
            if current_flow not in graph.flows:
                graph.flows.append(current_flow)
            if match.group(2):
                current.append(match.group(2).strip())
            continue
        if current_flow is None:
            raise GraphSyntaxError(
                "resource paths must start below a named flow such as `ingestion:`"
            )
        current.append(raw.strip())
    flush()

    if not expressions:
        raise GraphSyntaxError("graph has no resource paths")

    for flow, expression in expressions:
        pieces = _EDGE.split(expression)
        if len(pieces) < 3:
            raise GraphSyntaxError(f"flow `{flow}` needs at least one `->` connection")
        sources = _targets(pieces[0])
        for resource in sources:
            _merge_resource(graph, resource)
        index = 1
        while index < len(pieces):
            label = pieces[index] or None
            if index + 1 >= len(pieces):
                raise GraphSyntaxError(f"flow `{flow}` ends with an arrow")
            destinations = _targets(pieces[index + 1])
            for destination in destinations:
                _merge_resource(graph, destination)
            for source_resource in sources:
                for destination in destinations:
                    graph.connections.append(
                        Connection(source_resource.key, destination.key, flow, label)
                    )
            sources = destinations
            index += 2
    return graph


def _merge_resource(graph: ResourceGraph, resource: Resource) -> None:
    existing = graph.resources.get(resource.key)
    if existing is None:
        graph.resources[resource.key] = resource
        return
    for key, value in resource.properties.items():
        old = existing.properties.get(key)
        if old is not None and old != value:
            raise GraphSyntaxError(
                f"resource `{resource.key}` defines conflicting `{key}` values: `{old}` and `{value}`"
            )
        existing.properties[key] = value
