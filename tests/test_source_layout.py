import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_pattern_content_is_separate_from_explorer_code():
    assert (ROOT / "patterns").is_dir()
    assert (ROOT / "workspace-patterns").is_dir()
    assert (ROOT / "explorer" / "app.js").is_file()
    assert (ROOT / "integrations" / "agent_setup.py").is_file()
    assert 'id="pattern-references"' in (ROOT / "explorer" / "index.html").read_text()


def test_python_namespace_has_explicit_responsibility_boundaries():
    package = ROOT / "pattern_explorer"
    assert {path.name for path in package.iterdir() if path.is_dir() and not path.name.startswith("_")} == {
        "catalog",
        "orchestration",
        "rendering",
        "server",
    }
    assert not list((ROOT / "harness").glob("*.py"))


def test_catalog_does_not_depend_on_execution_or_presentation_layers():
    forbidden = {"orchestration", "rendering", "server"}
    for path in (ROOT / "pattern_explorer" / "catalog").glob("*.py"):
        imports = []
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        assert not any(set(module.split(".")) & forbidden for module in imports), path
