"""Check a session's test environment and write its pinned Python and uv to $GITHUB_OUTPUT.

Run from the session folder by .github/workflows/session-tests.yml. A session's tests run in its
pinned environment (mise.toml, pyproject.toml, uv.lock), in parallel through a `parallel`
dependency group, and its Python is type-checked by the ty that setup/pyproject.toml pins.
"""

import os
import sys
import tomllib
from pathlib import Path

session = os.environ["SESSION"]
for name in ("pyproject.toml", "uv.lock", "mise.toml"):
    if not Path(name).is_file():
        sys.exit(f"::error file={session}/{name}::A session's tests run in its pinned environment; {name} is missing")
with open("pyproject.toml", "rb") as f:
    config = tomllib.load(f)
groups = config.get("dependency-groups", {})
if not any(str(dep).startswith("pytest-xdist") for dep in groups.get("parallel", [])):
    sys.exit(f"::error file={session}/pyproject.toml::The session's tests run in parallel; add pytest-xdist "
             "to a `parallel` dependency group (uv add --group parallel pytest-xdist)")
with open("../../setup/pyproject.toml", "rb") as f:
    ty = next(dep for dep in tomllib.load(f)["project"]["dependencies"] if dep.startswith("ty=="))
if ty not in groups.get("typecheck", []):
    sys.exit(f"::error file={session}/pyproject.toml::The session's Python is type-checked with the ty "
             f"setup/pyproject.toml pins; put {ty} in a `typecheck` dependency group (uv add --group typecheck {ty})")
if "ty" not in config.get("tool", {}):
    # Without it, ty walks up to the root ty.toml and checks the repository's code instead.
    sys.exit(f"::error file={session}/pyproject.toml::Configure the session's type check in a [tool.ty] "
             "table (see setup/README.md#type-checking)")
with open("mise.toml", "rb") as f:
    tools = tomllib.load(f)["tools"]
with open(os.environ["GITHUB_OUTPUT"], "a") as out:
    out.write(f"python={tools['python']}\nuv={tools['uv']}\n")
print(f"python {tools['python']}, uv {tools['uv']}")
