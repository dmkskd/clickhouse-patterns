"""Run every pattern as a parametrized pytest case.

    uv run pytest                      # all patterns
    uv run pytest -k kafka             # one pattern
"""
import pytest

from pattern_explorer.catalog.manifest import discover_patterns
from pattern_explorer.orchestration.runner import run_pattern

PATTERNS = discover_patterns()


@pytest.mark.parametrize("pattern", PATTERNS, ids=[p.slug for p in PATTERNS])
def test_pattern(pattern):
    result = run_pattern(pattern)
    assert result.passed, result.detail
