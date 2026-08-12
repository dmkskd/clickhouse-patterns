# ClickHouse Pattern Explorer - document, compare, and run architecture patterns.
#
#   just agent-setup              # configure Codex and Claude integrations
#   just agent-status             # verify skill and MCP adapters
#   just list                     # patterns grouped by category, flow, and topology
#   just describe                 # what each pattern does
#   just show <pattern>           # detailed info for one pattern
#   just diagram <pattern>        # generate SVG + refresh the Pattern Explorer
#   just site                     # build the backend-free static catalog
#   just build-single             # build one self-contained catalog HTML file
#   just explore                  # browse, start, validate, and inspect patterns
#   just new <name>               # new documentation-first workspace pattern
#   just clone <pattern> <name>   # derive an editable workspace pattern
#   just delete <name>            # delete an inactive workspace pattern
#   just run <pattern>            # validate → explore until Enter/Ctrl+C → clean up
#   just start <pattern>          # advanced: prepare a detached live session
#   just status                   # active pattern and ClickHouse endpoint
#   just validate                 # validate the live session
#   just reload                   # rebuild the session from edited source
#   just stop                     # tear the live session down
#   just test <pattern>           # up → run → assert → down
#   just test <pattern> --update  # regenerate expected.txt from verify output
#   just up/down <pattern>        # low-level infrastructure only
#   just test-all                 # run every pattern
#   just pytest                   # same, via pytest (parametrized)

set positional-arguments

[private]
default:
    @just --list
    @printf '\nExamples:\n\n  Agent setup (runtime + authoring skills, read-only MCP):\n    just agent-setup\n    just agent-status\n\n  Explore a validated pattern (waits for Enter/Ctrl+C, then cleans up):\n    just run kafka-ingest-replicated\n\n  Start a documentation-first company pattern:\n    just new our-orders-cdc\n    just diagram our-orders-cdc\n\n  Derive an existing runnable pattern:\n    just clone cdc-postgres-peerdb my-orders-cdc\n    just run my-orders-cdc\n'

# Configure the shared skill for Codex, Claude, or all supported agents.
[group('Agent')]
agent-setup *args:
    uv run python -m pattern_explorer agent-setup {{args}}

# Show skill discovery and MCP adapter status for supported agents.
[group('Agent')]
agent-status *agents:
    uv run python -m pattern_explorer agent-status {{agents}}

# Backward-compatible alias for Codex-only skill setup.
[group('Agent')]
skill-install:
    @just agent-setup codex

# Install Pattern Explorer dependencies and configure supported agent clients.
[group('General')]
setup:
    uv sync --extra dev
    @just agent-setup

# List all patterns in a compact table.
[group('General')]
list:
    uv run python -m pattern_explorer list

# Describe what every pattern does.
[group('General')]
describe:
    uv run python -m pattern_explorer describe

# Show one pattern's files and validation checks.
[group('Patterns')]
show pattern:
    uv run python -m pattern_explorer show {{pattern}}

# Generate an SVG + HTML architecture preview from the compact resource graph.
[group('Patterns')]
diagram pattern *flags:
    uv run python -m pattern_explorer diagram {{pattern}} {{flags}}

# Build the static catalog; pass --output-dir for a deployable destination.
[group('Patterns')]
site *flags:
    uv run python -m pattern_explorer catalog --output .runtime/catalog.js
    node explorer/scripts/build-static.mjs --catalog .runtime/catalog.js --output-dir .runtime/site {{flags}}

# Build one self-contained HTML catalog that works directly from file://.
[group('Patterns')]
build-single *flags:
    uv run python -m pattern_explorer catalog --output .runtime/catalog.js
    node explorer/scripts/build-static.mjs --single --catalog .runtime/catalog.js --output .runtime/pattern-explorer.html {{flags}}

# Open the interactive catalog and local pattern control plane.
[group('Patterns')]
explore *flags:
    uv run python -m pattern_explorer explorer {{flags}}

# Create a documentation-first workspace pattern from scratch.
[group('Patterns')]
new name:
    uv run python -m pattern_explorer new {{name}}

# Derive an editable workspace pattern from a library or workspace pattern.
[group('Patterns')]
clone pattern name:
    uv run python -m pattern_explorer clone {{pattern}} {{name}}

# Delete an inactive workspace pattern; curated library patterns are never removed.
[group('Patterns')]
delete name:
    uv run python -m pattern_explorer delete {{name}}

# Validate a pattern, wait while the user explores it, then clean up.
[group('Patterns')]
run pattern *flags:
    uv run python -m pattern_explorer run {{pattern}} {{flags}}

# Advanced: prepare a detached live pattern and leave it running.
[group('Patterns')]
start pattern:
    uv run python -m pattern_explorer start {{pattern}}

# Show the active pattern and ClickHouse endpoint.
[group('Patterns')]
status *flags:
    uv run python -m pattern_explorer status {{flags}}

# Validate the active pattern without stopping it.
[group('Patterns')]
validate *flags:
    uv run python -m pattern_explorer validate {{flags}}

# Rebuild the active pattern from its current source.
[group('Patterns')]
reload:
    uv run python -m pattern_explorer reload

# Stop the active pattern and remove its volumes.
[group('Patterns')]
stop:
    uv run python -m pattern_explorer stop

# Run one pattern end to end and tear it down.
[group('Testing')]
test pattern *flags:
    uv run python -m pattern_explorer test {{pattern}} {{flags}}

# Start only the infrastructure for a pattern.
[group('Infrastructure')]
up pattern:
    uv run python -m pattern_explorer up {{pattern}}

# Stop the low-level infrastructure for a pattern.
[group('Infrastructure')]
down pattern:
    uv run python -m pattern_explorer down {{pattern}}

# Run every pattern end to end.
[group('Testing')]
test-all:
    uv run python -m pattern_explorer test-all

# Run the parametrized pytest suite.
[group('Testing')]
pytest *flags:
    uv run --extra dev pytest {{flags}}
