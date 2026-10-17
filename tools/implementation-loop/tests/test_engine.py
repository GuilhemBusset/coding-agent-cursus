"""End-to-end runs of the builder/examiner engine (ADR 0012): real git, the real ship.sh, the real
verifier and real squash merges into a local bare remote. Only the agents and GitHub are fakes."""

import unittest
from unittest import mock

from helpers import SHIP, TempRepo, git, issue_body

from implement_loop import engine as engine_mod
from implement_loop.agents import FakeAgents, Script
from implement_loop.config import Caps, Config
from implement_loop.engine import Engine
from implement_loop.github import FakeGitHub
from implement_loop.graph import build_plan
from implement_loop.model import Phase
from implement_loop.state import RepoClaims, RunStore
from implement_loop.workspace import Workspace

EPIC = 1
LACKS = ["hardware:laptop", "human:rehearsal"]


class EngineCase(unittest.TestCase):
    def setUp(self):
        self.repo = TempRepo()
        self.gh = FakeGitHub(on_merge=self.repo.merge)
        self.scripts: dict[int, Script] = {}
        self.policy = {"lacks": LACKS}

    def tearDown(self):
        self.repo.cleanup()

    def add_work(self, n, path, content, blocked_by=(), size="M", items=None, **script):
        deliverables = items or [f"`{path}` contains `{content}`."]
        self.gh.add_issue(n, f"Issue {n}", issue_body(f"feat/issue-{n}", deliverables, ["The test passes on main."]),
                          labels=(f"size:{size}",), blocked_by=blocked_by)
        self.scripts[n] = Script(files={path: content}, **script)

    def epic(self, *children):
        self.gh.add_issue(EPIC, "Epic", "An epic.\n", subs=children)

    def run_engine(self, agents=None, caps=None, fresh=False, policy=None):
        plan = build_plan(self.gh, EPIC, self.repo.work)
        store = RunStore.for_root(self.repo.work, EPIC, fresh=fresh)
        ws = Workspace(self.repo.work, EPIC, SHIP, base_dir=self.repo.loop_dir)
        self.agents = agents or FakeAgents(self.scripts)
        cfg = Config(repo="test/test", caps=caps or Caps(ci_poll_s=0, queue_poll_s=0))
        engine = Engine(plan, store, self.gh, ws, self.agents, cfg, repo_root=self.repo.work,
                        log=lambda m: None, sleep=lambda s: None, environment=getattr(self, "environment", None),
                        policy=policy or self.policy)
        self.engine = engine
        summary = engine.run()
        self.store = store
        return summary

    def phase(self, n):
        return self.store.issue(n).phase

    def events(self, kind=None, issue=None):
        return [e for e in self.store.events() if (kind is None or e["kind"] == kind) and (issue is None or e.get("issue") == issue)]

    def roles(self, kind):
        return {c[1] for c in self.agents.calls if c[0] == kind}


