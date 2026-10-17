"""Regression tests for the 19 defects Codex's review of the builder/examiner engine found
(ADR 0012). Each test is named after its finding: `test_<n>_...`."""

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

from helpers import HAS_PYTEST, SHIP, git, issue_body
from test_engine import EPIC, EngineCase

from implement_loop import VERSION, gate, verify
from implement_loop.agents import Decision, FakeAgents, Objection, Probe, Request, Ruling, Script
from implement_loop.config import Caps, Config
from implement_loop.engine import Engine
from implement_loop.graph import build_plan
from implement_loop.model import CheckSpec, Finding, IssueState, Phase
from implement_loop.state import RepoClaims, RunStore, runs_root
from implement_loop.supervisor import Supervisor
from implement_loop.workspace import Workspace


class Agents(FakeAgents):
    """FakeAgents whose answers a test adjusts: a hook gets the default answer and returns the one
    to give. Every examination request is recorded."""

    def __init__(self, scripts, **hooks):
        super().__init__(scripts)
        self.hooks = hooks
        self.exams: list[dict] = []

    def plan(self, vendor, req, worktree):
        result = super().plan(vendor, req, worktree)
        return self.hooks["plan"](result, req) if "plan" in self.hooks else result

    def triage(self, vendor, req, plan):
        result = super().triage(vendor, req, plan)
        return self.hooks["triage"](result, req) if "triage" in self.hooks else result

    def build(self, vendor, req, plan, worktree, feedback):
        k = self._built.get(req.issue.number, 0)
        result = super().build(vendor, req, plan, worktree, feedback)
        return self.hooks["build"](result, req, worktree, k) if "build" in self.hooks else result

    def examine(self, vendor, req, plan, worktree, base_sha, head_sha, evidence, memory, requests, since):
        self.exams.append({"issue": req.issue.number, "feedback": list(req.feedback), "head": head_sha,
                           "since": since, "plan": plan})
        result = super().examine(vendor, req, plan, worktree, base_sha, head_sha, evidence, memory, requests, since)
        return self.hooks["examine"](result, req, plan, since) if "examine" in self.hooks else result

    def decide(self, vendor, req, worktree, requests):
        if "decide" not in self.hooks:
            return super().decide(vendor, req, worktree, requests)
        self.calls.append(("decide", vendor, req.issue.number, tuple(r["id"] for r in requests)))
        return self._metered(req.issue.number, "decide", vendor, lambda: self.hooks["decide"](requests))


def with_zone(path):
    """A plan hook: the plan also claims `path`."""
    def hook(result, req):
        result.zones = sorted(set(result.zones) | {path})
        return result
    return hook


def is_revert(req) -> bool:
    return any("Certify a revert" in f for f in req.feedback)


class FixCase(EngineCase):
    def make_engine(self, agents=None, caps=None):
        plan = build_plan(self.gh, EPIC, self.repo.work)
        store = RunStore.for_root(self.repo.work, EPIC)
        ws = Workspace(self.repo.work, EPIC, SHIP, base_dir=self.repo.loop_dir)
        self.agents = agents or FakeAgents(self.scripts)
        return Engine(plan, store, self.gh, ws, self.agents, Config(repo="t/t", caps=caps or Caps(ci_poll_s=0, queue_poll_s=0)),
                      repo_root=self.repo.work, log=lambda m: None, sleep=lambda s: None, policy=self.policy)

    def store_dir(self) -> Path:
        return RunStore.for_root(self.repo.work, EPIC).dir

    def builds(self, n=2):
        return [c for c in self.agents.calls if c[0] == "build" and c[2] == n]

    def after(self, kind, seq, issue=None):
        return [e for e in self.events(kind, issue) if e["seq"] > seq]

    def last_seq(self):
        return max((e["seq"] for e in self.store.events()), default=0)

    def breaking_pair(self):
        """#3 breaks #2's checks on main; its fix-forward changes nothing, so it is reverted."""
        self.add_work(2, "docs/a.txt", "alpha")
        self.add_work(3, "docs/a.txt", "broken", blocked_by=(2,))
        self.epic(2, 3)

    def revert_prs(self):
        return [p for p in self.gh.prs.values() if p["head"]["ref"].endswith("-revert")]


