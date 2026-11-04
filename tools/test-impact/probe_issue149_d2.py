from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def test_repo_checks_runs_locked_import_check():
    workflow = (ROOT / ".github/workflows/checks.yml").read_text()
    command = "uv run --project setup --locked ruff check --select I ."
    assert "- name: Import order" in workflow
    assert command in workflow
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "checks.yml" in ci and "required" in ci