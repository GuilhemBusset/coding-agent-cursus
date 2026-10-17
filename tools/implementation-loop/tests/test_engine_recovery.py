"""Recovery, resumption and git-mechanics regressions of the engine, ported from the end-to-end
suite of the earlier engines (ADR 0008, ADR 0011) to the builder/examiner workflow (ADR 0012).
Real git, the real ship.sh, the real verifier and real squash merges into a local bare remote;
only the agents and GitHub are fakes."""

import signal
import stat
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from helpers import REPO_ROOT, SHIP, git, issue_body
from test_agent_git_isolation import IsolationCase, git_dir
from test_engine import EPIC, EngineCase

from implement_loop import engine as engine_mod
from implement_loop.agents import AgentFailure, Decision, FakeAgents, Request, Script
from implement_loop.config import Caps
from implement_loop.engine import Engine
from implement_loop.github import GitHubError
from implement_loop.model import Phase
from implement_loop.state import RunStore
from implement_loop.workspace import GitError, Workspace


class RecoveryCase(EngineCase):
    def store_dir(self) -> Path:
        return RunStore.for_root(self.repo.work, EPIC).dir

    def builds(self, n=2):
        return [c for c in self.agents.calls if c[0] == "build" and c[2] == n]

    def guard(self, branch="feat/issue-2"):
        """The CI loop guard over the merged branch: no implementation commit changed a locked test."""
        return subprocess.run(["bash", str(REPO_ROOT / "scripts" / "check-loop-guard.sh"), "origin/main~1",
                               f"origin/{branch}"], cwd=self.repo.work, capture_output=True, text=True)

    def move_main(self, files):
        git("fetch", "-q", "origin", cwd=self.repo.merger)
        git("checkout", "-q", "-B", "main", "origin/main", cwd=self.repo.merger)
        for rel, content in files.items():
            (self.repo.merger / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.repo.merger / rel).write_text(content)
        git("add", "-A", cwd=self.repo.merger)
        git("commit", "-qm", "fixture: move main", cwd=self.repo.merger)
        git("push", "-q", "origin", "HEAD:main", cwd=self.repo.merger)

    def faults(self):
        return [n for n, i in self.gh.issues.items() if {"name": "loop:engine-bug"} in i["labels"]]


