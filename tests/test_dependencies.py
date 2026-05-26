import ast
import sys
from pathlib import Path

_SRC = Path(__file__).parent.parent / "src" / "minimost"

# werkzeug is always co-installed with Flask (it's Flask's own utility library)
_ALLOWED_THIRD_PARTY = {"flask", "werkzeug"}


def _top_level_package(name: str) -> str:
    return name.split(".")[0]


def _collect_third_party_imports(path: Path) -> dict[str, set[str]]:
    """Return a mapping of file -> set of third-party top-level packages imported."""
    results: dict[str, set[str]] = {}
    for py_file in path.rglob("*.py"):
        tree = ast.parse(py_file.read_text(), filename=str(py_file))
        third_party: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    pkg = _top_level_package(alias.name)
                    if pkg not in sys.stdlib_module_names and pkg != "minimost":
                        third_party.add(pkg)
            elif isinstance(node, ast.ImportFrom):
                if node.level > 0:
                    continue  # relative import
                if node.module is None:
                    continue
                pkg = _top_level_package(node.module)
                if pkg not in sys.stdlib_module_names and pkg != "minimost":
                    third_party.add(pkg)
        if third_party:
            results[str(py_file.relative_to(_SRC.parent.parent))] = third_party
    return results


def test_only_flask_dependency():
    imports = _collect_third_party_imports(_SRC)
    violations: dict[str, set[str]] = {
        f: pkgs - _ALLOWED_THIRD_PARTY for f, pkgs in imports.items()
    }
    violations = {f: pkgs for f, pkgs in violations.items() if pkgs}
    assert not violations, (
        "Unexpected third-party imports found (only 'flask' is allowed):\n"
        + "\n".join(f"  {f}: {sorted(pkgs)}" for f, pkgs in sorted(violations.items()))
    )
