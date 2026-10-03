"""End-to-end runs of the engine: real git, the real ship.sh, the real verifier and real squash
merges into a local bare remote. Only the agents and GitHub are fakes."""

import unittest
from pathlib import Path

from helpers import SHIP, TempRepo, issue_body

from implement_loop.agents import FakeAgents, Script
from implement_loop.config import Caps, Config
from implement_loop.engine import Engine
from implement_loop.github import FakeGitHub
from implement_loop.graph import build_plan
from implement_loop.model import Phase
from implement_loop.state import RunStore
from implement_loop.workspace import Workspace

EPIC = 1


class EngineCase(unittest.TestCase):
    def setUp(self):
        self.repo = TempRepo()
        self.gh = FakeGitHub(on_merge=self.repo.merge)
        self.scripts: dict[int, Script] = {}

    def tearDown(self):
        self.repo.cleanup()

    def add_work(self, n, path, content, blocked_by=(), size="M", **script):
        self.gh.add_issue(n, f"Issue {n}", issue_body(f"feat/issue-{n}", [f"`{path}` contains `{content}`."],
                                                     ["The check passes."]),
                          labels=(f"size:{size}",), blocked_by=blocked_by)
        self.scripts[n] = Script(files={path: content}, **script)

    def epic(self, *children):
        self.gh.add_issue(EPIC, "Epic", "An epic.\n", subs=children)

    def run_engine(self, agents=None, caps=None, fresh=False):
        plan = build_plan(self.gh, EPIC, self.repo.work)
        store = RunStore.for_root(self.repo.work, EPIC, fresh=fresh)
        ws = Workspace(self.repo.work, EPIC, SHIP, base_dir=self.repo.loop_dir)
        self.agents = agents or FakeAgents(self.scripts)
        cfg = Config(repo="test/test", caps=caps or Caps(ci_poll_s=0))
        engine = Engine(plan, store, self.gh, ws, self.agents, cfg, repo_root=self.repo.work,
                        log=lambda m: None, sleep=lambda s: None)
        summary = engine.run()
        self.store = store
        return summary

    def phase(self, n):
        return self.store.issue(n).phase

    def events(self, kind=None, issue=None):
        return [e for e in self.store.events() if (kind is None or e["kind"] == kind) and (issue is None or e.get("issue") == issue)]