class HappyPathRegressions(RecoveryCase):
    def test_evidence_and_progress_comments_are_updated_in_place(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        self.run_engine()
        pr = self.gh.prs[self.store.issue(2).pr]
        self.assertNotIn("Closes", pr["body"], "the loop closes the issue itself, with evidence")
        evidence = [c["body"] for c in self.gh.comments[pr["number"]] if "implement-loop:evidence" in c["body"]]
        self.assertEqual(len(evidence), 1)
        self.assertIn("| A1 |", evidence[0])
        progress = [c for c in self.gh.comments[2] if "implement-loop:progress" in c["body"]]
        self.assertEqual(len(progress), 1, "the progress comment is updated in place")

    def test_overlapping_issues_build_one_at_a_time(self):
        self.add_work(2, "docs/shared.txt", "alpha")
        self.add_work(3, "docs/shared.txt", "alpha")
        self.epic(2, 3)
        self.run_engine()
        starts = sorted((e["seq"], e["issue"]) for e in self.events("phase") if e["to"] == "build")
        first = starts[0][1]
        second = next(i for _, i in starts if i != first)
        first_merged = [e["seq"] for e in self.events("merged") if e["issue"] == first][0]
        second_start = min(s for s, i in starts if i == second)
        self.assertLess(first_merged, second_start, f"#{second} must wait for #{first} to leave the writing phases")
        self.assertEqual((self.phase(2), self.phase(3)), (Phase.DONE, Phase.DONE))

    def test_explorers_read_the_issues_themselves(self):
        # #21: an explorer wrote "I could not read issue #21's text or its 8 ledger items"
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        self.run_engine()
        briefing = [c for c in self.agents.calls if c[0] == "explore"][0][3]
        self.assertIn("`docs/a.txt` contains `alpha`.", briefing)


class RoundRegressions(RecoveryCase):
    def test_a_failed_verification_is_fed_back_to_the_builder(self):
        self.add_work(2, "docs/a.txt", "alpha", wrong_attempts=1)
        self.epic(2)
        self.run_engine()
        self.assertEqual(self.phase(2), Phase.DONE)
        feedback = [c[3] for c in self.builds()]
        self.assertEqual(len(feedback), 2)
        self.assertFalse(any("failed" in f for f in feedback[0]))
        self.assertTrue(any(f.startswith("D1") and "fail" in f for f in feedback[1]), feedback[1])

    def test_a_failed_issue_leaves_independent_work_alone_and_stays_open(self):
        self.add_work(2, "docs/a.txt", "alpha", wrong_attempts=99)
        self.add_work(3, "docs/b.txt", "beta", blocked_by=(2,))
        self.add_work(4, "docs/c.txt", "gamma")
        self.epic(2, 3, 4)
        summary = self.run_engine()
        self.assertEqual(self.phase(4), Phase.DONE, "independent work carries on")
        self.assertEqual((set(summary["failed"]), set(summary["waiting"])), ({2}, {3}))
        self.assertIn("#2", self.store.issue(3).wait["detail"])
        self.assertIn({"name": "loop:failed"}, self.gh.issues[2]["labels"])
        self.assertIn({"name": "loop:waiting"}, self.gh.issues[3]["labels"])
        self.assertEqual(self.gh.issues[2]["state"], "open")
        self.assertFalse([pr for pr in self.gh.prs.values() if pr["head"]["ref"] == "feat/issue-2"])
        self.assertEqual(len(self.faults()), 1, "the non-delivery is filed as a loop fault")

    def test_an_edit_to_a_locked_test_never_reaches_a_commit(self):
        self.add_work(2, "docs/a.txt", "alpha", findings=1, tamper=True)
        self.epic(2)
        summary = self.run_engine()
        self.assertEqual(summary["phases"], {"done": 1})
        self.assertEqual(self.events("locked_changes_reverted", 2)[0]["files"], ["checks/issue_2.sh"])
        self.assertNotIn("exit 0", self.repo.main_file("checks/issue_2.sh"), "the edit never reaches a commit")
        touched = git("log", "--format=%s", "origin/main", "--", "checks/issue_2.sh", cwd=self.repo.work)
        self.assertEqual(len(touched.splitlines()), 1, "only the squash merge touches the locked test")
        guard = self.guard()
        self.assertEqual(guard.returncode, 0, guard.stdout + guard.stderr)

    def test_a_builder_that_is_always_blocked_fails_after_a_replan(self):
        self.add_work(2, "docs/a.txt", "alpha", impossible=True)
        self.epic(2)
        self.run_engine()
        st = self.store.issue(2)
        self.assertEqual((st.phase, st.fail["cause"]), (Phase.FAILED, "no_progress"))
        self.assertIn("contradict", st.fail["detail"])
        self.assertEqual(len(self.events("replan", 2)), 1)
        self.assertTrue(any("needs a typed request" in p for p in self.events("round_failed", 2)[0]["problems"]))
        self.assertLessEqual(len(self.builds()), Caps().unproductive_fail + 2)
        self.assertFalse(self.gh.prs)

    def test_a_blocking_finding_is_fed_back_with_its_witness(self):
        self.add_work(2, "docs/a.txt", "alpha", findings=1)
        self.epic(2)
        self.run_engine()
        self.assertEqual(self.phase(2), Phase.DONE)
        fix = self.builds()[1][3]
        self.assertTrue(any("an edge case breaks the item" in f and "Reproduce: test -f edge_2.txt" in f
                            for f in fix), fix)

    def test_a_defect_that_never_goes_away_fails_the_issue_and_nothing_lands(self):
        self.add_work(2, "docs/a.txt", "alpha", items=["`docs/a.txt` contains `alpha`.",
                                                        "The page reads clearly to a student."],
                      review_items=("D2",), unmet_review=99)
        self.epic(2)
        self.run_engine()
        st = self.store.issue(2)
        self.assertEqual((st.phase, st.fail["cause"]), (Phase.FAILED, "no_progress"))
        self.assertFalse(self.gh.prs, "nothing is opened for merge")
        self.assertIsNone(self.repo.main_file("docs/a.txt"))

    def test_an_outage_resumes_at_the_examination_without_rebuilding(self):
        self.add_work(2, "docs/a.txt", "alpha", outages=1)
        self.epic(2)
        self.run_engine()
        self.assertEqual((self.phase(2), self.store.issue(2).wait["resume"]), (Phase.WAITING, "examine"))
        self.assertFalse(self.faults(), "an outage is not an engine fault")
        before = len(self.agents.calls)
        self.run_engine(agents=self.agents)   # the outage is over: the same fake now answers
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertEqual(self.events("resumed", 2)[0]["phase"], "examine")
        self.assertFalse([c for c in self.agents.calls[before:] if c[0] in ("plan", "triage", "build")])

    def test_a_red_required_check_goes_back_to_the_builder_with_the_log(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        self.gh.check_script = ["failure", "failure"]   # red, red again after the re-run, then green
        agents = FakeAgents(self.scripts)
        original = agents.build

        def fix_round(vendor, req, plan, worktree, feedback):
            # this fake's fix commits nothing new, so let CI evaluate the same head afresh
            if any("required CI check" in f for f in feedback):
                self.gh._check_seen.clear()
            return original(vendor, req, plan, worktree, feedback)
        agents.build = fix_round
        self.run_engine(agents=agents)
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertEqual(len(self.gh.reruns), 1)
        feedback = self.builds()[1][3]
        self.assertTrue(any("fake CI failure" in f for f in feedback))

    def test_a_check_that_stays_red_fails_without_merging(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        self.gh.default_check = "failure"
        self.run_engine()
        st = self.store.issue(2)
        self.assertEqual((st.phase, st.fail["cause"]), (Phase.FAILED, "no_progress"))
        self.assertIn("required CI check is 'failure'", st.fail["detail"])
        self.assertIsNone(self.repo.main_file("docs/a.txt"))
        self.assertFalse([c for c in self.gh.calls if c[0] == "merge_pr"])

    def test_a_check_with_no_verdict_waits_and_the_next_run_lands_it(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        self.gh.default_check = "cancelled"
        self.run_engine()
        st = self.store.issue(2)
        self.assertEqual((st.phase, st.wait["kind"], st.wait["resume"]), (Phase.WAITING, "ci", "land"))
        self.gh.default_check = "success"
        self.run_engine(agents=self.agents)
        self.assertEqual(self.phase(2), Phase.DONE)

    def test_the_owner_ticks_an_owner_item_and_the_next_run_closes_the_issue_and_the_epic(self):
        self.add_work(2, "docs/a.txt", "alpha", items=["`docs/a.txt` contains `alpha`.",
                                                        "Runs under a second on a 2020 laptop."],
                      owner_items=("D2",))
        self.add_work(3, "docs/b.txt", "beta", blocked_by=(2,))
        self.epic(2, 3)
        self.run_engine()
        self.assertEqual((self.phase(2), self.phase(3)), (Phase.DELIVERED, Phase.DONE))
        body = self.gh.issues[2]["body"]
        self.assertIn("- [ ] Runs under a second on a 2020 laptop.", body)
        self.assertIn("- [x] `docs/a.txt` contains `alpha`.", body)
        self.assertIn("- [x] The test passes on main.", body)
        self.assertEqual(self.gh.issues[EPIC]["state"], "open", "the epic waits for the owner's evidence")
        summary = [c["body"] for c in self.gh.comments[EPIC] if "implement-loop:run" in c["body"]][0]
        self.assertIn("Remaining obligations", summary)
        self.assertIn("#2 D2: needs hardware:laptop", summary)
        # the owner ticks the box; the next run closes the issue and the epic
        self.gh.issues[2]["body"] = body.replace("- [ ] Runs under a second", "- [x] Runs under a second")
        self.run_engine(agents=FakeAgents(self.scripts))
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertTrue(self.events("owner_evidence_complete", 2))
        self.assertEqual(self.gh.issues[2]["state"], "closed")
        self.assertEqual(self.gh.issues[EPIC]["state"], "closed")


class RequirementRegressions(RecoveryCase):
    """Regression tests for the cross-vendor review of PR #54."""

    def test_criteria_edited_while_building_are_delivered_as_edited(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        agents = FakeAgents(self.scripts)
        original = agents.build
        edited = []

        def build_then_edit(*args, **kwargs):
            result = original(*args, **kwargs)
            if not edited:
                body = self.gh.issues[2]["body"]
                self.gh.issues[2]["body"] = (body.replace("The test passes on main.", "The test passes on main, as edited.")
                                             + "- [ ] A second criterion.\n")
                edited.append(True)
            return result
        agents.build = build_then_edit
        self.run_engine(agents=agents)
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertTrue(self.events("requirements_changed", 2))
        body = self.gh.issues[2]["body"]
        self.assertIn("- [x] The test passes on main, as edited.", body)
        self.assertIn("- [x] A second criterion.", body)

    def test_criteria_edited_after_merge_are_never_ticked_with_old_evidence(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        merge = self.gh.on_merge

        def merge_then_edit(branch, sha):
            result = merge(branch, sha)
            self.gh.issues[2]["body"] = self.gh.issues[2]["body"].replace("The test passes on main.",
                                                                         "A different criterion.")
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
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        real_verify = engine_mod.verify.verify
        ticked = []

        def verify_then_edit(root, *args, **kwargs):
            result = real_verify(root, *args, **kwargs)
            if Path(root).name == "coord":
                ticked.append("- [x] The test passes on main." in self.gh.issues[2]["body"])
                self.gh.issues[2]["body"] = self.gh.issues[2]["body"].replace("The test passes on main.",
                                                                             "Something else entirely.")
            return result
        with mock.patch.object(engine_mod.verify, "verify", verify_then_edit):
            self.run_engine()
        self.assertEqual(self.store.issue(2).round, 2)
        self.assertTrue(self.events("new_round", 2))
        self.assertFalse(any(ticked), "never ticked with old evidence")
        self.assertIn("- [x] Something else entirely.", self.gh.issues[2]["body"])

    def test_a_finding_that_cannot_be_reproduced_is_published_never_dropped(self):
        self.add_work(2, "docs/a.txt", "alpha", advisory_findings=1)
        self.epic(2)
        self.run_engine()
        self.assertEqual(self.phase(2), Phase.DONE)
        advisory = [f for f in self.store.issue(2).findings if f["status"] == "advisory"]
        self.assertEqual([(f["title"], f["reason"]) for f in advisory],
                         [("the edge case may break the item", "no runnable reproduction")])
        pr = self.gh.prs[self.store.issue(2).pr]
        self.assertIn("the edge case may break the item (no runnable reproduction)", pr["body"])
        self.assertEqual(len(self.builds()), 1, "it never blocked")


class AgentGitRegressions(RecoveryCase):
    def test_tags_and_branches_an_agent_creates_are_deleted(self):
        self.add_work(2, "docs/a.txt", "alpha", tags=True, branches=True)
        self.epic(2)
        self.run_engine()
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertEqual(git("tag", "--list", "agent-probe-*", cwd=self.repo.work), "")
        self.assertEqual(git("branch", "--list", "agent-branch-*", cwd=self.repo.work), "")
        self.assertEqual(self.events("agent_refs_deleted", 2)[0]["refs"],
                         ["refs/heads/agent-branch-2", "refs/tags/agent-probe-2"])

    def test_commits_an_agent_makes_are_absorbed_into_engine_commits(self):
        self.add_work(2, "docs/a.txt", "alpha", commits=True)
        self.epic(2)
        self.run_engine()
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertEqual(len(self.events("agent_commits_absorbed", 2)), 1)
        log = git("log", "--format=%s", "origin/feat/issue-2", cwd=self.repo.work)
        self.assertNotIn("agent commit", log)
        self.assertIn("Build #2", log)

    def force_added_file_survives_the_agent_call(self, commit_inside):
        ws = Workspace(self.repo.work, EPIC, SHIP, base_dir=self.repo.loop_dir)
        wt = ws.issue_worktree(2, "feat/issue-2")
        (wt / ".gitignore").write_text("required.bin\n")
        with ws.agent_call(wt):
            (wt / "required.bin").write_bytes(b"\x00staged by the agent\n")
            git("add", "-f", "required.bin", cwd=wt)
            if commit_inside:
                git("commit", "-q", "-m", "agent commit", cwd=wt)
        self.assertIn("required.bin", git("ls-files", "--cached", "required.bin", cwd=wt))
        sha = ws.commit_all(wt, "Build #2", "implementation", 2)
        self.assertEqual(git("show", f"{sha}:required.bin", cwd=wt), "\x00staged by the agent")
        self.assertEqual(git("fsck", "--connectivity-only", "--no-dangling", cwd=self.repo.work), "")

    def test_a_file_an_agent_force_adds_is_kept_in_the_index(self):
        self.force_added_file_survives_the_agent_call(commit_inside=False)

    def test_a_file_an_agent_force_adds_and_commits_is_kept_in_the_index(self):
        self.force_added_file_survives_the_agent_call(commit_inside=True)

    def test_a_commit_made_after_verification_is_verified_before_examination(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        original = Engine._step_verify
        store_dir = self.store_dir()

        def verify_then_stop(engine, n):
            original(engine, n)
            (store_dir / "STOP").write_text("stop\n")
        with mock.patch.object(Engine, "_step_verify", verify_then_stop):
            self.run_engine()
        self.assertEqual(self.phase(2), Phase.EXAMINE)
        wt = Path(self.store.issue(2).worktree)
        (wt / "docs" / "a.txt").write_text("sabotage\n")
        git("commit", "-qam", "stray commit after verification", cwd=wt)
        (store_dir / "STOP").unlink()
        self.run_engine(agents=FakeAgents(self.scripts))
        self.assertTrue(self.events("head_changed_before_examination", 2))
        self.assertEqual(self.repo.main_file("docs/a.txt"), "alpha", "only verified content may reach main")


class LockedTestRegressions(RecoveryCase):
    """A locked test changes only with the agreement of both vendors (ADR 0012, Q2)."""

    def test_a_locked_test_changes_only_through_an_approved_request(self):
        # #21: a locked chart test waited for "no SVG in any chart"; it cost a full redesign
        self.add_work(2, "docs/a.txt", "alpha", findings=1, test_change=True)
        self.epic(2)
        self.run_engine()
        self.assertEqual(self.phase(2), Phase.DONE)
        st = self.store.issue(2)
        self.assertEqual(self.events("requests_decided", 2)[0]["decided"], {"R2-1": "approved"})
        self.assertEqual(self.roles("decide"), {"codex"}, "the other vendor agrees to the change")
        self.assertEqual(self.events("locked_tests_changed", 2)[0]["files"], ["checks/issue_2.sh"])
        self.assertEqual(st.replans, 0, "changed, not replanned")
        self.assertIn("# amended through an approved request", self.repo.main_file("checks/issue_2.sh"))
        bodies = git("log", "--format=%B", "origin/feat/issue-2", cwd=self.repo.work)
        self.assertIn("Loop-Approved: R2-1 by codex", bodies)
        guard = self.guard()
        self.assertEqual(guard.returncode, 0, guard.stdout + guard.stderr)

    def test_a_refused_test_change_leaves_the_locked_test_as_it_was(self):
        self.add_work(2, "docs/a.txt", "alpha", findings=1, test_change=True)
        self.epic(2)
        agents = FakeAgents(self.scripts)
        agents.decide = lambda vendor, req, wt, requests: agents._metered(
            2, "decide", vendor, lambda: [Decision(r["id"], False, "the item never asks for it") for r in requests])
        self.run_engine(agents=agents)
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertEqual(self.events("requests_decided", 2)[0]["decided"], {"R2-1": "refused"})
        self.assertFalse(self.events("locked_tests_changed", 2))
        self.assertTrue(any("checks/issue_2.sh" in e["files"] for e in self.events("locked_changes_reverted", 2)))
        self.assertNotIn("amended", self.repo.main_file("checks/issue_2.sh"))

    def test_a_test_change_request_must_carry_an_edit_to_a_locked_test(self):
        self.add_work(2, "docs/a.txt", "alpha", findings=1)
        self.epic(2)
        agents = FakeAgents(self.scripts)
        original = agents.build

        def ask_without_editing(vendor, req, plan, worktree, feedback):
            result = original(vendor, req, plan, worktree, feedback)
            if len([c for c in agents.calls if c[0] == "build"]) == 2:
                result.requests.append(Request("test_change", "this test is wrong", paths=["docs/a.txt"]))
            return result
        agents.build = ask_without_editing
        self.run_engine(agents=agents)
        self.assertEqual(self.phase(2), Phase.DONE)
        request = self.store.issue(2).requests[0]
        self.assertEqual(request["status"], "refused")
        self.assertIn("needs the proposed content", request["reason"])
        self.assertFalse([c for c in agents.calls if c[0] == "decide"], "nothing for the other vendor to decide")
        self.assertFalse(self.events("locked_tests_changed", 2))
        self.assertEqual(self.repo.main_file("docs/a.txt"), "alpha", "a request never deletes what it names")

    def test_an_interrupted_build_never_lands_an_edit_to_a_locked_test(self):
        self.add_work(2, "docs/a.txt", "alpha", findings=1)
        self.epic(2)
        agents = FakeAgents(self.scripts)
        original = agents.build
        store_dir = self.store_dir()
        interrupted = []

        def half_written(vendor, req, plan, worktree, feedback):
            if self.engine.store.issue(2).locked and not interrupted:   # the round after the first examination
                interrupted.append(True)
                (worktree / "checks" / "issue_2.sh").write_text("#!/usr/bin/env bash\n# half-written edit\n")
                (store_dir / "STOP").write_text("stop\n")
                raise type("AgentStopped", (RuntimeError,), {})("stopped mid-build")
            return original(vendor, req, plan, worktree, feedback)
        agents.build = half_written
        self.run_engine(agents=agents)
        self.assertEqual(self.phase(2), Phase.BUILD)
        self.assertTrue(self.events("step_interrupted", 2))
        # main moves on, so the next round first checkpoints what the interrupted build left
        self.move_main({"docs/elsewhere.txt": "main moved\n"})
        self.run_engine(agents=agents)   # the stop belonged to the earlier invocation
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertTrue(self.events("checkpoint_before_update", 2))
        self.assertTrue(any("checks/issue_2.sh" in e["files"] for e in self.events("locked_changes_reverted", 2)))
        self.assertNotIn("half-written", self.repo.main_file("checks/issue_2.sh"))
        guard = self.guard()
        self.assertEqual(guard.returncode, 0, guard.stdout + guard.stderr)


class RecordedRunRegressions(RecoveryCase):
    """The failures of the first live runs (2026-10-04, epic #11 and #21), replayed."""

    def test_an_environment_failure_waits_without_spending_rounds_and_resumes_when_fixed(self):
        # #21: Chromium's shared libraries were missing; two implement attempts were wasted on it
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        agents = FakeAgents(self.scripts)
        original = agents.build

        def test_needing_the_host(vendor, req, plan, worktree, feedback):
            result = original(vendor, req, plan, worktree, feedback)
            target = worktree / "checks" / "issue_2.sh"
            target.write_text(target.read_text().replace(
                "set -euo pipefail\n",
                'set -euo pipefail\n[ "${HOST_LIBS_OK:-}" = 1 ] || { echo "chrome: error while loading shared libraries: libnspr4.so"; exit 127; }\n'))
            return result
        agents.build = test_needing_the_host
        self.run_engine(agents=agents)
        st = self.store.issue(2)
        self.assertEqual((st.phase, st.wait["kind"], st.wait["resume"]), (Phase.WAITING, "environment", "verify"))
        self.assertIn("libnspr4.so", st.wait["detail"])
        self.assertEqual((len(self.builds()), st.unproductive), (1, 0))
        self.assertFalse(self.events("round_failed", 2))

        self.environment = {"fingerprint": "healed", "check_env": {"HOST_LIBS_OK": "1"}}
        self.run_engine(agents=agents)
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertEqual(len(self.builds()), 1, "the same commit is verified again")

    def test_an_engine_fault_is_filed_once_waits_and_is_seen_again_on_a_new_version(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.add_work(3, "docs/b.txt", "beta")
        self.add_work(4, "docs/c.txt", "gamma", size="S")
        self.epic(2, 3, 4)
        original = Engine._step_examine

        def crash_for_m(engine, n):
            if engine.plan.issues[n].size == "M":
                raise KeyError("a bug in the engine at " + str(self.repo.work))
            return original(engine, n)
        with mock.patch.object(Engine, "_step_examine", crash_for_m):
            summary = self.run_engine()
        self.assertEqual({n: self.store.issue(n).wait["kind"] for n in summary["waiting"]}, {2: "engine", 3: "engine"})
        self.assertEqual(self.phase(4), Phase.DONE, "the run carries on")
        filed = [c for c in self.gh.calls if c[0] == "create_issue"]
        self.assertEqual(len(filed), 1, "one issue per distinct fault")
        body = self.gh.issues[filed[0][1]]["body"]
        self.assertIn("implement-loop:fault:", body)
        self.assertNotIn(str(self.repo.work), body, "local paths are redacted")
        self.assertIn({"name": "loop:engine-bug"}, self.gh.issues[filed[0][1]]["labels"])

        # a new engine version resumes them; the same fault is a comment on the same issue
        with mock.patch.object(Engine, "_step_examine", crash_for_m), mock.patch.object(engine_mod, "VERSION", "9.9.9"):
            self.run_engine(agents=self.agents)
        self.assertEqual({e["issue"] for e in self.events("resumed")}, {2, 3})
        self.assertEqual(len([c for c in self.gh.calls if c[0] == "create_issue"]), 1)
        self.assertTrue(any("Seen again" in c["body"] for c in self.gh.comments.get(filed[0][1], [])))

    def test_an_unavailable_agent_waits_as_an_outage_and_is_not_filed(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        agents = FakeAgents(self.scripts)

        def unavailable(vendor, req, plan, worktree, feedback):
            raise AgentFailure(f"{vendor} build failed after 3 attempts: 529 overloaded", kind="outage", vendor=vendor)
        agents.build = unavailable
        self.run_engine(agents=agents)
        st = self.store.issue(2)
        self.assertEqual((st.phase, st.wait["kind"], st.wait["resume"], st.wait["vendor"]),
                         (Phase.WAITING, "outage", "build", "claude"))
        self.assertEqual((st.infra, st.calls), (0, 2), "an outage is charged to no budget")
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
        regressions = [e for e in self.events("regression_check") if e["issue"] == 3]
        self.assertTrue(regressions and not regressions[0]["ok"])
        self.assertEqual(regressions[0]["of"], 2)
        self.assertEqual(len(self.events("fix_forward", 3)), 1, "one fix-forward round")
        self.assertTrue(any("#2's checks fail on main" in f for f in self.builds(3)[1][3]),
                        "the fix-forward round is told what broke")
        # The fix-forward changed nothing, so the breaking PR is reverted and #3 delivered once
        # more; it breaks main again, is reverted again, and fails. Main is never left red.
        reverted = self.events("reverted", 3)
        first_pr = [e["pr"] for e in self.events("merged") if e["issue"] == 3][0]
        self.assertEqual(len(reverted), 2)
        self.assertEqual(reverted[0]["of"], [first_pr])
        self.assertTrue(all(self.gh.prs[e["pr"]]["head"]["ref"].endswith("-revert") for e in reverted))
        st = self.store.issue(3)
        self.assertEqual((st.phase, st.fail["cause"], st.reverts), (Phase.FAILED, "main_broken", 2))
        self.assertEqual(self.repo.main_file("docs/a.txt"), "alpha", "main is green again")

    def test_a_pr_merged_by_someone_else_at_another_head_is_accepted_on_main(self):
        # #21: the owner merged PR #61 by hand after a CI-only change; the engine could not resume
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        self.run_engine()
        st = self.store.issue(2)
        pr = self.gh.prs[st.pr]
        pr["head"]["sha"] = "f2e878c" + "0" * 33   # updated with main before the owner merged it
        self.gh.issues[2]["state"] = "open"          # as if the engine had stopped before accepting it
        st.phase = Phase.LAND
        self.store.put(st)
        self.run_engine(agents=FakeAgents(self.scripts))
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertEqual(self.events("merged_externally", 2)[0]["head"], pr["head"]["sha"])

    def test_a_failed_issue_is_retried_only_on_a_new_engine_version_and_only_once(self):
        self.add_work(2, "docs/a.txt", "alpha", wrong_attempts=99)
        self.epic(2)
        self.run_engine()
        self.assertEqual(self.phase(2), Phase.FAILED)
        before = len(self.agents.calls)
        self.run_engine(agents=self.agents)
        self.assertEqual(self.phase(2), Phase.FAILED, "an unchanged failure is not retried without new evidence")
        self.assertEqual(self.agents.calls[before:], [])
        with mock.patch.object(engine_mod, "VERSION", "9.9.9"):
            self.run_engine(agents=self.agents)
        self.assertEqual(len(self.events("revived", 2)), 1)
        self.assertEqual(self.phase(2), Phase.FAILED, "still wrong")
        self.assertTrue(self.store.issue(2).fail["resumed"])
        with mock.patch.object(engine_mod, "VERSION", "9.9.10"):
            self.run_engine(agents=self.agents)
        self.assertEqual(len(self.events("revived", 2)), 1, "one more try per failure, not one per version")


class CrossVendorRegressions(RecoveryCase):
    """Regression tests for Codex's review of the autonomous engine (PR 1)."""

    def test_an_older_merged_pr_of_a_reused_branch_is_not_mistaken_for_this_delivery(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        old_head = git("rev-parse", "origin/main", cwd=self.repo.work)   # contains nothing of this delivery
        self.gh.prs[4999] = {"number": 4999, "head": {"ref": "feat/issue-2", "sha": old_head}, "base": {"ref": "main"},
                             "title": "old", "body": "", "state": "closed", "merged": True, "labels": []}
        self.run_engine()
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertEqual(self.events("stale_pr_ignored", 2)[0]["pr"], 4999)
        self.assertEqual(self.repo.main_file("docs/a.txt"), "alpha", "the real work was merged")
        self.assertNotEqual(self.store.issue(2).pr, 4999)

    def review_issue(self):
        self.gh.add_issue(2, "Issue 2", issue_body("feat/issue-2", ["`docs/a.txt` contains `alpha`."], ["It reads well."]),
                          labels=("size:M",))
        self.scripts[2] = Script(files={"docs/a.txt": "alpha"}, review_items=("A1",))
        self.epic(2)

    def test_examiner_verdicts_do_not_survive_unreviewed_changes_in_an_external_merge(self):
        self.review_issue()
        original = Engine._step_land

        def someone_else_merges(engine, n):
            # the owner pushes a change to a certified path and merges the PR by hand, once
            st = engine.store.issue(n)
            if st.round > 1:
                return original(engine, n)
            wt = Path(st.worktree)
            engine.ws.push(wt)
            (wt / "docs" / "a.txt").write_text("alpha, edited after review\n")
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
        self.assertTrue(self.events("new_round", 2), "the unreviewed item is delivered again")
        self.assertEqual(self.phase(2), Phase.DONE)

    def test_an_edit_inside_a_merge_commit_also_invalidates_examiner_verdicts(self):
        self.review_issue()
        original = Engine._step_land

        def merge_main_with_an_edit(engine, n):
            st = engine.store.issue(n)
            if st.round > 1:
                return original(engine, n)
            wt = Path(st.worktree)
            engine.ws.push(wt)
            self.move_main({"docs/other.txt": "unrelated\n"})
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

    def test_a_merge_github_keeps_refusing_waits_instead_of_looping(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)

        def refuse(n, sha, method="squash"):
            raise GitHubError("Pull Request is not mergeable")
        self.gh.merge_pr = refuse
        self.run_engine()
        st = self.store.issue(2)
        self.assertEqual((st.phase, st.wait["kind"], st.wait["resume"], st.merge_refusals),
                         (Phase.WAITING, "github", "land", 3))
        self.assertEqual(len(self.events("merge_refused", 2)), 3)

    def test_a_leftover_stop_request_does_not_stop_the_next_run(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        (self.store_dir() / "STOP").write_text("stop requested\n")
        summary = self.run_engine()
        self.assertFalse(summary["stopped"])
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertTrue(self.events("stale_stop_cleared"))

    def test_earlier_issues_are_regression_checked_after_a_restart(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.add_work(3, "docs/a.txt", "broken", blocked_by=(2,))
        self.epic(2, 3)
        original = Engine._step_plan

        def stop_before_3(engine, n):
            if n == 3:
                (engine.store.dir / "STOP").write_text("stop\n")
                raise type("AgentStopped", (RuntimeError,), {})("stopped")
            return original(engine, n)
        with mock.patch.object(Engine, "_step_plan", stop_before_3):
            self.run_engine()
        self.assertEqual(self.gh.issues[2]["state"], "closed", "#2 is done and leaves the next plan's work")
        self.run_engine(agents=FakeAgents(self.scripts))
        checked = [e for e in self.events("regression_check") if e["issue"] == 3]
        self.assertTrue(checked and checked[0]["of"] == 2 and not checked[0]["ok"])

    def test_published_fault_reports_carry_no_exception_message(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)

        def leak(engine, n):
            raise RuntimeError("Authorization: Bearer ghp_secret123 at https://user:pw@example.test")
        with mock.patch.object(Engine, "_step_examine", leak):
            self.run_engine()
        filed = [c for c in self.gh.calls if c[0] == "create_issue"][0][1]
        public = self.gh.issues[filed]["body"] + "".join(c["body"] for c in self.gh.comments.get(2, []))
        self.assertNotIn("ghp_secret123", public)
        self.assertNotIn("user:pw", public)
        self.assertIn("RuntimeError", public)
        self.assertIn("ghp_secret123", [e for e in self.store.events() if e["kind"] == "step_crashed"][0]["error"],
                      "the local journal keeps the detail")

    def test_a_fault_issue_created_before_a_lost_response_is_not_filed_twice(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        real_create = self.gh.create_issue

        def create_then_lose_the_response(title, body, labels):
            real_create(title, body, labels)
            raise GitHubError("connection reset")
        self.gh.create_issue = create_then_lose_the_response

        def crash(engine, n):
            raise KeyError("x")
        with mock.patch.object(Engine, "_step_examine", crash):
            self.run_engine()
        self.gh.create_issue = real_create
        self.run_engine(agents=FakeAgents(self.scripts))
        faults = [n for n, i in self.gh.issues.items() if "implement-loop:fault:" in (i.get("body") or "")]
        self.assertEqual(len(faults), 1)


class ResumeTests(RecoveryCase):
    def test_stop_then_resume_finishes_without_redoing_work(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        agents = FakeAgents(self.scripts)
        original = agents.build

        def build_then_stop(*args, **kwargs):
            result = original(*args, **kwargs)
            (self.store_dir() / "STOP").write_text("stop\n")
            return result
        agents.build = build_then_stop
        summary = self.run_engine(agents=agents)
        self.assertTrue(summary["stopped"])
        self.assertEqual(self.phase(2), Phase.VERIFY)
        (self.store_dir() / "STOP").unlink()

        again = FakeAgents(self.scripts)
        summary = self.run_engine(agents=again)
        self.assertEqual(summary["phases"], {"done": 1})
        self.assertFalse(any(c[0] in ("plan", "triage", "build") for c in again.calls),
                         "a resumed run continues from the saved phase")

    def test_changed_requirements_invalidate_the_plan(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        agents = FakeAgents(self.scripts)
        original = agents.triage

        def triage_then_stop(*args, **kwargs):
            (self.store_dir() / "STOP").write_text("stop\n")
            return original(*args, **kwargs)
        agents.triage = triage_then_stop
        self.run_engine(agents=agents)
        self.assertEqual(self.phase(2), Phase.PLANNED)
        (self.store_dir() / "STOP").unlink()

        self.gh.issues[2]["body"] = self.gh.issues[2]["body"].replace("The test passes on main.",
                                                                     "The test passes on main twice.")
        again = FakeAgents(self.scripts)
        self.run_engine(agents=again)
        self.assertEqual([e["kind"] for e in self.events("requirements_changed")], ["requirements_changed"])
        self.assertTrue(any(c[0] == "plan" for c in again.calls), "the plan is redone")
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
        st.phase, st.wait = Phase.LAND, None   # as if the process died before handling the crash
        self.store.put(st)
        self.gh.merge_pr = real_merge
        self.run_engine(agents=FakeAgents(self.scripts))
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertEqual(len(self.events("merge_found_on_resume")), 1)
        self.assertEqual(len([c for c in self.gh.calls if c[0] == "merge_pr"]), 1, "never merged twice")

    def test_a_branch_lost_after_shipping_rebased_it_is_restored_at_the_verified_tip(self):
        """Shipping rebases an unpublished branch when main moved, so the recorded examined and
        certified heads are no longer in the verified tip's history; they must not block
        restoring a branch deleted afterwards."""
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        real_push, real_verify = Workspace.push, Engine._step_verify
        stopped = []

        def push(ws, wt):
            if not (self.repo.merger / "docs/moved.txt").exists():
                self.move_main({"docs/moved.txt": "main moved\n"})
            return real_push(ws, wt)

        def verify_then_stop(engine, n):
            real_verify(engine, n)
            changed = any(e["kind"] == "head_changed_after_certificate" for e in engine.store.events())
            if changed and not stopped:   # the rebased tip is verified
                stopped.append(True)
                (self.store_dir() / "STOP").write_text("stop\n")

        with mock.patch.object(Workspace, "push", push), mock.patch.object(Engine, "_step_verify", verify_then_stop):
            self.run_engine()
        (self.store_dir() / "STOP").unlink()
        st = self.store.issue(2)
        self.assertEqual(st.phase, Phase.EXAMINE)
        wt = Path(st.worktree)
        rebased = git("rev-parse", "HEAD", cwd=wt)
        self.assertEqual(st.verified_sha, rebased)
        for stale in (st.examined_sha, st.certified_sha):
            self.assertNotEqual(subprocess.run(["git", "merge-base", "--is-ancestor", stale, rebased],
                                               cwd=wt, capture_output=True).returncode, 0)
        git("update-ref", "-d", git("symbolic-ref", "HEAD", cwd=wt), cwd=self.repo.work)
        st.phase = Phase.WAITING
        st.wait = {"kind": "engine", "resume": "examine", "detail": "the branch was deleted", "since": 0,
                   "version": "0.3.0"}
        self.store.put(st)
        self.run_engine(agents=FakeAgents(self.scripts))
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertEqual(self.events("branch_restore_failed"), [])
        self.assertEqual([e["sha"] for e in self.events("branch_restored")], [rebased])


class KilledCallOnALostBranchTests(IsolationCase):
    """A killed agent call left an executable bit only in its private index, and the issue's
    branch was then deleted (#34's): reattaching must carry the bit without HEAD, and a failed
    carry must keep the private metadata for the next try."""

    def killed_with_staged_executable_bit(self):
        wt = self.worktree()
        git("config", "core.fileMode", "false", cwd=wt)
        original = (wt / ".git").read_bytes()
        base = git("rev-parse", "HEAD", cwd=wt)
        code = "\n".join([
            "import os, signal, subprocess, sys", "from pathlib import Path", "sys.path.insert(0, sys.argv[1])",
            "from implement_loop.workspace import Workspace",
            "ws = Workspace(Path(sys.argv[2]), int(sys.argv[3]), Path(sys.argv[4]), base_dir=Path(sys.argv[5]))",
            "with ws.agent_call(Path(sys.argv[6])):",
            "    subprocess.run(['git', 'update-index', '--chmod=+x', 'README.md'], cwd=sys.argv[6], check=True)",
            "    os.kill(os.getpid(), signal.SIGKILL)",
        ])
        proc = subprocess.run([sys.executable, "-c", code, str(Path(__file__).resolve().parents[1]),
                               str(self.repo.work), str(self.n), str(SHIP), str(self.ws.dir), str(wt)],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, -signal.SIGKILL, proc.stderr)
        private = git_dir(wt)
        self.assertTrue(private.is_relative_to(self.ws.dir.resolve()))
        self.assertEqual(stat.S_IMODE((wt / "README.md").stat().st_mode), 0o644)
        git("update-ref", "-d", "refs/heads/feat/isolated-worker", cwd=self.repo.work)
        return wt, original, base, private

    def assert_mode(self, wt, mode):
        self.assertEqual(git("ls-files", "--stage", "README.md", cwd=wt).split(" ", 1)[0], mode)

    def test_restoring_the_branch_carries_the_executable_bit_without_head(self):
        wt, original, base, private = self.killed_with_staged_executable_bit()
        self.assertEqual(self.ws.restore_branch(wt, [base]), ("refs/heads/feat/isolated-worker", base))
        self.assert_registered(wt, original)
        self.assert_ref(self.repo.work, "refs/heads/feat/isolated-worker", base)
        self.assert_mode(wt, "100755")
        self.assertFalse(private.exists())

    def test_the_engine_restores_the_branch_and_keeps_the_executable_bit(self):
        wt, original, base, private = self.killed_with_staged_executable_bit()
        self.engine._reconcile()
        self.assertEqual(self.events("branch_restore_failed"), [])
        self.assertEqual([(e["branch"], e["sha"]) for e in self.events("branch_restored")],
                         [("feat/isolated-worker", base)])
        self.assertNotIn(self.store.issue(self.n).phase, (Phase.WAITING, Phase.FAILED))
        self.assertEqual(self.events("new_round"), [], "the work is kept, not started again")
        self.assert_registered(wt, original)
        self.assert_mode(wt, "100755")
        self.assertFalse(private.exists())

    def test_a_failed_carry_keeps_the_private_metadata_for_the_next_reattach(self):
        wt, original, base, private = self.killed_with_staged_executable_bit()
        git("update-ref", "refs/heads/feat/isolated-worker", base, cwd=self.repo.work)
        with mock.patch.object(self.ws, "restore_index_entry", side_effect=GitError("index locked")):
            with self.assertRaises(GitError):
                self.ws.reattach(wt)
        self.assertEqual(git_dir(wt), private)
        self.assert_mode(wt, "100755")
        self.ws.reattach(wt)
        self.assert_registered(wt, original)
        self.assert_mode(wt, "100755")
        self.assertFalse(private.exists())

    def test_removing_the_worktree_does_not_depend_on_carrying(self):
        wt, original, base, private = self.killed_with_staged_executable_bit()
        with mock.patch.object(self.ws, "restore_index_entry", side_effect=GitError("index locked")):
            self.ws.remove(wt)
        self.assertFalse(wt.exists())
        self.assertFalse(private.exists())
        self.assertNotIn(str(wt), git("worktree", "list", "--porcelain", cwd=self.repo.work))


if __name__ == "__main__":
    unittest.main()
