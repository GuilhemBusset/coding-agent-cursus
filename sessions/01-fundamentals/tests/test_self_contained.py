"""Static import boundaries, complemented by the engine's isolated-copy run.

These checks cover the agreed import mechanisms, not arbitrary Python execution;
the acceptance evidence also requires source review of every session Python file.
"""

import ast
from pathlib import Path
import re
import sys
import tomllib


SESSION = Path(__file__).resolve().parents[1]
FORBIDDEN_IMPORTS = {"importlib", "runpy", "imp", "site"}


def visible_files(pattern):
    return [
        path for path in sorted(SESSION.rglob(pattern))
        if not any(part.startswith(".") for part in path.relative_to(SESSION).parts)
    ]


def import_problems(source, path, allowed_roots):
    """Inspect syntax, including common import aliases, without executing it."""
    tree = ast.parse(source, filename=str(path))
    problems = []
    sys_names = {"sys"}
    builtin_names = {"builtins"}
    dynamic_names = {"__import__"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "sys":
                    sys_names.add(alias.asname or "sys")
                if alias.name == "builtins":
                    builtin_names.add(alias.asname or "builtins")
        elif isinstance(node, ast.ImportFrom) and node.module == "builtins":
            for alias in node.names:
                if alias.name == "__import__":
                    dynamic_names.add(alias.asname or alias.name)

    def report(node, message):
        problems.append(f"{path}:{node.lineno}: {message}")

    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = path.parent
                for _ in range(node.level - 1):
                    base = base.parent
                if not base.resolve().is_relative_to(SESSION):
                    report(node, "relative import escapes session")
            elif node.module:
                names = [node.module]
                if node.module == "sys" and any(alias.name in {"path", "*"} for alias in node.names):
                    report(node, "sys.path import is forbidden")
        for name in names:
            root = name.split(".")[0]
            if root in FORBIDDEN_IMPORTS:
                report(node, f"dynamic import mechanism: {name}")
            elif root not in allowed_roots:
                # Absolute imports may resolve beside the script or from a
                # session-local package root, but never from an ancestor repo.
                bases = [path.parent, SESSION]
                candidates = [candidate for base in bases for candidate in (base / f"{root}.py", base / root)]
                if not any(
                    candidate.exists() and candidate.resolve().is_relative_to(SESSION)
                    for candidate in candidates
                ):
                    report(node, f"undeclared, non-local import: {name}")
        if isinstance(node, ast.Attribute) and node.attr == "path":
            if isinstance(node.value, ast.Name) and node.value.id in sys_names:
                report(node, "sys.path access is forbidden")
        if isinstance(node, ast.Call):
            function = node.func
            direct = isinstance(function, ast.Name) and function.id in dynamic_names
            qualified = (
                isinstance(function, ast.Attribute) and function.attr == "__import__"
                and isinstance(function.value, ast.Name) and function.value.id in builtin_names
            )
            if direct or qualified:
                report(node, "dynamic __import__ call is forbidden")
    return problems


def test_python_imports_stay_in_session():
    config = tomllib.loads((SESSION / "pyproject.toml").read_text(encoding="utf-8"))
    requirements = list(config["project"]["dependencies"])
    requirements.extend(
        item for item in config.get("dependency-groups", {}).get("fixtures", [])
        if isinstance(item, str)
    )
    dependencies = {
        re.match(r"\s*([\w.-]+)", requirement)[1].lower().replace("-", "_")
        for requirement in requirements
    }
    allowed = sys.stdlib_module_names | dependencies
    paths = visible_files("*.py")
    assert paths, "Session must have its own Python tests"
    problems = []
    for path in paths:
        if not path.resolve().is_relative_to(SESSION):
            problems.append(f"{path}: symlink escapes session")
        problems.extend(import_problems(path.read_text(encoding="utf-8"), path, allowed))
    assert not problems, "\n".join(problems)


def test_no_import_path_overrides():
    config = tomllib.loads((SESSION / "pyproject.toml").read_text(encoding="utf-8"))
    tool = config.get("tool", {})
    assert "sources" not in tool.get("uv", {}), "No external uv sources"
    assert "pythonpath" not in tool.get("pytest", {}).get("ini_options", {}), "No pytest path injection"
    pth_files = [
        str(path.relative_to(SESSION)) for path in SESSION.rglob("*.pth")
        if ".venv" not in path.relative_to(SESSION).parts
    ]
    assert not pth_files, f"Unexpected import path files: {pth_files}"


def test_import_checker_rejects_external_and_dynamic_imports():
    path = SESSION / "tests/example.py"
    for source in (
        "import repo_shared_core",
        "from repo_shared_core.solver import solve",
        "import sys as runtime\nruntime.path.append('../..')",
        "from sys import path as search_path",
        "__import__('repo_shared_core')",
        "import builtins as b\nb.__import__('repo_shared_core')",
        "from builtins import __import__ as load\nload('repo_shared_core')",
        "import importlib.util as loader",
        "from runpy import run_path",
        "import imp",
        "import site",
        "from ...outside import solve",
    ):
        assert import_problems(source, path, sys.stdlib_module_names), source


def test_import_checker_accepts_stdlib_dependencies_and_pattern_literals():
    source = '''
import ast
from pathlib import Path
import numpy as np
from highspy import Highs
patterns = ["sys.path", "__import__", "importlib", "runpy", "imp", "site"]
# import repo_shared_core
'''
    assert not import_problems(source, SESSION / "tests/example.py", sys.stdlib_module_names | {"numpy", "highspy"})