class HappyPathTests(EngineCase):
    def test_dependent_issues_land_in_order_with_evidence(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.add_work(3, "docs/b.txt", "beta", blocked_by=(2,))
        self.epic(2, 3)
        summary = self.run_engine()

        self.assertEqual(summary["phases"], {"done": 2})
        self.assertEqual(self.repo.main_file("docs/a.txt"), "alpha")
        self.assertEqual(self.repo.main_file("docs/b.txt"), "beta")
        self.assertTrue(self.repo.main_file("checks/issue_2.sh").startswith("#!/usr/bin/env bash"))
        self.assertTrue(self.repo.main_file("checks/probe_2.sh").startswith("#!/usr/bin/env bash"),
                        "the examiner's passing probe is adopted as locked evidence")
        self.assertEqual([e["issue"] for e in self.events("merged")], [2, 3])
        first_b = min(e["seq"] for e in self.events("phase", 3) if e["to"] == "plan")
        a_done = min(e["seq"] for e in self.events("phase", 2) if e["to"] == "done")
        self.assertLess(a_done, first_b, "#3 waits until #2 is delivered")
        pr = self.gh.prs[self.store.issue(2).pr]
        self.assertTrue(pr["merged"])
        self.assertTrue(pr["body"].startswith("Refs #2"))
        self.assertIn("## Decisions", pr["body"])
        self.assertIn("examined, probed and certified", pr["body"])
        body = self.gh.issues[2]["body"]
        self.assertIn("- [x] The test passes on main. ([evidence](", body)
        self.assertEqual(self.gh.issues[2]["state"], "closed")
        self.assertEqual(self.gh.issues[EPIC]["state"], "closed")

    def test_two_keys_one_per_vendor(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        self.run_engine()
        self.assertEqual(self.roles("plan"), {"claude"})
        self.assertEqual(self.roles("build"), {"claude"})
        self.assertEqual(self.roles("triage"), {"codex"})
        self.assertEqual(self.roles("examine"), {"codex"})
        smooth = [c for c in self.agents.calls if c[0] != "explore"]
        self.assertLessEqual(len(smooth), 5, f"a smooth issue costs about five calls: {smooth}")

    def test_operator_codex_swaps_every_role(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        self.run_engine(agents=FakeAgents(self.scripts, operator="codex", other="claude"))
        self.assertEqual((self.roles("build"), self.roles("examine")), ({"codex"}, {"claude"}))

    def test_independent_disjoint_issues_overlap_in_time(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.add_work(3, "docs/b.txt", "beta")
        self.epic(2, 3)
        self.run_engine()
        building = {n: [e for e in self.events("phase", n) if e["to"] == "build"][0]["seq"] for n in (2, 3)}
        merged = {e["issue"]: e["seq"] for e in self.events("merged")}
        self.assertLess(max(building.values()), min(merged.values()))
        self.assertEqual((self.phase(2), self.phase(3)), (Phase.DONE, Phase.DONE))

    def test_unquoted_triage_objections_are_dropped(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        self.run_engine()
        planned = self.events("planned", 2)[0]
        self.assertEqual((planned["objections"], planned["kept"]), (1, 0))


class RoundTests(EngineCase):
    def test_wrong_then_right_takes_extra_rounds(self):
        self.add_work(2, "docs/a.txt", "alpha", wrong_attempts=2)
        self.epic(2)
        self.run_engine()
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertEqual(len([c for c in self.agents.calls if c[0] == "build"]), 3)

    def test_no_progress_replans_then_fails_and_its_dependent_waits(self):
        self.add_work(2, "docs/a.txt", "alpha", wrong_attempts=99)
        self.add_work(3, "docs/b.txt", "beta", blocked_by=(2,))
        self.epic(2, 3)
        summary = self.run_engine()
        self.assertEqual(self.phase(2), Phase.FAILED)
        self.assertEqual(self.store.issue(2).fail["cause"], "no_progress")
        self.assertEqual(len(self.events("replan", 2)), 1)
        self.assertEqual(self.phase(3), Phase.WAITING)
        self.assertEqual(self.store.issue(3).wait["kind"], "prerequisite")
        self.assertNotIn("parked", summary["phases"])
        self.assertIsNone(self.repo.main_file("docs/a.txt"), "nothing partial is merged")

    def test_a_blocking_finding_keeps_its_probe_until_fixed(self):
        self.add_work(2, "docs/a.txt", "alpha", findings=1)
        self.epic(2)
        self.run_engine()
        self.assertEqual(self.phase(2), Phase.DONE)
        f = self.store.issue(2).findings
        blocking = [x for x in f if x["blocking"]]
        self.assertEqual(len(blocking), 1)
        self.assertEqual(blocking[0]["status"], "closed")
        self.assertEqual(self.repo.main_file("edge_2.txt"), "handled")

    def test_a_finding_tied_to_no_item_goes_to_a_follow_up_issue(self):
        self.add_work(2, "docs/a.txt", "alpha", unquoted_findings=1)
        self.epic(2)
        self.run_engine()
        self.assertEqual(self.phase(2), Phase.DONE)
        followup = self.store.issue(2).followup
        self.assertIsNotNone(followup)
        self.assertIn({"name": "loop:follow-up"}, self.gh.issues[followup]["labels"])
        self.assertEqual(len([c for c in self.agents.calls if c[0] == "build"]), 1, "it never blocked")

    def test_a_probe_that_fails_unconditionally_is_rejected(self):
        self.add_work(2, "docs/a.txt", "alpha", probe="unconditional")
        self.epic(2)
        self.run_engine()
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertIsNone(self.repo.main_file("checks/probe_2.sh"))
        self.assertTrue(self.events("examined", 2)[0]["rejected"])

    def test_an_edit_to_a_locked_test_is_reverted(self):
        self.add_work(2, "docs/a.txt", "alpha", findings=1, tamper=True)
        self.epic(2)
        self.run_engine()
        self.assertTrue(self.events("locked_changes_reverted", 2))
        self.assertIn("test", self.repo.main_file("checks/issue_2.sh"))

    def test_review_items_block_until_met(self):
        self.add_work(2, "docs/a.txt", "alpha", items=["`docs/a.txt` contains `alpha`.",
                                                        "The page reads clearly to a student."],
                      review_items=("D2",), unmet_review=1)
        self.epic(2)
        self.run_engine()
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertEqual(self.store.issue(2).verdicts["D2"]["verdict"], "met")
        self.assertIn("- [x] The page reads clearly", self.gh.issues[2]["body"])


class ObligationTests(EngineCase):
    def test_an_owner_item_is_delivered_with_its_obligation_and_unblocks_dependents(self):
        self.add_work(2, "docs/a.txt", "alpha", items=["`docs/a.txt` contains `alpha`.",
                                                        "Runs under a second on a 2020 laptop."],
                      owner_items=("D2",))
        self.add_work(3, "docs/b.txt", "beta", blocked_by=(2,))
        self.epic(2, 3)
        self.run_engine()
        self.assertEqual(self.phase(2), Phase.DELIVERED)
        self.assertEqual(self.phase(3), Phase.DONE)
        self.assertEqual(self.store.issue(2).obligations[0]["kind"], "capability")
        self.assertIn("hardware:laptop", self.store.issue(2).human_tasks[0])
        self.assertEqual(self.gh.issues[2]["state"], "open")

    def test_an_owner_claim_for_a_capability_the_host_has_is_demoted(self):
        self.add_work(2, "docs/a.txt", "alpha", items=["`docs/a.txt` contains `alpha`.", "It fetches the page online."],
                      bad_owner_items=("D2",))
        self.epic(2)
        self.run_engine()
        plan = self.store.issue(2).plan
        self.assertEqual(next(i for i in plan["items"] if i["id"] == "D2")["proof"], "review")
        self.assertFalse(self.store.issue(2).obligations)

    def test_an_item_deferred_to_an_issue_outside_the_run_lands_the_rest(self):
        self.gh.add_issue(9, "Prerequisite widget", "The Prerequisite widget the demo plays in.\n")
        self.add_work(2, "docs/a.txt", "alpha", items=["`docs/a.txt` contains `alpha`.", "It plays in the widget."],
                      deferred=(("D2", 9),))
        self.epic(2)
        self.run_engine()
        self.assertEqual(self.phase(2), Phase.DELIVERED)
        ob = self.store.issue(2).obligations
        self.assertEqual((ob[0]["kind"], ob[0]["issue"]), ("deferred", 9))
        self.assertIn({"name": "loop:deferred"}, self.gh.issues[2]["labels"])
        self.assertTrue(any("implement-loop:deferred" in c["body"] for c in self.gh.comments[2]))

    def test_a_blocked_build_asks_for_a_path_and_carries_on(self):
        self.add_work(2, "docs/a.txt", "alpha", blocked_once=True, extra_path="docs/registry.txt")
        self.epic(2)
        self.run_engine()
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertEqual(self.roles("decide"), {"codex"})
        self.assertTrue(any(g["path"] == "docs/registry.txt" for g in self.store.issue(2).grants))


class WaitAndFailTests(EngineCase):
    def test_an_outage_waits_and_the_next_run_resumes(self):
        self.add_work(2, "docs/a.txt", "alpha", outages=1)
        self.epic(2)
        self.run_engine()
        self.assertEqual(self.phase(2), Phase.WAITING)
        self.assertEqual(self.store.issue(2).wait["kind"], "outage")
        self.assertEqual(self.store.issue(2).infra, 0, "an outage is charged to no budget")
        self.run_engine(agents=self.agents)
        self.assertEqual(self.phase(2), Phase.DONE)

    def test_timeouts_spend_the_infrastructure_budget_then_fail(self):
        self.add_work(2, "docs/a.txt", "alpha", crashes=99)
        self.epic(2)
        self.run_engine(caps=Caps(ci_poll_s=0, queue_poll_s=0, infra_budget=3))
        self.assertEqual(self.phase(2), Phase.FAILED)
        self.assertEqual(self.store.issue(2).fail["cause"], "ceiling")
        self.assertEqual(self.store.issue(2).infra, 3)

    def test_a_failed_issue_resumes_once_on_a_new_engine_version(self):
        self.add_work(2, "docs/a.txt", "alpha", wrong_attempts=99)
        self.epic(2)
        self.run_engine()
        self.assertEqual(self.phase(2), Phase.FAILED)
        self.scripts[2].wrong_attempts = 0
        self.agents._built[2] = 99
        with mock.patch.object(engine_mod, "VERSION", "9.9.9"):
            self.run_engine(agents=self.agents)
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertTrue(self.events("revived", 2))

    def test_a_flaky_required_check_is_rerun_once(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        self.gh.check_script = ["failure", "success"]
        self.run_engine()
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertEqual(len(self.gh.reruns), 1)

    def test_a_check_with_no_verdict_waits(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        self.gh.check_script = [None, None]
        self.run_engine(caps=Caps(ci_poll_s=1, ci_timeout_s=1, queue_poll_s=0))
        self.assertEqual(self.phase(2), Phase.WAITING)
        self.assertEqual(self.store.issue(2).wait["kind"], "ci")

    def test_an_engine_fault_is_filed_once_and_its_issue_waits(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.add_work(3, "docs/b.txt", "beta")
        self.epic(2, 3)
        original = Engine._step_verify

        def broken(engine, n):
            if n == 2:
                raise KeyError("boom")
            return original(engine, n)
        with mock.patch.object(Engine, "_step_verify", broken):
            self.run_engine()
        self.assertEqual(self.phase(2), Phase.WAITING)
        self.assertEqual(self.store.issue(2).wait["kind"], "engine")
        self.assertEqual(self.phase(3), Phase.DONE)
        filed = [i for i in self.gh.issues.values() if {"name": "loop:engine-bug"} in i["labels"]]
        self.assertEqual(len(filed), 1)
        self.assertIn("## Deliverables", filed[0]["body"], "a fault issue carries a ledger a repair run can prove")

    def test_a_merge_queue_another_run_holds_is_polled_not_abandoned(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        claims = RepoClaims(self.repo.work)
        claims.acquire("merge-queue", "run-other")
        released = []

        def sleep(_):
            if not released:
                claims.release("merge-queue", "run-other")
                released.append(True)
        plan = build_plan(self.gh, EPIC, self.repo.work)
        store = RunStore.for_root(self.repo.work, EPIC)
        ws = Workspace(self.repo.work, EPIC, SHIP, base_dir=self.repo.loop_dir)
        self.agents = FakeAgents(self.scripts)
        Engine(plan, store, self.gh, ws, self.agents, Config(repo="t/t", caps=Caps(ci_poll_s=0, queue_poll_s=0)),
               repo_root=self.repo.work, log=lambda m: None, sleep=sleep, policy=self.policy).run()
        self.store = store
        self.assertEqual(self.phase(2), Phase.DONE)

    def test_an_issue_another_run_holds_waits(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        RepoClaims(self.repo.work).acquire("issue-2", "run-other")
        self.run_engine(caps=Caps(ci_poll_s=0, queue_poll_s=0, queue_wait_s=0))
        self.assertEqual(self.phase(2), Phase.WAITING)
        self.assertEqual(self.store.issue(2).wait["kind"], "claim")


class RequirementTests(EngineCase):
    def test_criteria_edited_before_landing_send_the_issue_back_to_plan(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        original = self.gh.get_issue
        edited = []

        def get_issue(n):
            data = original(n)
            if n == 2 and not edited and any(e["kind"] == "examined" for e in self.store_events()):
                edited.append(True)
                self.gh.issues[2]["body"] = self.gh.issues[2]["body"].replace("The test passes on main.",
                                                                             "The test passes on main, twice.")
                data = original(n)
            return data
        self.store_events = lambda: RunStore.for_root(self.repo.work, EPIC).events()
        with mock.patch.object(self.gh, "get_issue", get_issue):
            self.run_engine()
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertTrue(self.events("requirements_changed", 2))

    def test_a_legacy_parked_state_migrates_and_resumes(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        store = RunStore.for_root(self.repo.work, EPIC)
        store.state.setdefault("issues", {})["2"] = {
            "number": 2, "phase": "parked", "park_kind": "exhausted", "reason": "the design was impossible",
            "design": {"files": ["docs/a.txt"], "check_files": ["checks/old_2.sh"], "checks": []},
            "locked": {"checks/old_2.sh": "x"}}
        store.save()
        self.run_engine()
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertTrue(self.events("migrated", 2))


if __name__ == "__main__":
    unittest.main()