class HappyPathTests(EngineCase):
    def test_dependent_issues_land_in_order_with_evidence(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.add_work(3, "docs/b.txt", "beta", blocked_by=(2,))
        self.epic(2, 3)
        summary = self.run_engine()

        self.assertEqual(summary["phases"], {"done": 2})
        self.assertEqual(self.repo.main_file("docs/a.txt"), "alpha")
        self.assertEqual(self.repo.main_file("docs/b.txt"), "beta")
        self.assertEqual(self.repo.main_file("checks/issue_2.sh").splitlines()[0], "#!/usr/bin/env bash")
        merges = [e["issue"] for e in self.events("merged")]
        self.assertEqual(merges, [2, 3])
        first_b_step = min(e["seq"] for e in self.events("phase", 3) if e["to"] == "design")
        a_accepted = min(e["seq"] for e in self.events("phase", 2) if e["to"] == "done")
        self.assertLess(a_accepted, first_b_step, "#3 must wait until #2 is accepted")

        pr = self.gh.prs[self.store.issue(2).pr]
        self.assertTrue(pr["merged"])
        self.assertTrue(pr["body"].startswith("Refs #2"))
        self.assertNotIn("Closes", pr["body"])
        evidence = [c["body"] for c in self.gh.comments[pr["number"]] if "implement-loop:evidence" in c["body"]]
        self.assertEqual(len(evidence), 1)
        self.assertIn("| A1 |", evidence[0])

        body = self.gh.issues[2]["body"]
        self.assertIn("- [x] The check passes. ([evidence](", body)
        self.assertEqual(self.gh.issues[2]["state"], "closed")
        self.assertEqual(self.gh.issues[EPIC]["state"], "closed")
        progress = [c for c in self.gh.comments[2] if "implement-loop:progress" in c["body"]]
        self.assertEqual(len(progress), 1, "the progress comment is updated in place")

    def test_cross_vendor_roles(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        self.run_engine()
        by_kind = {}
        for call in self.agents.calls:
            by_kind.setdefault(call[0], set()).add(call[1])
        self.assertEqual(by_kind["write_checks"], {"codex"})
        self.assertEqual(by_kind["implement"], {"claude"})
        self.assertEqual(by_kind["propose"], {"claude", "codex"})
        reviews = {(c[1], c[2]) for c in self.agents.calls if c[0] == "review"}
        self.assertEqual(reviews, {("codex", "cross"), ("claude", "acceptance")})

    def test_operator_codex_swaps_every_role(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        self.run_engine(agents=FakeAgents(self.scripts, operator="codex", other="claude"))
        implement = {c[1] for c in self.agents.calls if c[0] == "implement"}
        cross = {c[1] for c in self.agents.calls if c[0] == "review" and c[2] == "cross"}
        self.assertEqual((implement, cross), ({"codex"}, {"claude"}))

    def test_small_issues_get_one_proposal(self):
        self.add_work(2, "docs/a.txt", "alpha", size="S")
        self.epic(2)
        self.run_engine()
        self.assertEqual(len([c for c in self.agents.calls if c[0] == "propose"]), 1)

    def test_independent_disjoint_issues_overlap_in_time(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.add_work(3, "docs/b.txt", "beta")
        self.epic(2, 3)
        self.run_engine(caps=Caps(ci_poll_s=0))
        writing = {n: [e for e in self.events("phase", n) if e["to"] == "checks"][0]["seq"] for n in (2, 3)}
        merged = {e["issue"]: e["seq"] for e in self.events("merged")}
        self.assertLess(max(writing.values()), min(merged.values()), "both should start writing before either merges")
        self.assertEqual((self.phase(2), self.phase(3)), (Phase.DONE, Phase.DONE),
                         "the second issue must not fail on files the first one merged")

    def test_overlapping_issues_write_one_at_a_time(self):
        self.add_work(2, "docs/shared.txt", "alpha")
        self.add_work(3, "docs/shared.txt", "alpha")
        self.epic(2, 3)
        self.run_engine()
        starts = sorted((e["seq"], e["issue"]) for e in self.events("phase") if e["to"] == "checks")
        first, second = starts[0][1], starts[1][1]
        first_merged = [e["seq"] for e in self.events("merged") if e["issue"] == first][0]
        self.assertLess(first_merged, starts[1][0], f"#{second} must wait for #{first} to leave the writing phases")


class FailureTests(EngineCase):
    def test_wrong_then_right_implementation_takes_extra_attempts(self):
        self.add_work(2, "docs/a.txt", "alpha", wrong_attempts=2)
        self.epic(2)
        summary = self.run_engine()
        self.assertEqual(summary["phases"], {"done": 1})
        self.assertEqual(self.store.issue(2).attempts, 2)
        feedback = [c[3] for c in self.agents.calls if c[0] == "implement"]
        self.assertEqual(feedback[0], ())
        self.assertTrue(any("A1 failed" in f for f in feedback[1]))

    def test_attempt_cap_ends_in_needs_human_and_blocks_dependents(self):
        self.add_work(2, "docs/a.txt", "alpha", wrong_attempts=99)
        self.add_work(3, "docs/b.txt", "beta", blocked_by=(2,))
        self.add_work(4, "docs/c.txt", "gamma")
        self.epic(2, 3, 4)
        summary = self.run_engine()
        self.assertEqual(self.phase(2), Phase.NEEDS_HUMAN)
        self.assertIn("verification failed 3 times", self.store.issue(2).reason)
        self.assertEqual(self.phase(3), Phase.PENDING)
        self.assertEqual(self.phase(4), Phase.DONE, "independent work carries on")
        self.assertEqual(summary["blocked_by_needs_human"], [3])
        self.assertIn({"name": "loop:needs-human"}, self.gh.issues[2]["labels"])
        self.assertEqual(self.gh.issues[2]["state"], "open")

    def test_editing_a_locked_check_is_caught(self):
        self.add_work(2, "docs/a.txt", "alpha", tamper=True)
        self.epic(2)
        summary = self.run_engine()
        self.assertEqual(summary["phases"], {"done": 1})
        verified = self.events("verified", 2)
        self.assertFalse(verified[0]["ok"])
        self.assertIn("locked file changed: checks/issue_2.sh", verified[0]["problems"])
        self.assertTrue(verified[-1]["ok"])

    def test_impossible_task_stops_immediately(self):
        self.add_work(2, "docs/a.txt", "alpha", impossible=True)
        self.epic(2)
        self.run_engine()
        self.assertEqual(self.phase(2), Phase.NEEDS_HUMAN)
        self.assertIn("cannot be done", self.store.issue(2).reason)
        self.assertEqual(len([c for c in self.agents.calls if c[0] == "implement"]), 1)

    def test_criterion_dispute_goes_to_a_human_before_any_code(self):
        self.add_work(2, "docs/a.txt", "alpha", criterion_dispute=True)
        self.epic(2)
        self.run_engine()
        self.assertEqual(self.phase(2), Phase.NEEDS_HUMAN)
        self.assertIn("would change an acceptance criterion", self.store.issue(2).reason)
        self.assertFalse(any(c[0] in ("write_checks", "implement") for c in self.agents.calls))

    def test_diverging_proposals_get_one_critique_round(self):
        self.add_work(2, "docs/a.txt", "alpha", disagree=True)
        self.epic(2)
        self.run_engine()
        self.assertEqual(len([c for c in self.agents.calls if c[0] == "critique"]), 1)
        self.assertEqual(self.store.issue(2).design_rounds, 2)
        self.assertEqual(self.phase(2), Phase.DONE)

    def test_verified_review_defect_triggers_a_fix_round(self):
        self.add_work(2, "docs/a.txt", "alpha", review_defects=1)
        self.epic(2)
        self.run_engine()
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertEqual(self.store.issue(2).fix_rounds, 1)
        fix_feedback = [c[3] for c in self.agents.calls if c[0] == "implement"][1]
        self.assertTrue(any("edge case breaks the criterion" in f for f in fix_feedback))

    def test_defects_beyond_the_fix_rounds_stop(self):
        self.add_work(2, "docs/a.txt", "alpha", review_defects=99)
        self.epic(2)
        self.run_engine()
        self.assertEqual(self.phase(2), Phase.NEEDS_HUMAN)
        self.assertEqual(self.store.issue(2).fix_rounds, 3)
        self.assertFalse(self.gh.prs, "nothing is opened for merge")

    def test_reviewer_outage_retries_once(self):
        self.add_work(2, "docs/a.txt", "alpha", reviewer_fails=1)
        self.add_work(3, "docs/b.txt", "beta", reviewer_fails=2)
        self.epic(2, 3)
        self.run_engine()
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertEqual(self.phase(3), Phase.NEEDS_HUMAN)
        self.assertIn("review missing", self.store.issue(3).reason)

    def test_red_required_check_blocks_the_merge(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        self.gh.default_check = "failure"
        self.run_engine()
        self.assertEqual(self.phase(2), Phase.NEEDS_HUMAN)
        self.assertIn("required check is 'failure'", self.store.issue(2).reason)
        self.assertIsNone(self.repo.main_file("docs/a.txt"))

    def test_manual_items_leave_the_issue_open_but_unblock_dependents(self):
        self.gh.add_issue(2, "Issue 2", issue_body("feat/issue-2", ["`docs/a.txt` contains `alpha`."],
                                                   ["The check passes.", "A person rehearses it."]), labels=("size:M",))
        self.scripts[2] = Script(files={"docs/a.txt": "alpha"}, manual_items=("A2",))
        self.add_work(3, "docs/b.txt", "beta", blocked_by=(2,))
        self.epic(2, 3)
        self.run_engine()
        self.assertEqual(self.phase(2), Phase.ACCEPTED)
        self.assertEqual(self.gh.issues[2]["state"], "open")
        self.assertIn("- [ ] A person rehearses it.", self.gh.issues[2]["body"])
        self.assertIn("- [x] The check passes.", self.gh.issues[2]["body"])
        self.assertEqual(self.phase(3), Phase.DONE)
        self.assertEqual(self.gh.issues[EPIC]["state"], "open", "the epic waits for the human evidence")
        summary = [c["body"] for c in self.gh.comments[EPIC] if "implement-loop:run" in c["body"]][0]
        self.assertIn("A2: A person rehearses it.", summary)


class ReviewFindingRegressions(EngineCase):
    """Regression tests for the cross-vendor review of PR #54."""

    def test_criteria_edited_before_landing_send_the_issue_back_to_design(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        agents = FakeAgents(self.scripts)
        original = agents.implement
        edited = []

        def implement_then_edit(*args, **kwargs):
            result = original(*args, **kwargs)
            if not edited:
                body = self.gh.issues[2]["body"]
                self.gh.issues[2]["body"] = body.replace("The check passes.", "The check passes on main.") + "- [ ] A second criterion.\n"
                edited.append(True)
            return result
        agents.implement = implement_then_edit
        self.run_engine(agents=agents)
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertTrue(self.events("requirements_changed", 2))
        body = self.gh.issues[2]["body"]
        self.assertIn("- [x] The check passes on main.", body)
        self.assertIn("- [x] A second criterion.", body)

    def test_criteria_edited_after_merge_are_never_ticked_with_old_evidence(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        merge = self.gh.on_merge

        def merge_then_edit(branch, sha):
            result = merge(branch, sha)
            self.gh.issues[2]["body"] = self.gh.issues[2]["body"].replace("The check passes.", "A different criterion.")
            return result
        self.gh.on_merge = merge_then_edit
        self.run_engine()
        self.assertEqual(self.phase(2), Phase.NEEDS_HUMAN)
        self.assertIn("changed after", self.store.issue(2).reason)
        self.assertEqual(self.gh.issues[2]["state"], "open")
        self.assertNotIn("- [x]", self.gh.issues[2]["body"])

    def test_criteria_edited_during_post_merge_verification_are_not_ticked(self):
        from unittest import mock
        from implement_loop import engine as engine_module
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        real_verify = engine_module.verify.verify

        def verify_then_edit(root, *args, **kwargs):
            result = real_verify(root, *args, **kwargs)
            if Path(root).name == "coord":
                self.gh.issues[2]["body"] = self.gh.issues[2]["body"].replace("The check passes.", "Something else entirely.")
            return result
        with mock.patch.object(engine_module.verify, "verify", verify_then_edit):
            self.run_engine()
        self.assertEqual(self.phase(2), Phase.NEEDS_HUMAN)
        self.assertNotIn("- [x]", self.gh.issues[2]["body"])
        self.assertEqual(self.gh.issues[2]["state"], "open")

    def test_a_commit_made_after_verification_is_verified_before_review(self):
        from unittest import mock
        from implement_loop.engine import Engine
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        original = Engine._step_verify
        store_dir = RunStore.for_root(self.repo.work, EPIC).dir

        def verify_then_stop(engine, n):
            original(engine, n)
            (store_dir / "STOP").write_text("stop\n")
        with mock.patch.object(Engine, "_step_verify", verify_then_stop):
            self.run_engine()
        self.assertEqual(self.phase(2), Phase.REVIEW)
        wt = Path(self.store.issue(2).worktree)
        (wt / "docs" / "a.txt").write_text("sabotage\n")
        from helpers import git
        git("commit", "-qam", "stray commit after verification", cwd=wt)
        (store_dir / "STOP").unlink()
        self.run_engine(agents=FakeAgents(self.scripts))
        self.assertTrue(self.events("head_changed_before_review", 2))
        self.assertEqual(self.repo.main_file("docs/a.txt"), "alpha", "only verified content may reach main")


class ResumeTests(EngineCase):
    def test_stop_then_resume_finishes_without_redoing_work(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        agents = FakeAgents(self.scripts)
        original = agents.implement

        def implement_then_stop(*args, **kwargs):
            result = original(*args, **kwargs)
            (self.store_dir() / "STOP").write_text("stop\n")
            return result
        agents.implement = implement_then_stop
        summary = self.run_engine(agents=agents)
        self.assertTrue(summary["stopped"])
        stopped_at = self.phase(2)
        self.assertIn(stopped_at, (Phase.VERIFY,))
        (self.store_dir() / "STOP").unlink()

        again = FakeAgents(self.scripts)
        summary = self.run_engine(agents=again)
        self.assertEqual(summary["phases"], {"done": 1})
        self.assertFalse(any(c[0] in ("propose", "write_checks", "implement") for c in again.calls),
                         "a resumed run continues from the saved phase")

    def test_changed_requirements_invalidate_the_design(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        agents = FakeAgents(self.scripts)
        original = agents.judge

        def judge_then_stop(*args, **kwargs):
            (self.store_dir() / "STOP").write_text("stop\n")
            return original(*args, **kwargs)
        agents.judge = judge_then_stop
        self.run_engine(agents=agents)
        self.assertEqual(self.phase(2), Phase.DESIGNED)
        (self.store_dir() / "STOP").unlink()

        self.gh.issues[2]["body"] = self.gh.issues[2]["body"].replace("The check passes.", "The check passes twice.")
        again = FakeAgents(self.scripts)
        self.run_engine(agents=again)
        self.assertEqual([e["kind"] for e in self.events("requirements_changed")], ["requirements_changed"])
        self.assertTrue(any(c[0] == "propose" for c in again.calls), "the design is redone")
        self.assertEqual(self.phase(2), Phase.DONE)

    def test_a_merge_the_engine_never_recorded_is_picked_up_on_resume(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        real_merge = self.gh.merge_pr

        def merge_then_die(n, sha, method="squash"):
            real_merge(n, sha, method)
            raise RuntimeError("process died right after the merge")
        self.gh.merge_pr = merge_then_die
        self.run_engine()
        st = self.store.issue(2)
        st.phase, st.reason = Phase.LAND, None   # as if the process died before handling the crash
        self.store.put(st)
        self.gh.merge_pr = real_merge
        self.run_engine(agents=FakeAgents(self.scripts))
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertEqual(len(self.events("merge_found_on_resume")), 1)
        self.assertEqual(len([c for c in self.gh.calls if c[0] == "merge_pr"]), 1, "never merged twice")

    def store_dir(self) -> Path:
        return RunStore.for_root(self.repo.work, EPIC).dir


if __name__ == "__main__":
    unittest.main()