class Finding01Credentials(unittest.TestCase):
    def test_1_check_commands_run_without_github_credentials(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        spec = CheckSpec("A1", command='echo "gh=${GH_TOKEN:-none} github=${GITHUB_TOKEN:-none} '
                                       'ssh=${SSH_AUTH_SOCK:-none} ghe=${GH_ENTERPRISE_TOKEN:-none}"; '
                                       'echo "helper=[$(git config --get credential.helper)] config=$GH_CONFIG_DIR"')
        secrets = {"GH_TOKEN": "ghp_engine_secret", "GITHUB_TOKEN": "ghs_engine_secret", "SSH_AUTH_SOCK": "/tmp/agent.sock"}
        with mock.patch.dict(os.environ, secrets):
            ev, _ = verify.run_check(root, spec, "abc123", root / ".work", extra_env={"GH_ENTERPRISE_TOKEN": "ghe_secret"})
        self.assertTrue(ev.passed, ev.output_tail)
        self.assertIn("gh=none github=none ssh=none ghe=none", ev.output_tail)
        self.assertIn("helper=[]", ev.output_tail)
        self.assertIn(f"config={(root / '.work').resolve()}", ev.output_tail.replace(str(root / ".work"), str((root / ".work").resolve())))
        for secret in ("ghp_engine_secret", "ghs_engine_secret", "ghe_secret"):
            self.assertNotIn(secret, ev.output_tail)


class Finding01PublishedEvidence(FixCase):
    def test_1_published_evidence_never_carries_the_engines_token(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)

        def echo_token(result, req, worktree, k):
            result.commands = [CheckSpec(c.criterion, command=c.command + ' && echo "token=${GH_TOKEN:-unset}"')
                               if c.criterion == "A1" else c for c in result.commands]
            return result
        with mock.patch.dict(os.environ, {"GH_TOKEN": "ghp_engine_secret"}):
            self.run_engine(agents=Agents(self.scripts, build=echo_token))
        self.assertEqual(self.phase(2), Phase.DONE)
        pr = self.store.issue(2).pr
        evidence = [c["body"] for c in self.gh.comments[pr] if "implement-loop:evidence" in c["body"]][0]
        self.assertIn("token=unset", evidence)
        published = json.dumps([self.gh.comments, self.gh.prs, self.gh.issues])
        self.assertNotIn("ghp_engine_secret", published)


class Finding02RevertGates(FixCase):
    def test_2_a_revert_is_verified_and_certified_on_its_exact_head_then_passes_the_required_check(self):
        self.breaking_pair()
        agents = Agents(self.scripts)
        self.run_engine(agents=agents)
        reverted = self.events("reverted", 3)
        self.assertTrue(reverted)
        pr = self.gh.prs[reverted[0]["pr"]]
        head = pr["head"]["sha"]
        self.assertTrue(pr["merged"])
        # the earlier issues' checks ran on the reverted tree, before it was certified and merged
        checked = [e for e in self.events("regression_check", 3) if e["head"] == head]
        self.assertTrue(checked and checked[0]["ok"] and checked[0]["of"] == 2)
        self.assertLess(checked[0]["seq"], reverted[0]["seq"])
        certified = [x for x in agents.exams if x["head"] == head]
        self.assertEqual(len(certified), 1, "the other vendor certified the exact revert head")
        self.assertTrue(any("Certify a revert" in f for f in certified[0]["feedback"]))
        self.assertIn(head, self.gh._check_seen, "the required check ran on it")
        self.assertIn(("merge_pr", pr["number"], head), self.gh.calls)

    def test_2_a_revert_waits_for_the_merge_queue_another_run_holds(self):
        self.breaking_pair()
        claims = RepoClaims(self.repo.work)
        real = Engine._revert
        held = []

        def another_run_lands_first(engine, n, feedback):
            if not held:
                held.append(claims.acquire("merge-queue", "run-other"))
            return real(engine, n, feedback)
        with mock.patch.object(Engine, "_revert", another_run_lands_first):
            self.run_engine(caps=Caps(ci_poll_s=0, queue_poll_s=0, queue_wait_s=0))
            st = self.store.issue(3)
            self.assertEqual((st.phase, st.wait["kind"], st.wait["resume"]), (Phase.WAITING, "merge_queue", "merged"))
            self.assertFalse(self.revert_prs(), "nothing is pushed or merged while another run lands")
            self.assertEqual(self.repo.main_file("docs/a.txt"), "broken")
            claims.release("merge-queue", "run-other")
            self.run_engine(agents=self.agents)
        self.assertTrue(self.events("reverted", 3))
        self.assertFalse(RepoClaims(self.repo.work).acquire("merge-queue", "run-other") is False)

    def test_2_a_refused_certificate_fails_the_issue_main_broken_and_merges_nothing(self):
        self.breaking_pair()

        def refuse_the_revert(result, req, plan, since):
            if is_revert(req):
                result.certify, result.summary = False, "the revert also drops unrelated work"
            return result
        self.run_engine(agents=Agents(self.scripts, examine=refuse_the_revert))
        st = self.store.issue(3)
        self.assertEqual((st.phase, st.fail["cause"]), (Phase.FAILED, "main_broken"))
        self.assertIn("did not certify the revert", st.fail["detail"])
        self.assertFalse(self.revert_prs())
        self.assertFalse(self.events("reverted", 3))
        self.assertEqual(len([c for c in self.gh.calls if c[0] == "merge_pr"]), 2, "only #2 and #3 ever merged")
        self.assertNotIn("-revert", git("ls-remote", "--heads", "origin", cwd=self.repo.work), "nothing was pushed")

    def test_2_a_revert_that_leaves_earlier_checks_failing_is_never_proposed(self):
        self.breaking_pair()
        real = Engine._regressions

        def still_failing_on_the_revert(engine, n, root, head):
            if Path(root).name != "coord":   # the revert's own worktree
                return [f"after #{n} was reverted, #2's checks still fail"]
            return real(engine, n, root, head)
        with mock.patch.object(Engine, "_regressions", still_failing_on_the_revert):
            self.run_engine(agents=Agents(self.scripts))
        st = self.store.issue(3)
        self.assertEqual((st.phase, st.fail["cause"]), (Phase.FAILED, "main_broken"))
        self.assertIn("still leaves earlier issues' checks failing", st.fail["detail"])
        self.assertFalse(self.revert_prs())
        self.assertFalse([x for x in self.agents.exams if any("Certify a revert" in f for f in x["feedback"])])

    def test_2_a_revert_the_required_check_refuses_is_not_merged(self):
        self.breaking_pair()
        real = self.gh.required_check_run

        def red_on_reverts(sha, name):
            if any(p["head"]["ref"].endswith("-revert") for p in self.gh.prs.values()):
                return {"id": 999, "status": "completed", "conclusion": "failure"}
            return real(sha, name)
        self.gh.required_check_run = red_on_reverts
        self.run_engine()
        st = self.store.issue(3)
        self.assertEqual((st.phase, st.fail["cause"]), (Phase.FAILED, "main_broken"))
        self.assertIn("did not pass the required check", st.fail["detail"])
        self.assertEqual(len(self.revert_prs()), 1)
        self.assertFalse(self.revert_prs()[0]["merged"])


class Finding03DeltaAfterAdoption(FixCase):
    def test_3_adopted_probes_make_a_new_head_that_a_delta_examination_certifies(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        certified = []
        real = Engine._set_phase

        def watch(engine, n, phase, **changes):
            result = real(engine, n, phase, **changes)
            sha = engine.store.issue(n).certified_sha
            if sha and sha not in certified:
                certified.append(sha)
            return result
        with mock.patch.object(Engine, "_set_phase", watch):
            self.run_engine()
        self.assertEqual(self.phase(2), Phase.DONE)
        examined = self.events("examined", 2)
        self.assertEqual([bool(e["adopted"]) for e in examined], [True, False])
        locked = self.events("tests_locked", 2)[0]["sha"]
        self.assertEqual(examined[1]["head"], locked, "the head adopting the probes made was examined itself")
        self.assertEqual([c[3] for c in self.agents.calls if c[0] == "examine"], [False, True], "a delta examination")
        self.assertTrue(certified)
        self.assertTrue(set(certified) <= {e["head"] for e in examined}, "certified_sha only ever equals an examined head")
        self.assertEqual(self.events("merged", 2)[0]["head"], locked)


class Finding04TestsOutsideZones(FixCase):
    def test_4_a_test_the_builder_lists_outside_its_zones_is_a_zone_problem(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        stray = "elsewhere/check_2.sh"

        def list_a_stray_test(result, req, worktree, k):
            if k == 0:
                (worktree / "elsewhere").mkdir(exist_ok=True)
                (worktree / stray).write_text("#!/usr/bin/env bash\ntrue\n")
                result.tests = result.tests + [stray]
            elif (worktree / stray).exists():
                (worktree / stray).unlink()   # the builder takes it back after the zone problem
            return result
        self.run_engine(agents=Agents(self.scripts, build=list_a_stray_test))
        first = self.events("verified", 2)[0]
        self.assertFalse(first["ok"])
        self.assertTrue(any("outside the plan's zones" in p and stray in p for p in first["problems"]), first["problems"])
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertIsNone(self.repo.main_file(stray))


class Finding05UnlistedCommandTests(FixCase):
    def test_5_a_test_a_command_runs_is_locked_even_when_the_builder_does_not_list_it(self):
        extra = "checks/extra_2.sh"
        self.add_work(2, "docs/a.txt", "alpha", findings=1)
        self.epic(2)

        def run_an_unlisted_test(result, req, worktree, k):
            (worktree / extra).write_text("#!/usr/bin/env bash\ntest -s docs/a.txt\n"
                                          if k == 0 else "#!/usr/bin/env bash\nexit 0\n")   # then it weakens it
            result.commands = [CheckSpec(c.criterion, command=c.command + f" && bash {extra}") for c in result.commands]
            self.assertNotIn(extra, result.tests)
            return result
        self.run_engine(agents=Agents(self.scripts, plan=with_zone(extra), build=run_an_unlisted_test))
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertIn(extra, self.events("tests_locked", 2)[0]["locked"])
        self.assertIn(extra, self.store.issue(2).tests)
        self.assertIn(f"Loop-Locks: {extra}", git("log", "--format=%B", "origin/feat/issue-2", cwd=self.repo.work))
        self.assertTrue(any(extra in e["files"] for e in self.events("locked_changes_reverted", 2)))
        self.assertIn("test -s docs/a.txt", self.repo.main_file(extra), "the weakened test never landed")


class Finding06CommandCwd(FixCase):
    def test_6_changing_a_locked_commands_cwd_is_a_request_the_other_vendor_decides(self):
        self.add_work(2, "docs/a.txt", "alpha", findings=1)
        self.epic(2)

        def move_the_command(result, req, worktree, k):
            if k >= 1:   # after the first examination locked the command
                result.commands = [CheckSpec(c.criterion, command=c.command, cwd="docs") if c.criterion == "D1" else c
                                   for c in result.commands]
            return result
        agents = Agents(self.scripts, build=move_the_command,
                        decide=lambda requests: [Decision(r["id"], False, "the test reads repo-relative paths")
                                                 for r in requests])
        self.run_engine(agents=agents)
        self.assertEqual(self.phase(2), Phase.DONE)
        st = self.store.issue(2)
        change = [r for r in st.requests if r["kind"] == "command_change"]
        self.assertEqual(len(change), 1)
        self.assertEqual((change[0]["item"], change[0]["commands"][0]["cwd"], change[0]["status"]), ("D1", "docs", "refused"))
        self.assertIn(change[0]["id"], [i for c in agents.calls if c[0] == "decide" for i in c[3]])
        d1 = [c for c in st.commands if c["criterion"] == "D1" and c.get("author") == "builder"]
        self.assertEqual([c["cwd"] for c in d1], ["."], "the locked command kept its directory")


class Finding07InRunPrerequisite(FixCase):
    def test_7_a_deferred_item_with_an_in_run_prerequisite_is_proven_after_it_lands(self):
        self.gh.add_issue(3, "Prerequisite widget", issue_body("feat/issue-3", ["`docs/b.txt` contains `beta`."],
                                                                ["The test passes on main."]), labels=("size:M",))
        self.scripts[3] = Script(files={"docs/b.txt": "beta"})
        self.add_work(2, "docs/a.txt", "alpha", items=["`docs/a.txt` contains `alpha`.",
                                                        "It plays in the prerequisite widget."], deferred=(("D2", 3),))
        self.epic(2, 3)
        self.run_engine()
        self.assertEqual((self.phase(2), self.phase(3)), (Phase.DONE, Phase.DONE))
        st = self.store.issue(2)
        d2 = next(i for i in st.plan["items"] if i["id"] == "D2")
        self.assertEqual((d2["proof"], d2["depends_on"]), ("review", 3))
        self.assertEqual(st.verdicts["D2"]["verdict"], "met", "proven by the examiner, not closed unproven")
        self.assertFalse([o for o in st.obligations if o["kind"] == "deferred"])
        self.assertIn("- [x] It plays in the prerequisite widget.", self.gh.issues[2]["body"])
        three_done = min(e["seq"] for e in self.events("phase", 3) if e["to"] == "done")
        self.assertLess(three_done, min(e["seq"] for e in self.events("phase", 2) if e["to"] == "build"))


class Finding08TriageDependency(FixCase):
    def test_8_a_triage_dependency_outside_the_run_leaves_the_item_deferred_in_the_final_plan(self):
        self.gh.add_issue(9, "Prerequisite widget", "The Prerequisite widget the demo plays in.\n")
        self.add_work(2, "docs/a.txt", "alpha", items=["`docs/a.txt` contains `alpha`.", "It plays in the widget."])
        self.epic(2)
        objection = Objection("dependency", "D2 plays in #9's widget, which no blocked-by link declares", item="D2",
                              quote="plays in the widget", depends_on=9, depends_quote="Prerequisite widget")
        self.run_engine(agents=Agents(self.scripts, triage=lambda result, req: [objection]))
        st = self.store.issue(2)
        d2 = next(i for i in st.plan["items"] if i["id"] == "D2")
        self.assertEqual((d2["proof"], d2["depends_on"]), ("deferred", 9))
        self.assertEqual(self.events("planned", 2)[0]["items"]["D2"], "deferred")
        self.assertEqual([(o["kind"], o["issue"]) for o in st.obligations], [("deferred", 9)])
        self.assertEqual(self.phase(2), Phase.DELIVERED)
        self.assertIn("- [ ] It plays in the widget.", self.gh.issues[2]["body"])


class Finding09MidBuildDependency(FixCase):
    def test_9_an_approved_mid_build_dependency_waits_and_survives_a_restart(self):
        self.gh.add_issue(3, "Prerequisite widget", issue_body("feat/issue-3", ["`docs/b.txt` contains `beta`."],
                                                                ["The test passes on main."]), labels=("size:M",))
        self.scripts[3] = Script(files={"docs/b.txt": "beta"}, wrong_attempts=1)   # still in flight when #2 asks
        self.add_work(2, "docs/a.txt", "alpha", items=["`docs/a.txt` contains `alpha`.",
                                                        "It plays in the prerequisite widget."])
        self.epic(2, 3)

        def ask_for_the_prerequisite(result, req, worktree, k):
            if req.issue.number == 2 and k == 0:
                result.requests = [Request("depends", "D2 needs #3's widget", item="D2", depends_on=3,
                                           depends_quote="Prerequisite widget")]
            return result
        agents = Agents(self.scripts, build=ask_for_the_prerequisite)
        real = Engine._step_build

        def stop_once_it_waits(engine, n):
            real(engine, n)
            if n == 2 and engine.store.issue(2).phase == Phase.PENDING:
                (engine.store.dir / "STOP").write_text("stop\n")
        with mock.patch.object(Engine, "_step_build", stop_once_it_waits):
            self.run_engine(agents=agents)
        st = self.store.issue(2)
        self.assertEqual((st.phase, st.extra_deps), (Phase.PENDING, [3]))
        self.assertTrue(self.events("waits_for_prerequisite", 2))
        self.assertNotIn(self.phase(3), (Phase.DONE, Phase.DELIVERED), "the fixture stops before #3 lands")
        (self.store_dir() / "STOP").unlink()

        restart = self.last_seq()
        self.run_engine(agents=agents)   # a fresh plan: the edge comes back from the state
        self.assertIn(3, self.engine.plan.deps[2])
        self.assertEqual((self.phase(2), self.phase(3)), (Phase.DONE, Phase.DONE))
        three_done = min(e["seq"] for e in self.after("phase", restart, 3) if e["to"] == "done")
        two_builds = [e["seq"] for e in self.after("phase", restart, 2) if e["to"] == "build"]
        self.assertTrue(two_builds)
        self.assertLess(three_done, min(two_builds), "#2 builds again only once #3 is delivered")


class Finding10OwnerAgentPart(FixCase):
    def owner_issue(self, **script):
        self.add_work(2, "docs/a.txt", "alpha", items=["`docs/a.txt` contains `alpha`.",
                                                        "Runs under a second on a 2020 laptop."],
                      owner_items=("D2",), **script)
        self.epic(2)

    def test_10_an_owner_items_agent_part_blocks_until_a_met_verdict(self):
        self.owner_issue(unmet_review=1)
        self.run_engine()
        self.assertEqual(self.events("examined", 2)[0]["unmet"], ["D2"])
        st = self.store.issue(2)
        self.assertEqual(st.verdicts["D2"]["verdict"], "met")
        self.assertEqual(self.phase(2), Phase.DELIVERED)
        self.assertIn("- [ ] Runs under a second", self.gh.issues[2]["body"], "an owner item is never ticked")

    def test_10_without_a_verdict_or_a_command_the_owner_item_is_never_delivered(self):
        self.owner_issue()

        def no_verdict_on_d2(result, req, plan, since):
            result.verdicts = [v for v in result.verdicts if v["item"] != "D2"]
            return result
        self.run_engine(agents=Agents(self.scripts, examine=no_verdict_on_d2))
        self.assertNotIn(self.phase(2), (Phase.DELIVERED, Phase.DONE))
        self.assertFalse(self.gh.prs)
        self.assertTrue(self.events("examination_incomplete", 2))
        self.assertTrue(any("no verdict on D2" in p for e in self.events("round_failed", 2) for p in e["problems"]))

    def test_10_a_command_proves_the_agent_part_without_a_verdict(self):
        self.owner_issue()

        def prove_d2(result, req, worktree, k):
            result.commands = result.commands + [CheckSpec("D2", command="bash checks/issue_2.sh")]
            return result

        def no_verdict_on_d2(result, req, plan, since):
            result.verdicts = [v for v in result.verdicts if v["item"] != "D2"]
            return result
        self.run_engine(agents=Agents(self.scripts, build=prove_d2, examine=no_verdict_on_d2))
        self.assertEqual(self.phase(2), Phase.DELIVERED)
        self.assertFalse(self.events("examination_incomplete", 2))
        self.assertTrue(any(e["criterion"] == "D2" and e["passed"] for e in self.store.issue(2).evidence))


class Finding11EarlyConftest(FixCase):
    def test_11_a_conftest_added_before_the_first_examination_is_not_new_test_configuration(self):
        conftest = "checks/conftest.py"
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)

        def add_a_conftest(result, req, worktree, k):
            (worktree / conftest).write_text("# shared fixtures\n")
            return result
        self.run_engine(agents=Agents(self.scripts, plan=with_zone(conftest), build=add_a_conftest))
        problems = [p for e in self.events("verified", 2) for p in e["problems"]]
        self.assertFalse([p for p in problems if "new test configuration" in p], problems)
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertIn(conftest, self.store.issue(2).locked, "it locks with the tests at the first examination")


def python_test_builder(path, versions, request_at=None):
    """A build hook writing `path` with the test functions `versions[k]` (the last one after
    that), run by A1's command; at round `request_at` it asks to change the locked file."""
    def hook(result, req, worktree, k):
        names = versions[min(k, len(versions) - 1)]
        (worktree / path).parent.mkdir(parents=True, exist_ok=True)
        (worktree / path).write_text("".join(f"def {name}():\n    assert open('docs/a.txt').read().strip() == 'alpha'\n\n"
                                             for name in names))
        result.tests = result.tests + [path]
        result.commands = [CheckSpec("A1", command=f"{sys.executable} -m pytest -q -p no:cacheprovider {path}")
                           if c.criterion == "A1" else c for c in result.commands]
        if k == request_at:
            result.requests = [Request("test_change", "the item needs this change to the locked test", paths=[path])]
        return result
    return hook


@unittest.skipUnless(HAS_PYTEST, "pytest is needed for the verifier's per-test accounting")
class Finding12And15Manifest(FixCase):
    def test_12_the_manifest_grows_with_tests_that_ran_in_locked_files(self):
        path = "tests/test_grow_2.py"
        self.add_work(2, "docs/a.txt", "alpha", findings=1)
        self.epic(2)
        hook = python_test_builder(path, [["test_one"], ["test_one", "test_two"]], request_at=1)
        self.run_engine(agents=Agents(self.scripts, plan=with_zone(path), build=hook))
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertEqual(self.events("locked_tests_changed", 2)[0]["files"], [path])
        manifest = self.store.issue(2).manifest
        self.assertIn(f"{path}::test_one", manifest["*"])
        self.assertIn(f"{path}::test_two", manifest["*"], "a test that ran in a locked file must keep running")

    def test_15_an_approved_test_change_with_a_disposition_retires_that_test_from_the_manifest(self):
        path = "tests/test_retire_2.py"
        self.add_work(2, "docs/a.txt", "alpha", findings=1)
        self.epic(2)
        hook = python_test_builder(path, [["test_one", "test_two"], ["test_one"]], request_at=1)
        retired = f"{path}::test_two"
        agents = Agents(self.scripts, plan=with_zone(path), build=hook, decide=lambda requests: [
            Decision(r["id"], True, "the item no longer asks for it", dispositions={retired: "excluded: no longer asked"})
            for r in requests])
        self.run_engine(agents=agents)
        self.assertEqual(self.phase(2), Phase.DONE, self.events("round_failed", 2))
        st = self.store.issue(2)
        self.assertNotIn(retired, [i for ids in st.manifest.values() for i in ids])
        self.assertIn(f"{path}::test_one", st.manifest["*"])
        self.assertEqual(st.dispositions[retired], "excluded: no longer asked")
        self.assertFalse([p for e in self.events("verified", 2) for p in e["problems"] if "did not run" in p])


class Finding13ProbeCoverage(FixCase):
    def test_13_missing_probes_are_asked_twice_then_an_arbiter_waiver_is_a_recorded_decision(self):
        self.add_work(2, "docs/a.txt", "alpha", probe="none")
        self.epic(2)
        agents = Agents(self.scripts)
        self.run_engine(agents=agents)
        self.assertEqual(self.phase(2), Phase.DONE)
        incomplete = self.events("examination_incomplete", 2)
        self.assertEqual([(e["retry"], e["unprobed"]) for e in incomplete], [(1, ["A1", "D1"]), (2, ["A1", "D1"])])
        asked = [x for x in agents.exams if any("write an independent probe for A1, D1" in f for f in x["feedback"])]
        self.assertEqual(len(asked), 2)
        self.assertEqual([c[3] for c in agents.calls if c[0] == "arbitrate"], ["probe_waiver"])
        st = self.store.issue(2)
        waiver = [d for d in st.decisions if d["id"] == "probe-waiver"]
        self.assertEqual(len(waiver), 1)
        self.assertIn("A1, D1", waiver[0]["choice"])
        self.assertIn("probe-waiver", self.gh.prs[st.pr]["body"])
        self.assertEqual(len(self.builds()), 1, "the examiner's gap is not the builder's failure")

    def test_13_a_refused_waiver_sends_the_builder_back_to_strengthen_its_tests(self):
        self.add_work(2, "docs/a.txt", "alpha", probe="none")
        self.epic(2)
        agents = Agents(self.scripts)
        rulings = []

        def refuse_once(vendor, req, dispute, worktree=None):
            rulings.append(dispute["kind"])
            upheld = len(rulings) > 1
            return agents._metered(req.issue.number, "arbitrate", vendor,
                                   lambda: Ruling(upheld, "the test reads the file as the item asks" if upheld
                                                  else "the test never checks the content the item names"))
        agents.arbitrate = refuse_once
        self.run_engine(agents=agents)
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertEqual(rulings, ["probe_waiver", "probe_waiver"])
        failed = self.events("round_failed", 2)
        self.assertTrue(any("arbiter judges your tests do not prove them" in p for p in failed[0]["problems"]))
        self.assertTrue(any("arbiter judges" in f for f in self.builds()[1][3]), "the builder is told why")

    def test_13_a_probe_given_on_the_second_ask_is_adopted_and_certified(self):
        self.add_work(2, "docs/a.txt", "alpha", probe="none")
        self.epic(2)

        def probe_when_asked(result, req, plan, since):
            if any("independent probe" in f for f in req.feedback):
                body = "#!/usr/bin/env bash\nset -e\ntest -s docs/a.txt\n"
                result.probes = [Probe(f"checks/probe_2_{i}.sh", i, f"bash checks/probe_2_{i}.sh", content=body)
                                 for i in ("A1", "D1")]
            return result
        agents = Agents(self.scripts, examine=probe_when_asked)
        self.run_engine(agents=agents)
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertEqual(len(self.events("examination_incomplete", 2)), 1)
        st = self.store.issue(2)
        self.assertEqual(st.probes, ["checks/probe_2_A1.sh", "checks/probe_2_D1.sh"])
        self.assertFalse([d for d in st.decisions if d["id"] == "examination-gaps"])
        self.assertIn(st.certified_sha, [e["head"] for e in self.events("examined", 2)])


class Finding14Budget(FixCase):
    def test_14_a_stale_state_copy_written_after_metered_calls_keeps_the_charges(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        engine = self.make_engine()
        stale = engine.store.issue(2)
        engine.before(2, "build", "claude")
        engine.after(2, "build", "claude", "answered")
        engine.before(2, "build", "claude")
        engine.after(2, "build", "claude", "timeout")
        engine.store.put(stale)   # a step writes back the copy it read before the calls
        b = engine.store.budget(2)
        self.assertEqual((b["calls"], b["infra"], b["pending"]), (1, 1, 0))

    def test_14_every_answered_call_of_a_run_is_charged(self):
        self.add_work(2, "docs/a.txt", "alpha", findings=1, blocked_once=True, extra_path="docs/registry.txt")
        self.epic(2)
        self.run_engine()
        self.assertEqual(self.phase(2), Phase.DONE)
        answered = [c for c in self.agents.calls if c[0] != "explore" and c[2] == 2]
        b = self.store.budget(2)
        self.assertEqual(b["calls"], len(answered))
        self.assertEqual(len([e for e in self.events("agent_attempt", 2) if e["outcome"] == "answered"]), len(answered))
        self.assertEqual(self.store.issue(2).calls, b["calls"], "the state mirrors the budget for reports")


class Finding16DeferredReopening(FixCase):
    def deferred_issue(self, prerequisite=9):
        if prerequisite == 9:
            self.gh.add_issue(9, "Prerequisite widget", "The Prerequisite widget the demo plays in.\n")
        self.add_work(2, "docs/a.txt", "alpha", items=["`docs/a.txt` contains `alpha`.", "It plays in the widget."],
                      deferred=(("D2", prerequisite),))
        self.epic(2)

    def test_16_a_deferred_item_reopens_when_its_issue_is_closed_as_completed(self):
        self.deferred_issue()
        self.run_engine()
        self.assertEqual(self.phase(2), Phase.DELIVERED)
        self.gh.issues[9].update(state="closed", state_reason="completed")
        self.run_engine(agents=self.agents)
        self.assertEqual(self.events("deferred_reopened", 2)[0]["items"], ["D2"])
        self.run_engine(agents=self.agents)
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertIn("- [x] It plays in the widget.", self.gh.issues[2]["body"])

    def test_16_a_deferred_item_reopens_when_its_issue_is_delivered_in_the_run(self):
        self.gh.add_issue(3, "Prerequisite widget", issue_body(
            "feat/issue-3", ["`docs/b.txt` contains `beta`.", "Runs under a second on a 2020 laptop."],
            ["The test passes on main."]), labels=("size:M",))
        self.scripts[3] = Script(files={"docs/b.txt": "beta"}, owner_items=("D2",))
        self.deferred_issue(prerequisite=3)
        self.run_engine()
        self.assertEqual(self.phase(2), Phase.DELIVERED)
        self.gh.subs[EPIC].append(3)   # the prerequisite joins the epic, and is delivered in the next run
        seq = self.last_seq()
        self.run_engine(agents=self.agents)
        self.assertEqual(self.phase(3), Phase.DELIVERED)
        self.assertEqual(self.gh.issues[3]["state"], "open", "delivered, not closed: an owner item remains")
        self.assertEqual(self.after("deferred_reopened", seq, 2)[0]["items"], ["D2"])

    def test_16_a_deferred_item_whose_issue_is_closed_as_not_planned_is_unresolved_not_reopened(self):
        self.deferred_issue()
        self.run_engine()
        self.gh.issues[9].update(state="closed", state_reason="not_planned")
        self.run_engine(agents=self.agents)
        self.run_engine(agents=self.agents)
        self.assertEqual(self.phase(2), Phase.DELIVERED)
        self.assertFalse(self.events("deferred_reopened", 2))
        self.assertEqual(len(self.events("deferred_unresolved", 2)), 1, "reported once")
        ob = self.store.issue(2).obligations[0]
        self.assertEqual((ob["item"], ob["kind"], ob.get("unresolved")), ("D2", "deferred", True))
        self.assertIn("- [ ] It plays in the widget.", self.gh.issues[2]["body"])
        sup = Supervisor(self.repo.work, EPIC, "claude", run=lambda args: 0, log=lambda m: None)
        self.assertTrue(sup._all_settled(RunStore.for_root(self.repo.work, EPIC)), "nothing left to wait for")


class SupervisorCase(unittest.TestCase):
    def setUp(self):
        from helpers import TempRepo
        self.repo = TempRepo()
        self.addCleanup(self.repo.cleanup)
        self.calls: list[list[str]] = []

    def put(self, n, phase, **fields):
        RunStore.for_root(self.repo.work, EPIC).put(IssueState(number=n, phase=phase, **fields))

    def fault(self, fingerprint="abc123", filed=77):
        path = runs_root(self.repo.work) / "faults.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({fingerprint: {"filed": filed, "runs": [EPIC], "count": 1, "issues": [2]}}))

    def sup(self, script, **kw):
        def run(args):
            self.calls.append(args)
            script(args)
            return 0
        kw.setdefault("clock", lambda: 0.0)
        return Supervisor(self.repo.work, EPIC, "claude", run=run, reachable=lambda v: True,
                          pull=lambda: "main checkout updated", sleep=lambda s: None, log=lambda m: None, **kw)


class Finding17RepairBeforeSettling(SupervisorCase):
    def test_17_a_fault_filed_by_the_last_run_is_repaired_before_the_supervision_settles(self):
        self.put(2, Phase.PENDING)

        def script(args):
            if "--repair" not in args and not any("--repair" in c for c in self.calls):
                # the root run fails its issue for good on this version, and files a loop fault
                self.put(2, Phase.FAILED, fail={"cause": "no_progress", "version": VERSION})
                self.fault()
        out = self.sup(script).supervise()
        self.assertTrue(out.finished)
        self.assertEqual(self.calls[0], ["run", str(EPIC), "--operator", "claude", "--yes"])
        self.assertEqual(self.calls[1], ["run", "77", "--operator", "claude", "--yes", "--repair"])
        self.assertEqual(out.repairs, ["abc123"])


class Finding18RunBound(SupervisorCase):
    def test_18_a_repair_that_uses_the_last_run_means_no_root_run(self):
        self.put(2, Phase.WAITING, wait={"kind": "engine", "resume": "build", "version": "0.0.1"})
        self.fault()
        out = self.sup(lambda args: None, max_runs=1).supervise()
        self.assertEqual(self.calls, [["run", "77", "--operator", "claude", "--yes", "--repair"]])
        self.assertEqual(out.runs, 1)
        self.assertFalse(out.finished)
        self.assertIn("stopped after 1 runs", out.reason)

    def test_18_no_run_starts_once_the_time_bound_is_spent(self):
        self.put(2, Phase.WAITING, wait={"kind": "engine", "resume": "build", "version": "0.0.1"})
        self.fault()
        now = [0.0]

        def slow_repair(args):
            now[0] += 3 * 3600   # the repair outlasts the whole supervision
        out = self.sup(slow_repair, max_hours=2, clock=lambda: now[0]).supervise()
        self.assertEqual([c for c in self.calls if "--repair" not in c], [], "no root run past the deadline")
        self.assertFalse(out.finished)
        self.assertIn("hours", out.reason)


class Finding19InterruptedAttempts(FixCase):
    def test_19_an_attempt_journaled_but_never_reported_is_charged_when_the_next_run_starts(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        killed = self.make_engine()
        killed.before(2, "build", "claude")   # the process dies during this call: no `after`
        self.assertEqual(killed.store.budget(2)["pending"], 1)
        self.run_engine()
        charged = self.events("interrupted_attempts_charged", 2)
        self.assertEqual([e["count"] for e in charged], [1])
        b = self.store.budget(2)
        self.assertEqual((b["infra"], b["pending"]), (1, 0))
        self.assertEqual(self.phase(2), Phase.DONE)


class Finding02RevertFindings(FixCase):
    """The revert's examination is classified like any other: an invariant finding its reproduction
    (or its probe) reproduces on the revert head refuses it."""

    def revert_with(self, findings, probes=()):
        self.breaking_pair()

        def report(result, req, plan, since):
            if is_revert(req):
                result.findings, result.probes = list(findings), list(probes)
            return result
        self.run_engine(agents=Agents(self.scripts, examine=report))
        return self.store.issue(3)

    def test_2_a_reproduced_invariant_finding_refuses_the_revert(self):
        st = self.revert_with([Finding(id="", title="the revert drops the owner's notes", invariant="data loss",
                                       observed="docs/notes.txt is gone", expected="a revert keeps work it did not bring",
                                       reproduction="test -f docs/notes.txt")])
        self.assertEqual((st.phase, st.fail["cause"]), (Phase.FAILED, "main_broken"))
        self.assertIn("the revert drops the owner's notes", st.fail["detail"])
        self.assertFalse(self.revert_prs())

    def test_2_a_finding_its_returned_probe_reproduces_refuses_the_revert(self):
        probe = Probe("checks/revert_probe.sh", "", "bash checks/revert_probe.sh",
                      content='#!/usr/bin/env bash\ntest "$(cat docs/a.txt)" = beta\n')
        st = self.revert_with([Finding(id="", title="the revert restores a stale value", probe=probe.file,
                                       invariant="wrong results presented as correct", observed="alpha",
                                       expected="beta")], [probe])
        self.assertEqual((st.phase, st.fail["cause"]), (Phase.FAILED, "main_broken"))
        self.assertIn("the revert restores a stale value", st.fail["detail"])
        self.assertFalse(self.revert_prs())

    def test_2_findings_that_do_not_reproduce_or_name_no_invariant_let_the_revert_land(self):
        self.revert_with([
            Finding(id="", title="it might lose data", invariant="data loss", observed="o", expected="e",
                    reproduction="test -f README.md"),                     # passes on the revert head
            Finding(id="", title="a nicer revert message", observed="terse", expected="friendlier",
                    reproduction="test -f docs/friendlier.txt")])          # reproduced, but no invariant
        self.assertTrue(self.events("reverted", 3))
        self.assertTrue(self.revert_prs()[0]["merged"])


class Finding05LateLock(FixCase):
    def test_5_a_test_file_first_run_after_the_first_examination_locks_at_that_verify(self):
        late = ["checks/late_2a.sh", "checks/late_2b.sh"]
        self.add_work(2, "docs/a.txt", "alpha", findings=1)
        self.epic(2)

        def zones(result, req):
            result.zones = sorted(set(result.zones) | set(late))
            return result

        def add_late_tests(result, req, worktree, k):
            if k >= 1:   # after the first examination: new test files, run through a glob
                for f in late:
                    (worktree / f).write_text("#!/usr/bin/env bash\ntest -s docs/a.txt\n")
                result.commands = [CheckSpec(c.criterion, command=c.command + " && ls checks/late_2*.sh | xargs -n1 bash")
                                   if c.criterion == "D1" else c for c in result.commands]
            return result
        self.run_engine(agents=Agents(self.scripts, plan=zones, build=add_late_tests))
        self.assertEqual(self.phase(2), Phase.DONE)
        locked = [e for e in self.events("tests_locked", 2) if e.get("late")]
        self.assertEqual([e["locked"] for e in locked], [late])
        reverified = [e for e in self.events("verified", 2) if e["seq"] > locked[0]["seq"]][0]
        self.assertTrue(reverified["ok"])
        self.assertTrue(git("log", "-1", "--format=%s", reverified["head"], cwd=self.repo.work)
                        .startswith("Lock newly run tests for #2"), "the new head is verified again")
        self.assertTrue(set(late) <= set(self.store.issue(2).locked))
        bodies = git("log", "--format=%B", "origin/feat/issue-2", cwd=self.repo.work)
        self.assertIn("Lock newly run tests for #2", bodies)
        for f in late:
            self.assertIn(f"Loop-Locks: {f}", bodies)


@unittest.skipUnless(HAS_PYTEST, "pytest is needed for the verifier's per-test accounting")
class Finding12ManifestFromEmpty(FixCase):
    def test_12_an_empty_manifest_grows_with_a_python_test_first_run_later(self):
        path = "tests/test_late_2.py"
        self.add_work(2, "docs/a.txt", "alpha", findings=1)
        self.epic(2)
        engine = []

        def add_a_python_test(result, req, worktree, k):
            if k >= 1:
                (worktree / "tests").mkdir(exist_ok=True)
                (worktree / path).write_text("def test_late():\n    assert open('docs/a.txt').read().strip() == 'alpha'\n")
                result.tests = result.tests + [path]
                result.commands = [CheckSpec("A1", command=f"{sys.executable} -m pytest -q -p no:cacheprovider {path}")
                                   if c.criterion == "A1" else c for c in result.commands]
                st = self.engine.store.issue(2)
                st.manifest = {}   # as an earlier engine left it: nothing selected yet
                self.engine.store.put(st)
            return result
        self.run_engine(agents=Agents(self.scripts, plan=with_zone(path), build=add_a_python_test))
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertTrue([e for e in self.events("tests_locked", 2) if e.get("late") and path in e["locked"]])
        self.assertIn(f"{path}::test_late", self.store.issue(2).manifest.get("*", []))


@unittest.skipUnless(HAS_PYTEST, "pytest is needed for the verifier's per-test accounting")
class Fault90SeveralCommandsPerItem(FixCase):
    """#41 (engine 1.0.0) gave four commands for one item; only the last was kept, so the tests
    only the first selected never ran and every round failed the same way (no_progress)."""
    path = "tests/test_several_2.py"

    def builder(self, later=""):
        def hook(result, req, worktree, k):
            (worktree / "tests").mkdir(exist_ok=True)
            (worktree / self.path).write_text("def test_only_the_first_selects():\n"
                                              "    assert open('docs/a.txt').read().strip() == 'alpha'\n")
            result.tests = result.tests + [self.path]
            bash = next(c.command for c in result.commands if c.criterion == "A1")
            result.commands = [c for c in result.commands if c.criterion != "A1"] + [
                CheckSpec("A1", command=f"{sys.executable} -m pytest -q -p no:cacheprovider {self.path}"),
                CheckSpec("A1", command=bash + (later if k >= 1 else ""))]
            return result
        return hook

    def a1(self):
        return [c["command"] for c in self.store.issue(2).commands if c["criterion"] == "A1" and c.get("author") == "builder"]

    def test_fault_90_every_command_for_an_item_is_kept_and_run(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        self.run_engine(agents=Agents(self.scripts, plan=with_zone(self.path), build=self.builder()))
        self.assertEqual(self.phase(2), Phase.DONE, self.events("round_failed", 2))
        self.assertEqual(len(self.a1()), 2)
        self.assertFalse([p for e in self.events("verified", 2) for p in e["problems"] if "no command selects" in p])

    def test_fault_90_a_changed_list_for_a_locked_item_is_one_request_applied_whole(self):
        self.add_work(2, "docs/a.txt", "alpha", findings=1)
        self.epic(2)
        agents = Agents(self.scripts, plan=with_zone(self.path), build=self.builder(later=" && true"),
                        decide=lambda requests: [Decision(r["id"], True, "same proof") for r in requests])
        self.run_engine(agents=agents)
        self.assertEqual(self.phase(2), Phase.DONE, self.events("round_failed", 2))
        change = [r for r in self.store.issue(2).requests if r["kind"] == "command_change"]
        self.assertEqual([(r["item"], len(r["commands"]), r["status"]) for r in change], [("A1", 2, "approved")])
        self.assertEqual(len(self.a1()), 2)
        self.assertTrue(self.a1()[1].endswith(" && true"))

    def test_fault_90_the_engine_version_moved_past_the_faulted_one(self):
        self.assertNotEqual(VERSION, "1.0.0")


@unittest.skipUnless(HAS_PYTEST, "pytest is needed for the verifier's per-test accounting")
class Fault94CriterionNamesTheItem(FixCase):
    """#24 (engine 1.0.0) gave its probe commands criteria like "D2, D3, A1: the examiner's probes";
    each was dropped in silence, so their tests never ran and every round failed the same way."""
    path = "tests/test_criterion_2.py"

    def builder(self, extra=()):
        def hook(result, req, worktree, k):
            (worktree / "tests").mkdir(exist_ok=True)
            (worktree / self.path).write_text("def test_alpha():\n    assert open('docs/a.txt').read().strip() == 'alpha'\n")
            result.tests = result.tests + [self.path]
            result.commands = [CheckSpec(f"{c.criterion}, D1: the builder's check", command=c.command)
                               for c in result.commands] + [
                CheckSpec("A1: the builder's own pytest file",
                          command=f"{sys.executable} -m pytest -q -p no:cacheprovider {self.path}")] + list(extra)
            return result
        return hook

    def test_fault_94_a_criterion_leading_with_an_item_id_is_kept_and_run(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        self.run_engine(agents=Agents(self.scripts, plan=with_zone(self.path), build=self.builder()))
        self.assertEqual(self.phase(2), Phase.DONE, self.events("round_failed", 2))
        builder = [c for c in self.store.issue(2).commands if c.get("author") == "builder"]
        self.assertLessEqual({c["criterion"] for c in builder}, {"A1", "D1"})
        self.assertTrue([c for c in builder if c["criterion"] == "A1" and self.path in c["command"]])
        self.assertFalse(self.events("commands_dropped", 2))
        self.assertFalse([p for e in self.events("verified", 2) for p in e["problems"] if "no command selects" in p])

    def test_fault_94_a_command_naming_no_item_is_reported_to_the_builder(self):
        self.add_work(2, "docs/a.txt", "alpha", wrong_attempts=1)
        self.epic(2)
        stray = CheckSpec("Regression: the whole suite", command="true")
        agents = Agents(self.scripts, plan=with_zone(self.path), build=self.builder([stray]))
        self.run_engine(agents=agents)
        self.assertEqual(self.phase(2), Phase.DONE, self.events("round_failed", 2))
        self.assertTrue(self.events("commands_dropped", 2))
        feedback = [f for c in agents.calls if c[0] == "build" and c[2] == 2 for f in c[3]]
        self.assertTrue([f for f in feedback if "were not kept" in f and "Regression: the whole suite" in f], feedback)

    def test_fault_94_the_engine_version_moved_past_the_faulted_one(self):
        self.assertNotEqual(VERSION, "1.0.1")


class FindingNew1OwnerFindings(unittest.TestCase):
    """On an owner item only the agent part can block: a finding must quote the plan's agent part."""
    item_text = {"D1": "`docs/a.txt` contains `alpha`.", "D2": "Runs under a second on a 2020 laptop."}
    parts = {"D2": "time the page on this host"}

    def classify(self, quote, reproduced=True, invariant=None):
        f = Finding(id="F", title="t", item="D2", quote=quote, invariant=invariant, observed="slow", expected="fast",
                    reproduction="test -f timing.txt")
        return gate.classify(f, self.item_text, gate.DEFAULT_INVARIANTS, reproduced, {"D1"}, {"D2"}, self.parts)

    def test_new_1_a_finding_quoting_the_owner_items_own_text_never_blocks(self):
        f = self.classify("under a second on a 2020 laptop")
        self.assertEqual((f.status, f.blocking), ("advisory", False))

    def test_new_1_a_reproduced_finding_quoting_the_agent_part_blocks(self):
        f = self.classify("time the page on this host")
        self.assertEqual((f.status, f.blocking), ("open", True))

    def test_new_1_an_agent_part_finding_that_does_not_reproduce_is_advisory(self):
        self.assertEqual(self.classify("time the page on this host", reproduced=False).blocking, False)

    def test_new_1_an_invariant_on_an_owner_item_still_blocks(self):
        f = self.classify("under a second on a 2020 laptop", invariant="data loss")
        self.assertEqual((f.status, f.blocking), ("open", True))


class FindingNew1OwnerFindingsInARun(FixCase):
    def owner_issue_with(self, quote):
        self.add_work(2, "docs/a.txt", "alpha", items=["`docs/a.txt` contains `alpha`.",
                                                        "Runs under a second on a 2020 laptop."], owner_items=("D2",))
        self.epic(2)

        def report(result, req, plan, since):
            if since is None:
                result.findings = result.findings + [Finding(
                    id="", title="the timing is never measured", item="D2", quote=quote, observed="no timing",
                    expected="a timing of the page", reproduction="test -f edge_2.txt")]
            return result
        self.run_engine(agents=Agents(self.scripts, plan=with_zone("edge_2.txt"), examine=report))

    def test_new_1_a_finding_on_the_agent_part_blocks_until_fixed(self):
        self.owner_issue_with("time it on this host")   # the fake plan's agent part
        self.assertEqual(self.phase(2), Phase.DELIVERED)
        blocking = [f for f in self.store.issue(2).findings if f["blocking"]]
        self.assertEqual([(f["item"], f["status"]) for f in blocking], [("D2", "closed")])
        self.assertEqual(len(self.builds()), 2)

    def test_new_1_a_finding_on_the_owners_evidence_never_blocks(self):
        self.owner_issue_with("Runs under a second")
        self.assertEqual(self.phase(2), Phase.DELIVERED)
        self.assertFalse([f for f in self.store.issue(2).findings if f["blocking"]])
        self.assertEqual(len(self.builds()), 1)


class FindingNew2Dispositions(FixCase):
    def test_new_2_dispositions_retire_exact_node_ids_and_a_bare_function_retires_its_cases(self):
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        engine = self.make_engine()
        st = engine.store.issue(2)
        st.manifest = {"*": ["t.py::test_p[1]", "t.py::test_p[2]", "t.py::test_q[1]", "t.py::test_q[2]", "t.py::test_r"]}
        st.commands = [{"criterion": "D1", "command": "pytest t.py", "cwd": ".", "author": "builder"}]
        request = {"id": "R2-1", "kind": "command_change", "item": "D1", "detail": "select fewer cases", "reason": "fine",
                   "command": {"criterion": "D1", "command": "pytest t.py -k 'not p'", "cwd": ".", "author": "builder"}}
        engine._apply_request(2, st, self.repo.work, request, {"t.py::test_p": "excluded: obsolete",
                                                               "t.py::test_q[1]": "excluded: flaky upstream"})
        self.assertEqual(st.manifest, {"*": ["t.py::test_q[2]", "t.py::test_r"]})
        self.assertEqual(st.commands[-1]["command"], "pytest t.py -k 'not p'")


class FindingNew3Stopping(FixCase):
    def test_new_3_the_engine_sees_a_stop_during_a_long_agent_call_and_terminates_the_agents(self):
        from concurrent import futures
        from implement_loop import engine as engine_mod
        from implement_loop.agents import AgentStopped
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        store_dir = self.store_dir()

        class LongBuild(FakeAgents):
            def __init__(self, scripts):
                super().__init__(scripts)
                self.released, self.terminated = threading.Event(), 0

            def terminate_all(self):
                self.terminated += 1
                self.released.set()

            def build(self, vendor, req, plan, worktree, feedback):
                (store_dir / "STOP").write_text("the operator stops the run\n")
                if self.released.wait(15):   # an agent call that only a terminate ends
                    raise AgentStopped("run stopped")
                return super().build(vendor, req, plan, worktree, feedback)

        def quick(fs, timeout=None, return_when=futures.ALL_COMPLETED):
            return futures.wait(fs, timeout=None if timeout is None else min(timeout, 0.2), return_when=return_when)
        agents = LongBuild(self.scripts)
        started = time.monotonic()
        with mock.patch.object(engine_mod, "wait", quick):
            summary = self.run_engine(agents=agents)
        self.assertLess(time.monotonic() - started, 12, "the stop did not wait for the agent call to end")
        self.assertTrue(summary["stopped"])
        self.assertEqual(agents.terminated, 1)
        self.assertEqual(len(self.events("stop_requested")), 1)
        self.assertTrue(self.events("step_interrupted", 2))
        self.assertEqual(self.phase(2), Phase.BUILD)

    def test_new_3_an_agent_started_as_a_stop_arrives_is_killed(self):
        from implement_loop import live
        agents = live.LiveAgents("claude", self.repo.tmp / "live-run", None)
        real_popen = subprocess.Popen

        def popen_then_stop(*args, **kwargs):
            proc = real_popen(*args, **kwargs)
            agents.terminate_all()   # the stop lands between the check and the registration
            return proc
        started = time.monotonic()
        with mock.patch.object(live.subprocess, "Popen", popen_then_stop):
            with self.assertRaises(live.AgentStopped):
                agents._spawn([sys.executable, "-c", "import time; time.sleep(30)"], "", self.repo.tmp, 60)
        self.assertLess(time.monotonic() - started, 10, "the late agent was killed, not waited for")


FAKE_ENGINE = r"""
import os, signal, subprocess, sys, time
from pathlib import Path
run_dir = Path(os.environ["FAKE_RUN_DIR"])
run_dir.mkdir(parents=True, exist_ok=True)
mode = os.environ["FAKE_MODE"]
agent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"], start_new_session=True)
(run_dir / "agents.pids").write_text(str(agent.pid))
(run_dir / "fake-agent.pid").write_text(str(agent.pid))
if mode == "stubborn":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
else:
    signal.signal(signal.SIGTERM, lambda *a: (run_dir / "got-sigterm").write_text("1") or sys.exit(143))
while True:
    if mode == "polite" and (run_dir / "STOP").exists():
        agent.terminate()
        agent.wait()
        sys.exit(3)
    time.sleep(0.05)
"""


class FastPopen(subprocess.Popen):
    """The supervisor's grace periods (minutes) shortened to half a second each."""

    def wait(self, timeout=None):
        return super().wait(timeout=None if timeout is None else min(timeout, 0.5))


def gone(pid: int, within: float = 10) -> bool:
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        try:
            state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        except (OSError, IndexError):
            return True
        if state in ("Z", "X"):
            return True
        time.sleep(0.05)
    return False


class FindingNew3Supervisor(SupervisorCase):
    def test_new_3_one_deadline_is_set_at_the_start_for_repair_and_root_runs(self):
        self.put(2, Phase.WAITING, wait={"kind": "engine", "resume": "build", "version": "0.0.1"})
        self.fault()
        now = [100.0]
        deadlines = []
        sup = None

        def script(args):
            deadlines.append(sup._deadline)
            now[0] += 600
            if "--repair" not in args:
                self.put(2, Phase.DONE)
        sup = self.sup(script, max_hours=2, clock=lambda: now[0])
        out = sup.supervise()
        self.assertTrue(out.finished)
        self.assertEqual(len(deadlines), 2)
        self.assertEqual(set(deadlines), {100.0 + 2 * 3600})

    def test_new_3_the_backoff_never_sleeps_past_the_deadline(self):
        self.put(2, Phase.WAITING, wait={"kind": "ci", "resume": "land"})
        now, slept = [0.0], []

        def sleep(s):
            slept.append(s)
            now[0] += s
        sup = self.sup(lambda args: None, max_hours=0.01, clock=lambda: now[0])
        sup.sleep = sleep
        out = sup.supervise()
        self.assertFalse(out.finished)
        self.assertEqual(slept, [36.0], "60 s of backoff, capped by the 36 s left")

    def engine_script(self):
        script = self.repo.work / "tools" / "implementation-loop" / "implement.py"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(FAKE_ENGINE)

    def run_past_the_deadline(self, mode):
        from implement_loop import supervisor as supervisor_mod
        self.engine_script()
        run_dir = RunStore.for_root(self.repo.work, EPIC).dir
        sup = Supervisor(self.repo.work, EPIC, "claude", log=lambda m: None)
        sup._deadline = sup.clock() - 1   # the supervision's time is up as the run starts
        proxy = types.SimpleNamespace(Popen=FastPopen, TimeoutExpired=subprocess.TimeoutExpired, run=subprocess.run)
        with mock.patch.dict(os.environ, {"FAKE_RUN_DIR": str(run_dir), "FAKE_MODE": mode}), \
                mock.patch.object(supervisor_mod, "subprocess", proxy):
            code = sup._run_engine(["run", str(EPIC), "--operator", "claude", "--yes"])
        return code, run_dir

    def test_new_3_a_run_past_the_deadline_is_asked_to_stop_first(self):
        code, run_dir = self.run_past_the_deadline("polite")
        self.assertEqual(code, 3)
        self.assertTrue((run_dir / "STOP").exists())
        self.assertFalse((run_dir / "got-sigterm").exists(), "a run that stops is never signalled")
        self.assertTrue(gone(int((run_dir / "fake-agent.pid").read_text())))

    def test_new_3_a_run_that_ignores_stop_and_sigterm_is_killed_and_its_agents_reaped(self):
        code, run_dir = self.run_past_the_deadline("stubborn")
        self.assertEqual(code, -signal.SIGKILL)
        self.assertTrue((run_dir / "STOP").exists())
        self.assertTrue(gone(int((run_dir / "fake-agent.pid").read_text())), "the agent's own session was reaped")


if __name__ == "__main__":
    unittest.main()
