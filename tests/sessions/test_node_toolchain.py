"""Local Node manifests agree with the runtime and lock used by the student installer."""

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SESSION = ROOT / "sessions/02-research-agents"


def test_node_runtime_and_dependency_pins_match_lock():
    package = json.loads((SESSION / "package.json").read_text())
    lock = json.loads((SESSION / "package-lock.json").read_text())
    pins = tomllib.loads((SESSION / "mise.toml").read_text())["tools"]
    assert package["engines"]["node"] == pins["node"]
    assert package["packageManager"] == "npm@" + package["engines"]["npm"]
    for group in ("dependencies", "devDependencies"):
        assert lock["packages"][""][group] == package[group]
        for name, version in package[group].items():
            assert lock["packages"]["node_modules/" + name]["version"] == version
            assert lock["packages"]["node_modules/" + name]["integrity"]
    assert package["dependencies"]["@earendil-works/pi-ai"] == package["dependencies"]["@earendil-works/pi-agent-core"]


def test_scaffold_has_separate_student_and_supplied_work():
    for folder in ("cursus", "exercises/harness", "exercises/prompts", "exercises/fixed",
                   "exercises/cases", "exercises/runs", "tests/labs"):
        assert (SESSION / folder).is_dir()
    workspace = json.loads((ROOT / "setup/cursus.code-workspace").read_text())
    assert any((ROOT / "setup" / folder["path"]).resolve() == SESSION for folder in workspace["folders"])
