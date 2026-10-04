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
                        log=lambda m: None, sleep=lambda s: None, environment=getattr(self, "environment", None))
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

    def test_attempt_cap_redesigns_once_then_parks_with_its_dependents(self):
        self.add_work(2, "docs/a.txt", "alpha", wrong_attempts=99)
        self.add_work(3, "docs/b.txt", "beta", blocked_by=(2,))
        self.add_work(4, "docs/c.txt", "gamma")
        self.epic(2, 3, 4)
        summary = self.run_engine()
        st = self.store.issue(2)
        self.assertEqual((st.phase, st.park_kind, st.redesigns), (Phase.PARKED, "exhausted", 1))
        self.assertIn("verification failed 3 times", st.reason)
        self.assertEqual(len(self.events("redesign", 2)), 1, "one redesign before parking")
        self.assertEqual(len([c for c in self.agents.calls if c[0] == "implement" and c[2] == 2]), 6, "3 attempts per design")
        self.assertEqual((self.phase(3), self.store.issue(3).park_kind), (Phase.PARKED, "blocked"))
        self.assertIn("#2", self.store.issue(3).reason)
        self.assertEqual(self.phase(4), Phase.DONE, "independent work carries on")
        self.assertEqual(set(summary["parked"]), {2, 3})
        self.assertIn({"name": "loop:parked"}, self.gh.issues[2]["labels"])
        self.assertEqual(self.gh.issues[2]["state"], "open")

    def test_editing_a_locked_check_is_caught(self):
        self.add_work(2, "docs/a.txt", "alpha", tamper=True)
        self.epic(2)
        summary = self.run_engine()
        self.assertEqual(summary["phases"], {"done": 1})
        self.assertEqual(self.events("locked_changes_reverted", 2)[0]["files"], ["checks/issue_2.sh"])
        self.assertNotIn("exit 0", self.repo.main_file("checks/issue_2.sh"), "the edit never reaches a commit")
        from helpers import git
        touched = git("log", "--format=%s", "origin/main", "--", "checks/issue_2.sh", cwd=self.repo.work)
        self.assertEqual(len(touched.splitlines()), 1, "only the squash merge touches the locked check")

    def test_an_impossible_design_is_redone_once_with_the_implementers_note(self):
        self.add_work(2, "docs/a.txt", "alpha", impossible_once=True)
        self.epic(2)
        self.run_engine()
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertEqual(self.store.issue(2).redesigns, 1)
        redesign_feedback = [c for c in self.agents.calls if c[0] == "implement"][1][3]
        self.assertTrue(any("redesign 1" in f for f in redesign_feedback))
        self.assertTrue(any("criteria contradict" in f for f in redesign_feedback))

    def test_an_always_impossible_task_parks_after_one_redesign(self):
        self.add_work(2, "docs/a.txt", "alpha", impossible=True)
        self.epic(2)
        self.run_engine()
        st = self.store.issue(2)
        self.assertEqual((st.phase, st.park_kind), (Phase.PARKED, "exhausted"))
        self.assertIn("impossible", st.reason)
        self.assertEqual(len([c for c in self.agents.calls if c[0] == "implement"]), 2)

    def test_an_ambiguous_criterion_is_decided_by_the_judge_not_a_person(self):
        self.add_work(2, "docs/a.txt", "alpha", criterion_dispute=True)
        self.epic(2)
        self.run_engine()
        self.assertEqual(self.phase(2), Phase.DONE)
        log = self.store.issue(2).design["decision_log"]
        self.assertTrue(any("ambiguous" in d["choice"] for d in log))
        pr = self.gh.prs[self.store.issue(2).pr]
        self.assertIn("## Decisions", pr["body"])
        self.assertIn("the criterion itself is ambiguous", pr["body"])

    def test_diverging_proposals_get_one_critique_round(self):
        self.add_work(2, "docs/a.txt", "alpha", disagree=True)
        self.epic(2)
        self.run_engine()
        self.assertEqual(len([c for c in self.agents.calls if c[0] == "critique"]), 1)
        self.assertEqual(self.store.issue(2).design_rounds, 1)
        self.assertEqual(self.phase(2), Phase.DONE)

    def test_verified_review_defect_triggers_a_fix_round(self):
        self.add_work(2, "docs/a.txt", "alpha", review_defects=1)
        self.epic(2)
        self.run_engine()
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertEqual(self.store.issue(2).fix_rounds, 1)
        fix_feedback = [c[3] for c in self.agents.calls if c[0] == "implement"][1]
        self.assertTrue(any("edge case breaks the criterion" in f for f in fix_feedback))

    def test_defects_beyond_the_fix_rounds_redesign_then_park(self):
        self.add_work(2, "docs/a.txt", "alpha", review_defects=99)
        self.epic(2)
        self.run_engine()
        st = self.store.issue(2)
        self.assertEqual((st.phase, st.park_kind, st.redesigns), (Phase.PARKED, "exhausted", 1))
        self.assertIn("reproduced defects remain", st.reason)
        self.assertFalse(self.gh.prs, "nothing is opened for merge")

    def test_reviewer_outage_retries_once_then_parks_until_the_next_run(self):
        self.add_work(2, "docs/a.txt", "alpha", reviewer_fails=1)
        self.add_work(3, "docs/b.txt", "beta", reviewer_fails=2)
        self.epic(2, 3)
        self.run_engine()
        self.assertEqual(self.phase(2), Phase.DONE)
        st = self.store.issue(3)
        self.assertEqual((st.phase, st.park_kind, st.resume_phase), (Phase.PARKED, "transient", "review"))
        self.assertIn("review missing", st.reason)
        self.run_engine(agents=self.agents)   # the outage is over: the same fake now answers
        self.assertEqual(self.phase(3), Phase.DONE)
        self.assertEqual(self.events("resumed", 3)[0]["phase"], "review")

    def test_a_flaky_required_check_is_rerun_once(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        self.gh.check_script = ["failure", "success"]
        self.run_engine()
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertEqual(len(self.gh.reruns), 1)
        self.assertEqual(len([c for c in self.agents.calls if c[0] == "implement"]), 1, "no implementation round")

    def test_a_red_required_check_goes_back_to_the_implementer_with_the_log(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        self.gh.check_script = ["failure", "failure"]   # red, red again after the re-run, then green
        agents = FakeAgents(self.scripts)
        original = agents.implement

        def fix_round(*args, **kwargs):
            # this fake's fix commits nothing new, so let CI evaluate the same head afresh
            if any("required CI check" in f for f in args[4]):
                self.gh._check_seen.clear()
            return original(*args, **kwargs)
        agents.implement = fix_round
        self.run_engine(agents=agents)
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertEqual(self.store.issue(2).ci_fixes, 1)
        feedback = [c[3] for c in self.agents.calls if c[0] == "implement"][1]
        self.assertTrue(any("fake CI failure" in f for f in feedback))

    def test_a_check_that_stays_red_parks_without_merging(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        self.gh.default_check = "failure"
        self.run_engine()
        st = self.store.issue(2)
        self.assertEqual((st.phase, st.park_kind), (Phase.PARKED, "exhausted"))
        self.assertIn("required CI check is 'failure'", st.reason)
        self.assertIsNone(self.repo.main_file("docs/a.txt"))

    def test_a_check_with_no_verdict_parks_as_an_outage(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        self.gh.default_check = "cancelled"
        self.run_engine()
        st = self.store.issue(2)
        self.assertEqual((st.phase, st.park_kind, st.resume_phase), (Phase.PARKED, "transient", "land"))
        self.gh.default_check = "success"
        self.run_engine(agents=self.agents)
        self.assertEqual(self.phase(2), Phase.DONE)

    def test_manual_items_leave_the_issue_open_but_unblock_dependents(self):
        self.gh.add_issue(2, "Issue 2", issue_body("feat/issue-2", ["`docs/a.txt` contains `alpha`."],
                                                   ["The check passes.", "A person rehearses it."]), labels=("size:M",))
        self.scripts[2] = Script(files={"docs/a.txt": "alpha"}, manual_items=("A2",))
        self.add_work(3, "docs/b.txt", "beta", blocked_by=(2,))
        self.epic(2, 3)
        self.run_engine()
        self.assertEqual(self.phase(2), Phase.DELIVERED)
        self.assertEqual(self.gh.issues[2]["state"], "open")
        self.assertIn("- [ ] A person rehearses it.", self.gh.issues[2]["body"])
        self.assertIn("- [x] The check passes.", self.gh.issues[2]["body"])
        self.assertEqual(self.phase(3), Phase.DONE)
        self.assertEqual(self.gh.issues[EPIC]["state"], "open", "the epic waits for the human evidence")
        summary = [c["body"] for c in self.gh.comments[EPIC] if "implement-loop:run" in c["body"]][0]
        self.assertIn("Owner checklist", summary)
        self.assertIn("A2: A person rehearses it.", summary)
        # the owner ticks the box; the next run closes the issue and the epic
        self.gh.issues[2]["body"] = self.gh.issues[2]["body"].replace("- [ ] A person rehearses it.", "- [x] A person rehearses it.")
        self.run_engine(agents=FakeAgents(self.scripts))
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertEqual(self.gh.issues[2]["state"], "closed")
        self.assertEqual(self.gh.issues[EPIC]["state"], "closed")


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
        st = self.store.issue(2)
        self.assertEqual(st.round, 2, "the edited issue is delivered again in a new round")
        self.assertEqual(st.branch, "feat/issue-2-r2")
        self.assertTrue(self.events("new_round", 2))
        self.assertEqual(st.phase, Phase.DONE)
        self.assertIn("- [x] A different criterion.", self.gh.issues[2]["body"])
        self.assertEqual(len([c for c in self.gh.calls if c[0] == "merge_pr"]), 1,
                         "the second round changed nothing, so there was nothing to merge")
        self.assertTrue(self.events("nothing_to_land", 2))

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
        self.assertEqual(self.store.issue(2).round, 2)
        self.assertTrue(self.events("new_round", 2))
        self.assertNotIn("- [x] The check passes.", self.gh.issues[2]["body"], "never ticked with old evidence")

    def test_a_finding_that_cannot_be_verified_is_published_never_dropped(self):
        self.add_work(2, "docs/a.txt", "alpha", review_defects=1, unverifiable=True)
        self.epic(2)
        self.run_engine()
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertEqual(self.events("reviewed", 2)[0]["unresolved"], ["F2-0"])
        pr = self.gh.prs[self.store.issue(2).pr]
        self.assertIn("edge case breaks the criterion", pr["body"])
        self.assertIn("could not be reproduced either way", pr["body"])

    def test_tags_an_agent_creates_are_deleted(self):
        self.add_work(2, "docs/a.txt", "alpha", tags=True)
        self.epic(2)
        self.run_engine()
        self.assertEqual(self.phase(2), Phase.DONE)
        from helpers import git
        self.assertEqual(git("tag", "--list", "agent-probe-*", cwd=self.repo.work), "")
        self.assertEqual(self.events("agent_refs_deleted", 2)[0]["refs"], ["refs/tags/agent-probe-2"])

    def test_commits_an_agent_makes_are_absorbed_into_engine_commits(self):
        self.add_work(2, "docs/a.txt", "alpha", commits=True)
        self.epic(2)
        self.run_engine()
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertEqual(len(self.events("agent_commits_absorbed", 2)), 1)
        from helpers import git
        log = git("log", "--format=%s", "origin/feat/issue-2", cwd=self.repo.work)
        self.assertNotIn("agent commit", log)
        self.assertIn("Implement #2", log)

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


class RecordedRunRegressions(EngineCase):
    """The failures of the first live runs (2026-10-04, epic #11 and #21), replayed (ADR 0011)."""

    def test_a_reproduced_check_defect_is_amended_and_relocked(self):
        # #21: a locked chart test waited for "no SVG in any chart"; it cost a full redesign
        self.add_work(2, "docs/a.txt", "alpha", defective_check=True)
        self.epic(2)
        self.run_engine()
        self.assertEqual(self.phase(2), Phase.DONE)
        st = self.store.issue(2)
        self.assertEqual((st.check_amendments, st.redesigns), (1, 0), "amended, not redesigned")
        claimed = self.events("check_defect_claimed", 2)[0]
        self.assertTrue(claimed["reproduced"])
        self.assertIn(("verify_finding", "codex", 2, "C2-1"), self.agents.calls, "the other vendor reproduces it")
        amend = [c for c in self.agents.calls if c[0] == "write_checks"][1]
        self.assertEqual(amend[1], "codex", "the check's author amends it")
        self.assertTrue(any("expects a value the issue never asks for" in f for f in amend[3]))
        self.assertTrue(self.events("checks_locked", 2)[1]["amended"])
        self.assertEqual(self.repo.main_file("checks/issue_2.sh").splitlines()[-1], 'test "$(cat docs/a.txt)" = "alpha"')
        from helpers import git
        log = git("log", "--format=%s", "origin/feat/issue-2", cwd=self.repo.work)
        self.assertIn("Amend acceptance checks for #2", log)
        self.assertIn("Checkpoint #2", log, "the implementer's work was kept, not discarded")

    def test_a_check_defect_nobody_can_reproduce_is_feedback_not_an_amendment(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        agents = FakeAgents(self.scripts)
        original = agents.implement
        from implement_loop.agents import ImplementResult
        calls = []

        def claim_once(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                return ImplementResult("check_defect", "I think the check is wrong", defect_file="checks/issue_2.sh",
                                       defect_reproduction="bash checks/issue_2.sh")
            return original(*args, **kwargs)
        agents.implement = claim_once
        self.run_engine(agents=agents)
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertEqual(self.store.issue(2).check_amendments, 0)
        self.assertFalse(self.events("check_defect_claimed", 2)[0]["reproduced"])
        self.assertEqual(len([c for c in agents.calls if c[0] == "write_checks"]), 1)

    def test_a_redesign_retires_the_checks_it_no_longer_uses(self):
        # #21: a restarted issue kept the previous round's locked checks (issue #60)
        self.add_work(2, "docs/a.txt", "alpha", impossible_once=True)
        self.epic(2)
        agents = FakeAgents(self.scripts)
        original = agents.implement

        def switch_check_file(*args, **kwargs):
            result = original(*args, **kwargs)
            self.scripts[2].check_file = "checks/new_2.sh"   # the redesign picks another check file
            return result
        agents.implement = switch_check_file
        self.run_engine(agents=agents)
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertEqual(self.events("checks_locked", 2)[1]["retired"], ["checks/issue_2.sh"])
        self.assertIsNone(self.repo.main_file("checks/issue_2.sh"), "the stale suite never reaches main")
        self.assertIsNotNone(self.repo.main_file("checks/new_2.sh"))
        from helpers import git, REPO_ROOT
        import subprocess
        bodies = git("log", "--format=%B", "origin/feat/issue-2", cwd=self.repo.work)
        self.assertIn("Loop-Unlocks: checks/issue_2.sh", bodies)
        guard = subprocess.run(["bash", str(REPO_ROOT / "scripts" / "check-loop-guard.sh"), "origin/main~1", "origin/feat/issue-2"],
                               cwd=self.repo.work, capture_output=True, text=True)
        self.assertEqual(guard.returncode, 0, guard.stdout + guard.stderr)

    def test_an_environment_failure_parks_without_burning_attempts_and_resumes_when_fixed(self):
        # #21: Chromium's shared libraries were missing; two implement attempts were wasted on it
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        agents = FakeAgents(self.scripts)
        original = agents.write_checks

        def check_needing_the_host(vendor, req, design, worktree, feedback=None):
            original(vendor, req, design, worktree, feedback)
            target = worktree / "checks" / "issue_2.sh"
            target.write_text(target.read_text().replace(
                "set -euo pipefail\n",
                'set -euo pipefail\n[ "${HOST_LIBS_OK:-}" = 1 ] || { echo "chrome: error while loading shared libraries: libnspr4.so"; exit 127; }\n'))
        agents.write_checks = check_needing_the_host
        self.run_engine(agents=agents)
        st = self.store.issue(2)
        self.assertEqual((st.phase, st.park_kind, st.resume_phase, st.attempts), (Phase.PARKED, "environment", "verify", 0))
        self.assertIn("libnspr4.so", st.reason)
        self.assertEqual(len([c for c in agents.calls if c[0] == "implement"]), 1)

        self.environment = {"fingerprint": "healed", "check_env": {"HOST_LIBS_OK": "1"}}
        self.run_engine(agents=agents)
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertEqual(len([c for c in agents.calls if c[0] == "implement"]), 1, "the same commit is verified again")

    def test_an_engine_fault_is_filed_once_and_parks_only_its_issue(self):
        from unittest import mock
        from implement_loop.engine import Engine
        self.add_work(2, "docs/a.txt", "alpha")
        self.add_work(3, "docs/b.txt", "beta")
        self.add_work(4, "docs/c.txt", "gamma", size="S")
        self.epic(2, 3, 4)
        original = Engine._step_review

        def crash_for_m(engine, n):
            if engine.plan.issues[n].size == "M":
                raise KeyError("a bug in the engine at " + str(self.repo.work))
            return original(engine, n)
        with mock.patch.object(Engine, "_step_review", crash_for_m):
            summary = self.run_engine()
        self.assertEqual({n: self.store.issue(n).park_kind for n in summary["parked"]}, {2: "engine_error", 3: "engine_error"})
        self.assertEqual(self.phase(4), Phase.DONE, "the run carries on")
        filed = [c for c in self.gh.calls if c[0] == "create_issue"]
        self.assertEqual(len(filed), 1, "one issue per distinct fault")
        body = self.gh.issues[filed[0][1]]["body"]
        self.assertIn("implement-loop:fault:", body)
        self.assertNotIn(str(self.repo.work), body, "local paths are redacted")
        self.assertIn({"name": "loop:engine-bug"}, self.gh.issues[filed[0][1]]["labels"])

        # the same fault on a later run is a comment on the same issue, not a new issue
        with mock.patch.object(Engine, "_step_review", crash_for_m):
            self.store.issue(2)
            st = self.store.issue(2)
            st.retry = True
            self.store.put(st)
            self.run_engine()
        self.assertEqual(len([c for c in self.gh.calls if c[0] == "create_issue"]), 1)
        self.assertTrue(any("Seen again" in c["body"] for c in self.gh.comments.get(filed[0][1], [])))

    def test_an_unavailable_agent_parks_as_an_outage_not_an_engine_bug(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        agents = FakeAgents(self.scripts)

        class AgentFailure(RuntimeError):
            pass

        def unavailable(*args, **kwargs):
            raise AgentFailure("codex write_checks failed after 3 attempts")
        agents.write_checks = unavailable
        self.run_engine(agents=agents)
        st = self.store.issue(2)
        self.assertEqual((st.phase, st.park_kind, st.resume_phase), (Phase.PARKED, "transient", "checks"))
        self.assertFalse([c for c in self.gh.calls if c[0] == "create_issue"])
        self.run_engine(agents=FakeAgents(self.scripts))
        self.assertEqual(self.phase(2), Phase.DONE)

    def test_a_merge_that_breaks_an_earlier_issue_opens_a_fix_forward_round(self):
        # epic #11: #23 broke #20's standalone-session evidence and nobody saw it
        self.add_work(2, "docs/a.txt", "alpha")
        self.add_work(3, "docs/a.txt", "broken", blocked_by=(2,))
        self.epic(2, 3)
        self.run_engine()
        self.assertEqual(self.phase(2), Phase.DONE)
        st = self.store.issue(3)
        regressions = [e for e in self.events("regression_check") if e["issue"] == 3]
        self.assertTrue(regressions and not regressions[0]["ok"])
        self.assertEqual(len(self.events("new_round", 3)), 1, "one fix-forward round")
        self.assertEqual((st.phase, st.park_kind), (Phase.PARKED, "exhausted"))
        self.assertIn("#2's checks fail on main", st.reason)

    def test_a_pr_merged_by_someone_else_at_another_head_is_accepted_on_main(self):
        # #21: the owner merged PR #61 by hand after a CI-only change; the engine could not resume
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        self.run_engine()
        st = self.store.issue(2)
        pr = self.gh.prs[st.pr]
        pr["head"]["sha"] = "f2e878c" + "0" * 33   # updated with main before the owner merged it
        self.gh.issues[2]["state"] = "open"          # as if the engine had stopped before accepting it
        st.phase, st.reason = Phase.LAND, None
        self.store.put(st)
        self.run_engine(agents=FakeAgents(self.scripts))
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertEqual(self.events("merged_externally", 2)[0]["head"], pr["head"]["sha"])

    def test_retry_gives_an_exhausted_issue_a_fresh_set_of_recovery_steps(self):
        self.add_work(2, "docs/a.txt", "alpha", impossible=True)
        self.epic(2)
        self.run_engine()
        self.assertEqual(self.store.issue(2).park_kind, "exhausted")
        self.run_engine(agents=FakeAgents(self.scripts))
        self.assertEqual(self.phase(2), Phase.PARKED, "an unchanged failure is not retried without new evidence")
        self.scripts[2].impossible = False
        st = self.store.issue(2)
        st.retry = True
        self.store.put(st)
        self.run_engine(agents=FakeAgents(self.scripts))
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertTrue(self.events("resumed", 2)[0]["retry"])

    def test_explorers_read_the_issues_themselves(self):
        # #21: an explorer wrote "I could not read issue #21's text or its 8 ledger items"
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        self.run_engine()
        briefing = [c for c in self.agents.calls if c[0] == "explore"][0][3]
        self.assertIn("`docs/a.txt` contains `alpha`.", briefing)


class CrossVendorReviewRegressions(EngineCase):
    """Regression tests for Codex's review of the autonomous engine (PR 1)."""

    def test_an_older_merged_pr_of_a_reused_branch_is_not_mistaken_for_this_delivery(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        from helpers import git
        old_head = git("rev-parse", "origin/main", cwd=self.repo.work)   # contains nothing of this delivery
        self.gh.prs[4999] = {"number": 4999, "head": {"ref": "feat/issue-2", "sha": old_head}, "base": {"ref": "main"},
                             "title": "old", "body": "", "state": "closed", "merged": True, "labels": []}
        self.run_engine()
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertEqual(self.events("stale_pr_ignored", 2)[0]["pr"], 4999)
        self.assertEqual(self.repo.main_file("docs/a.txt"), "alpha", "the real work was merged")
        self.assertNotEqual(self.store.issue(2).pr, 4999)

    def test_reviewer_judgements_do_not_survive_unreviewed_changes_in_an_external_merge(self):
        self.gh.add_issue(2, "Issue 2", issue_body("feat/issue-2", ["`docs/a.txt` contains `alpha`."], ["It reads well."]),
                          labels=("size:M",))
        self.scripts[2] = Script(files={"docs/a.txt": "alpha"}, artifact_items=("A1",))
        self.epic(2)
        from unittest import mock
        from implement_loop.engine import Engine
        original = Engine._step_land

        def someone_else_merges(engine, n):
            # the owner pushes a change to a reviewed path and merges the PR by hand, once
            st = engine.store.issue(n)
            if st.round > 1:
                return original(engine, n)
            wt = Path(st.worktree)
            engine.ws.push(wt)
            (wt / "docs" / "a.txt").write_text("alpha, edited after review\n")
            from helpers import git
            git("commit", "-qam", "owner edit", cwd=wt)
            git("push", "-q", "origin", "HEAD", cwd=wt)
            head = git("rev-parse", "HEAD", cwd=wt)
            pr = engine.gh.create_pr(st.branch, "main", "t", "b")
            engine.gh.merge_pr(pr["number"], head)
            return original(engine, n)
        with mock.patch.object(Engine, "_step_land", someone_else_merges):
            self.run_engine()
        merged = self.events("merged_externally", 2)[0]
        self.assertEqual(merged["unreviewed"], ["docs/a.txt"])
        self.assertTrue(self.events("new_round", 2), "the unreviewed artifact item is delivered again")
        self.assertEqual(self.phase(2), Phase.DONE)

    def test_an_edit_inside_a_merge_commit_also_invalidates_reviewer_judgements(self):
        self.gh.add_issue(2, "Issue 2", issue_body("feat/issue-2", ["`docs/a.txt` contains `alpha`."], ["It reads well."]),
                          labels=("size:M",))
        self.scripts[2] = Script(files={"docs/a.txt": "alpha"}, artifact_items=("A1",))
        self.epic(2)
        from unittest import mock
        from implement_loop.engine import Engine
        from helpers import git
        original = Engine._step_land

        def merge_main_with_an_edit(engine, n):
            st = engine.store.issue(n)
            if st.round > 1:
                return original(engine, n)
            wt = Path(st.worktree)
            engine.ws.push(wt)
            (self.repo.merger / "docs").mkdir(exist_ok=True)
            (self.repo.merger / "docs" / "other.txt").write_text("unrelated\n")
            git("fetch", "-q", "origin", cwd=self.repo.merger)
            git("checkout", "-q", "-B", "main", "origin/main", cwd=self.repo.merger)
            git("add", "-A", cwd=self.repo.merger)
            git("commit", "-qm", "unrelated change on main", cwd=self.repo.merger)
            git("push", "-q", "origin", "HEAD:main", cwd=self.repo.merger)
            git("fetch", "-q", "origin", cwd=wt)
            git("merge", "-q", "--no-ff", "--no-commit", "origin/main", cwd=wt)
            (wt / "docs" / "a.txt").write_text("alpha, changed while merging main\n")
            git("commit", "-qam", "Merge main", cwd=wt)
            git("push", "-q", "origin", "HEAD", cwd=wt)
            pr = engine.gh.create_pr(st.branch, "main", "t", "b")
            engine.gh.merge_pr(pr["number"], git("rev-parse", "HEAD", cwd=wt))
            return original(engine, n)
        with mock.patch.object(Engine, "_step_land", merge_main_with_an_edit):
            self.run_engine()
        self.assertEqual(self.events("merged_externally", 2)[0]["unreviewed"], ["docs/a.txt"])

    def test_an_interrupted_amendment_never_lands_a_check_edit_in_an_implementation_commit(self):
        self.add_work(2, "docs/a.txt", "alpha", defective_check=True)
        self.epic(2)
        agents = FakeAgents(self.scripts)
        original = agents.write_checks
        store_dir = RunStore.for_root(self.repo.work, EPIC).dir
        interrupted = []

        def half_written(vendor, req, design, worktree, feedback=None):
            if feedback and not interrupted:
                interrupted.append(True)
                (worktree / "checks" / "issue_2.sh").write_text("#!/usr/bin/env bash\n# half-written amendment\n")
                (store_dir / "STOP").write_text("stop\n")
                raise type("AgentStopped", (RuntimeError,), {})("stopped mid-amendment")
            return original(vendor, req, design, worktree, feedback)
        agents.write_checks = half_written
        self.run_engine(agents=agents)
        self.assertEqual(self.phase(2), Phase.CHECKS)
        self.run_engine(agents=agents)   # the stop belonged to the earlier invocation
        self.assertEqual(self.phase(2), Phase.DONE)
        for e in self.events("checkpoint_before_checks", 2):
            self.assertNotIn("checks/issue_2.sh", e["files"])
        from helpers import REPO_ROOT
        import subprocess
        guard = subprocess.run(["bash", str(REPO_ROOT / "scripts" / "check-loop-guard.sh"), "origin/main~1", "origin/feat/issue-2"],
                               cwd=self.repo.work, capture_output=True, text=True)
        self.assertEqual(guard.returncode, 0, guard.stdout + guard.stderr)

    def test_a_merge_github_keeps_refusing_parks_instead_of_looping(self):
        from implement_loop.github import GitHubError
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)

        def refuse(n, sha, method="squash"):
            raise GitHubError("Pull Request is not mergeable")
        self.gh.merge_pr = refuse
        self.run_engine()
        st = self.store.issue(2)
        self.assertEqual((st.phase, st.park_kind, st.merge_refusals), (Phase.PARKED, "transient", 3))
        self.assertEqual(len(self.events("merge_refused", 2)), 3)

    def test_a_leftover_stop_request_does_not_stop_the_next_run(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        store_dir = RunStore.for_root(self.repo.work, EPIC).dir
        (store_dir / "STOP").write_text("stop requested\n")
        summary = self.run_engine()
        self.assertFalse(summary["stopped"])
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertTrue(self.events("stale_stop_cleared"))

    def test_earlier_issues_are_regression_checked_after_a_restart(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.add_work(3, "docs/a.txt", "broken", blocked_by=(2,))
        self.epic(2, 3)
        from unittest import mock
        from implement_loop.engine import Engine
        original = Engine._step_design

        def stop_before_3(engine, n):
            if n == 3:
                (engine.store.dir / "STOP").write_text("stop\n")
                raise type("AgentStopped", (RuntimeError,), {})("stopped")
            return original(engine, n)
        with mock.patch.object(Engine, "_step_design", stop_before_3):
            self.run_engine()
        self.assertEqual(self.gh.issues[2]["state"], "closed", "#2 is done and leaves the next plan's work")
        self.run_engine(agents=FakeAgents(self.scripts))
        checked = [e for e in self.events("regression_check") if e["issue"] == 3]
        self.assertTrue(checked and checked[0]["of"] == 2 and not checked[0]["ok"])

    def test_published_fault_reports_carry_no_exception_message(self):
        from unittest import mock
        from implement_loop.engine import Engine
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)

        def leak(engine, n):
            raise RuntimeError("Authorization: Bearer ghp_secret123 at https://user:pw@example.test")
        with mock.patch.object(Engine, "_step_review", leak):
            self.run_engine()
        filed = [c for c in self.gh.calls if c[0] == "create_issue"][0][1]
        public = self.gh.issues[filed]["body"] + "".join(c["body"] for c in self.gh.comments.get(2, []))
        self.assertNotIn("ghp_secret123", public)
        self.assertNotIn("user:pw", public)
        self.assertIn("RuntimeError", public)
        self.assertIn("ghp_secret123", [e for e in self.store.events() if e["kind"] == "step_crashed"][0]["error"],
                      "the local journal keeps the detail")

    def test_a_fault_issue_created_before_a_lost_response_is_not_filed_twice(self):
        from unittest import mock
        from implement_loop.engine import Engine
        from implement_loop.github import GitHubError
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        real_create = self.gh.create_issue

        def create_then_lose_the_response(title, body, labels):
            real_create(title, body, labels)
            raise GitHubError("connection reset")
        self.gh.create_issue = create_then_lose_the_response

        def crash(engine, n):
            raise KeyError("x")
        with mock.patch.object(Engine, "_step_review", crash):
            self.run_engine()
        self.gh.create_issue = real_create
        self.run_engine(agents=FakeAgents(self.scripts))
        faults = [n for n, i in self.gh.issues.items() if "implement-loop:fault:" in (i.get("body") or "")]
        self.assertEqual(len(faults), 1)

    def test_writing_checks_keeps_work_an_interrupted_implementer_left(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        agents = FakeAgents(self.scripts)
        original = agents.write_checks
        seen = []

        def leftover_then_write(vendor, req, design, worktree, feedback=None):
            if not seen:
                seen.append(True)
                (worktree / "docs").mkdir(exist_ok=True)
                (worktree / "docs" / "a.txt").write_text("alpha\n")   # as if an implementer had stopped mid-way
            return original(vendor, req, design, worktree, feedback)
        from unittest import mock
        from implement_loop.engine import Engine
        real_checks = Engine._step_checks

        def with_leftover(engine, n):
            st = engine.store.issue(n)
            wt = engine.ws.issue_worktree(n, st.branch)
            (wt / "docs").mkdir(exist_ok=True)
            (wt / "docs" / "a.txt").write_text("alpha\n")
            return real_checks(engine, n)
        with mock.patch.object(Engine, "_step_checks", with_leftover):
            self.run_engine(agents=agents)
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertTrue(self.events("checkpoint_before_checks", 2))
        self.assertFalse(self.events("check_author_out_of_lane", 2), "the leftover work is not discarded")

    def test_an_amendment_may_rewrite_only_the_defective_check(self):
        self.add_work(2, "docs/a.txt", "alpha", defective_check=True)
        self.epic(2)
        agents = FakeAgents(self.scripts)
        original = agents.write_checks

        def also_touch_another_file(vendor, req, design, worktree, feedback=None):
            original(vendor, req, design, worktree, feedback)
            if feedback:
                self.assertEqual(design.check_files, ["checks/issue_2.sh"])
                (worktree / "checks" / "unrelated.sh").write_text("exit 0\n")
        agents.write_checks = also_touch_another_file
        self.run_engine(agents=agents)
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertIn("checks/unrelated.sh", self.events("check_author_out_of_lane", 2)[0]["discarded"])

    def test_a_defect_report_must_name_a_locked_check(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        agents = FakeAgents(self.scripts)
        original = agents.implement
        from implement_loop.agents import ImplementResult
        calls = []

        def wrong_file(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                return ImplementResult("check_defect", "this is wrong", defect_file="docs/a.txt", defect_reproduction="cat")
            return original(*args, **kwargs)
        agents.implement = wrong_file
        self.run_engine(agents=agents)
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertFalse(self.events("check_defect_claimed", 2), "nothing to reproduce: not a locked check")
        feedback = [c for c in agents.calls if c[0] == "implement"][0][3]   # the wrapper hid the first call
        self.assertTrue(any("is not one of the locked checks" in f for f in feedback))


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
