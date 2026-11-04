from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[2]

def test_docs_and_ruff_version_alignment():
    config = tomllib.loads((ROOT / "ruff.toml").read_text())
    setup = tomllib.loads((ROOT / "setup/pyproject.toml").read_text())
    pin = next(dep for dep in setup["project"]["dependencies"] if dep.startswith("ruff=="))
    assert pin == f"ruff{config['required-version']}"
    readme = (ROOT / "setup/README.md").read_text()
    agents = (ROOT / "AGENTS.md").read_text()
    command = "uv run --project setup --locked ruff check --select I"
    assert command in readme and command in agents
    assert "To bump Ruff" in readme and "setup/.venv/bin/ruff" in readme