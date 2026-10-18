"""Independent probes for issue 116: retirement, recovery, and check preservation."""
import shlex
import sys
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/implementation-loop"))
from implement_loop import verify
from implement_loop.config import Caps
from implement_loop.engine import Engine
from implement_loop.model import CheckSpec, IssueState, Phase
from implement_loop.state import RunStore


class Workspace:
    def commit_all(self, *args, **kwargs):
        return "fixture-head"

    def head(self, *args):
        return "fixture-head"


def setup_engine(tmp_path):
    wt = tmp_path / "work"
    wt.mkdir()
    engine = Engine.__new__(Engine)
    engine.store = RunStore(tmp_path / "state")
    engine.ws, engine.caps = Workspace(), Caps()
    engine.repair, engine.other = False, "codex"
    return engine, wt


def check(engine, st, wt, tmp_path):
    return verify.verify(wt, engine._specs(st), "fixture-head", tmp_path / "evidence",
                         st.locked, st.tests + st.probes, st.manifest)


def probe(file, command, content, criterion="D1", cwd="."):
    return SimpleNamespace(file=file, command=command, content=content, criterion=criterion, cwd=cwd)


def test_approved_deletion_retires_only_the_deleted_probe_command(tmp_path):
    engine, wt = setup_engine(tmp_path)
    (wt / "session").mkdir()
    (wt / "session/replacement.py").write_text("assert 2 + 2 == 4\n")
    py = shlex.quote(sys.executable)
    st = IssueState(number=50, commands=[asdict(CheckSpec("D1", command=f"{py} replacement.py", cwd="session"))])
    engine.store.put(st)
    engine._lock_and_adopt(50, wt, [
        probe("session/old.py", f"{py} old.py", "assert 2 + 2 == 4\n", cwd="session"),
        probe("session/kept.py", f"{py} kept.py", "assert 3 * 3 == 9\n", cwd="session"),
    ], first=True)
    st = engine.store.issue(50)
    assert check(engine, st, wt, tmp_path)[0]
    engine._apply_request(50, st, wt, {"id": "approved-delete", "kind": "test_change",
        "content": {"session/old.py": None}}, {})
    assert len(st.commands) == 2
    assert any(c["author"] == "builder" for c in st.commands)
    assert any(c["command"] == f"{py} kept.py" for c in st.commands)
    ok, evidence, problems, _ = check(engine, st, wt, tmp_path)
    assert ok, problems
    assert len(evidence) == 2


def test_revival_heals_a_pre_fix_orphan_and_preserves_the_ceiling(tmp_path):
    engine, wt = setup_engine(tmp_path)
    py = shlex.quote(sys.executable)
    (wt / "replacement.py").write_text("assert 2 + 2 == 4\n")
    st = IssueState(number=50, phase=Phase.FAILED, plan={"items": []}, worktree=str(wt),
        fail={"version": "1.0.5", "cause": "ceiling"},
        commands=[asdict(CheckSpec("D1", command=f"{py} replacement.py")),
                  asdict(CheckSpec("D1", command=f"{py} deleted.py", author="examiner"))])
    engine.store.put(st)
    engine.store.change_budget(50, calls=20)
    assert not check(engine, st, wt, tmp_path)[0]
    engine._maybe_revive(st)
    assert st.phase == Phase.BUILD
    assert st.fail["resumed"]
    assert engine.store.budget(50)["calls"] == 20
    assert engine.store.budget(50)["bonus"] == 20
    assert check(engine, st, wt, tmp_path)[0]


def test_unrelated_approved_edit_must_not_drop_an_existing_module_probe(tmp_path):
    engine, wt = setup_engine(tmp_path)
    (wt / "checks").mkdir()
    (wt / "checks/other.py").write_text("# unrelated locked check\n")
    (wt / "product.txt").write_text("good")
    py = shlex.quote(sys.executable)
    st = IssueState(number=50, tests=["checks/other.py"],
        commands=[asdict(CheckSpec("D1", command=f'{py} -c "print(1)"'))])
    engine.store.put(st)
    engine._lock_and_adopt(50, wt, [probe("checks/probe_contract.py", f"{py} -m checks.probe_contract",
        "from pathlib import Path\nassert Path('product.txt').read_text() == 'good'\n")], first=True)
    st = engine.store.issue(50)
    assert check(engine, st, wt, tmp_path)[0]
    (wt / "product.txt").write_text("broken")
    assert not check(engine, st, wt, tmp_path)[0], "the adopted probe detects the broken product"
    engine._apply_request(50, st, wt, {"id": "unrelated-edit", "kind": "test_change",
        "content": {"checks/other.py": "# approved edit of another locked check\n"}}, {})
    assert (wt / "checks/probe_contract.py").is_file()
    assert "checks/probe_contract.py" in st.probes
    ok, evidence, problems, _ = check(engine, st, wt, tmp_path)
    assert not ok, f"Unrelated test_change silently bypassed a live failing probe: {evidence}"
