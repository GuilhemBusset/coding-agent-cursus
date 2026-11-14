"""Proportionate review keeps real defects blocking and avoids unnecessary rebuilds (ADR 0018)."""

import unittest

import helpers  # noqa: F401 - puts the engine on sys.path
from implement_loop import gate
from implement_loop.agents import FakeAgents, Ruling
from implement_loop.model import Finding, Phase
from implement_loop.state import RunStore
from test_review_fixes import Agents, FixCase


class ReviewGateTests(unittest.TestCase):
    def test_polish_is_a_followup_but_material_defects_and_safety_still_block(self):
        for severity, invariant, blocking in ((3, None, False), (2, None, True), (1, None, True),
                                              (0, None, True), (3, "data loss", True)):
            with self.subTest(severity=severity, invariant=invariant):
                finding = Finding("F1", "a finding", item="D1", quote="the required behaviour",
                                  observed="wrong", expected="correct", reproduction="python check.py",
                                  severity=severity, invariant=invariant)
                gate.classify(finding, {"D1": "the required behaviour"}, gate.DEFAULT_INVARIANTS,
                              True, {"D1"}, set())
                self.assertEqual(finding.blocking, blocking)
                self.assertEqual(finding.status, "open" if blocking else "follow_up")

    def test_reuse_requires_a_quoted_verdict_and_a_passing_command_for_this_item_and_head(self):
        text = {"D1": "the required behaviour"}
        verdict = {"item": "D1", "verdict": "met", "quote": text["D1"],
                   "note": "python check.py asserts the required behaviour"}
        evidence = {"criterion": "D1", "command": "python check.py", "passed": True, "head_sha": "current"}
        self.assertEqual(gate.reviewed_tests([verdict], text, {"D1"}, [evidence], "current"), {"D1": verdict})
        for change in ({"passed": False}, {"head_sha": "old"}, {"criterion": "D2"}, {"command": "python other.py"}):
            with self.subTest(evidence=change):
                self.assertFalse(gate.reviewed_tests([verdict], text, {"D1"}, [evidence | change], "current"))
        for change in ({"quote": "something else entirely"}, {"note": "looks good"},
                       {"note": "python check.py"}, {"verdict": "unmet"}):
            with self.subTest(verdict=change):
                self.assertFalse(gate.reviewed_tests([verdict | change], text, {"D1"}, [evidence], "current"))


def reuse_tests(result, req, plan, since):
    texts = {i.id: i.text for i in req.spec.ledger}
    for item in plan["items"]:
        if item["proof"] == "test":
            command = next(c["command"] for c in req.facts["commands"] if c["criterion"] == item["id"])
            result.verdicts.append({"item": item["id"], "verdict": "met", "quote": texts[item["id"]],
                                    "note": f"{command} asserts the file contains the required value"})
    return result


class ReviewCalibrationTests(FixCase):
    def test_existing_tests_can_be_reviewed_locked_and_certified_without_duplicate_probes(self):
        self.add_work(2, "docs/a.txt", "alpha", probe="none")
        self.epic(2)
        agents = Agents(self.scripts, examine=reuse_tests)
        self.run_engine(agents=agents)
        st = self.store.issue(2)
        self.assertEqual(st.phase, Phase.DONE)
        self.assertFalse(st.probes)
        self.assertIn("checks/issue_2.sh", st.locked)
        self.assertEqual(len(self.builds()), 1)
        self.assertFalse(self.events("examination_incomplete", 2))
        self.assertFalse([c for c in agents.calls if c[0] == "arbitrate"])
        self.assertEqual(self.events("examined", 2)[0]["reused"], ["A1", "D1"])
        assert st.pr is not None
        pr = self.gh.prs[st.pr]
        self.assertEqual(pr["head"]["sha"], st.certified_sha)
        self.assertIn(st.certified_sha, self.gh._check_seen)

    def test_reproduced_polish_does_not_send_the_builder_back(self):
        self.add_work(2, "docs/a.txt", "alpha", probe="none")
        self.epic(2)

        def polish(result, req, plan, since):
            result = reuse_tests(result, req, plan, since)
            if since is None:
                result.findings = [Finding("", "nicer wording", item="D1", quote=req.spec.ledger[0].text,
                                           observed="terse", expected="friendlier", severity=3,
                                           reproduction="test -f optional-polish.txt")]
            return result

        self.run_engine(agents=Agents(self.scripts, examine=polish))
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertEqual(len(self.builds()), 1)
        self.assertFalse(self.events("round_failed", 2))
        self.assertIsNotNone(self.store.issue(2).followup)

    def test_revision_context_survives_verification_failures_and_a_reloaded_state(self):
        self.add_work(2, "docs/a.txt", "alpha", wrong_attempts=1)
        self.epic(2)
        revisions = []

        def record(result, req, worktree, k):
            revisions.append(req.facts["revision"])
            return result

        self.run_engine(agents=Agents(self.scripts, build=record))
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertEqual(revisions, [False, True])
        self.engine.store = RunStore(self.store.dir)
        self.assertTrue(self.engine._req(2).facts["revision"])

    def test_codex_operation_routes_disputes_to_codex_and_keeps_claude_certifying(self):
        self.add_work(2, "docs/a.txt", "alpha", probe="none")
        self.epic(2)
        self.run_engine(agents=FakeAgents(self.scripts, operator="codex", other="claude"))
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertEqual(self.roles("arbitrate"), {"codex"})
        self.assertEqual(self.roles("examine"), {"claude"})

    def test_astra_can_resolve_an_advisory_certificate_refusal_without_a_rebuild(self):
        self.add_work(2, "docs/a.txt", "alpha", probe="none", no_certify=1)
        self.epic(2)
        agents = Agents(self.scripts, examine=reuse_tests)
        disputes = []

        def arbitrate(vendor, req, dispute, worktree=None):
            disputes.append((vendor, dispute["kind"]))
            return agents._metered(req.issue.number, "arbitrate", vendor,
                                   lambda: Ruling(False, "The item is satisfied; more polish is optional."))

        agents.arbitrate = arbitrate  # ty: ignore[invalid-assignment]  # test double
        self.run_engine(agents=agents)
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertEqual(disputes, [("codex", "certificate_refusal")])
        self.assertEqual(len(self.builds()), 1)
        self.assertTrue(any("arbiter ruled" in f for e in agents.exams for f in e["feedback"]))
        self.assertIn("certificate-scope", {d["id"] for d in self.store.issue(2).decisions})

    def test_arbitration_does_not_replace_a_withheld_certificate(self):
        self.add_work(2, "docs/a.txt", "alpha", probe="none", no_certify=100, size="S")
        self.epic(2)
        agents = Agents(self.scripts, examine=reuse_tests)

        def arbitrate(vendor, req, dispute, worktree=None):
            return agents._metered(req.issue.number, "arbitrate", vendor, lambda: Ruling(False, "optional polish"))

        agents.arbitrate = arbitrate  # ty: ignore[invalid-assignment]  # test double
        self.run_engine(agents=agents)
        self.assertEqual(self.phase(2), Phase.FAILED)
        self.assertFalse(self.gh.prs)
        self.assertIsNone(self.store.issue(2).certified_sha)


if __name__ == "__main__":
    unittest.main()
