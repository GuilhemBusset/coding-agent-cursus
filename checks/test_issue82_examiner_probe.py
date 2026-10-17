"""Independent real-git probes for the dirty-worktree update recovery in #82."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "implementation-loop" / "tests"))
import test_engine_recovery as recovery
from implement_loop.engine import Engine
from implement_loop.model import Phase
from implement_loop.workspace import GitError, Workspace


@pytest.fixture
def case():
    instance = recovery.RecoveryCase(methodName="runTest")
    instance.setUp()
    try:
        instance.add_work(2, "docs/a.txt", "alpha")
        instance.epic(2)
        yield instance
    finally:
        instance.tearDown()


def run_race(case, monkeypatch, local, remote):
    step = Engine._step_build
    update = Workspace.update
    seen = {}

    def leave_dirty(engine, n):
        wt = engine.ws.issue_worktree(n, engine.store.issue(n).branch)
        (wt / "README.md").write_text(local)
        (wt / "keep.txt").write_text("interrupted work\n")
        return step(engine, n)

    def move_after_first_fetch(ws, wt):
        if not seen.get("moved"):
            seen["moved"] = True
            case.move_main({"README.md": remote})
        return update(ws, wt)

    def observe_builder_input(engine, n, wt, sync):
        seen.update(status=sync.status, files=sync.files,
                    readme=(wt / "README.md").read_text(),
                    kept=(wt / "keep.txt").read_text(),
                    checkpoint=engine.ws.git("show", "HEAD:README.md", cwd=wt))
        (engine.store.dir / "STOP").write_text("probe reached builder\n")

    monkeypatch.setattr(Engine, "_step_build", leave_dirty)
    monkeypatch.setattr(Workspace, "update", move_after_first_fetch)
    monkeypatch.setattr(Engine, "_build_round", observe_builder_input)
    case.run_engine()
    assert not case.events("step_crashed", 2)
    assert seen["kept"] == "interrupted work\n"
    checkpoints = case.events("checkpoint_before_update", 2)
    assert len(checkpoints) == 1 and checkpoints[0].get("retried")
    wt = Path(case.store.issue(2).worktree)
    assert case.engine.ws.git("show", checkpoints[0]["sha"] + ":README.md", cwd=wt) == local.strip()
    return seen


def test_tracked_work_survives_update_race_and_merges_both_sides(case, monkeypatch):
    base = "\n".join(f"line {n}" for n in range(30)) + "\n"
    case.move_main({"README.md": base})
    local = base.replace("line 0\n", "local first line\n")
    remote = base.replace("line 29\n", "main last line\n")
    seen = run_race(case, monkeypatch, local, remote)
    assert seen["status"] == "merged"
    assert seen["files"] == []
    assert seen["readme"] == local.replace("line 29\n", "main last line\n")


def test_retry_exposes_real_conflict_to_builder_and_keeps_checkpoint(case, monkeypatch):
    seen = run_race(case, monkeypatch, "local work\n", "main work\n")
    assert seen["status"] == "conflict"
    assert seen["files"] == ["README.md"]
    assert "<<<<<<<" in seen["readme"]
    assert "local work" in seen["readme"] and "main work" in seen["readme"]
    assert seen["checkpoint"] == "local work"
    wt = Path(case.store.issue(2).worktree)
    assert case.engine.ws.in_progress(wt) is None
    assert (wt / "README.md").read_text() == "local work\n"


def test_clean_update_failure_remains_visible_without_retry(case, monkeypatch):
    calls = []

    def fail_update(ws, wt):
        calls.append(wt)
        raise GitError("independent persistent git failure")

    monkeypatch.setattr(Workspace, "update", fail_update)
    case.run_engine()
    assert len(calls) == 1
    assert case.phase(2) == Phase.WAITING
    assert len(case.events("step_crashed", 2)) == 1
    assert not case.events("checkpoint_before_update", 2)
