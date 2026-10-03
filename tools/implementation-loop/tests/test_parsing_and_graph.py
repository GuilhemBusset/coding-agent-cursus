import unittest
from pathlib import Path

from helpers import REPO_ROOT, load_fixture

from implement_loop import issue_parser
from implement_loop.github import FakeGitHub
from implement_loop.graph import CycleError, build_plan, compute_waves, topological_order
from implement_loop.model import Issue


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.fixture = load_fixture()
        self.tokenizer = Issue.from_api(self.fixture["issues"]["28"])

    def test_ledger_reads_both_sections_in_order(self):
        items = issue_parser.ledger(self.tokenizer.body)
        self.assertEqual([i.id for i in items], ["D1", "D2", "D3", "D4", "D5", "A1", "A2", "A3"])
        self.assertTrue(all(not i.checked for i in items))
        self.assertIn("type-to-tokenize", items[0].text)

    def test_conventions_block_is_not_part_of_references(self):
        sections = issue_parser.sections(self.tokenizer.body)
        self.assertFalse(any("Conventions" in line for line in sections.get("references", [])))

    def test_branch_and_session_relative_paths(self):
        spec = issue_parser.parse(self.tokenizer, [])
        self.assertEqual(spec.branch, "feat/s1-widget-tokenizer")
        self.assertEqual(spec.declared_paths, ["sessions/01-fundamentals/cursus/labs/tokenizer.html"])

    def test_ticking_does_not_change_the_hash(self):
        body = self.tokenizer.body
        ticked = issue_parser.tick(body, {"D1": "https://github.test/c/1", "A2": ""})
        self.assertNotEqual(body, ticked)
        self.assertIn("- [x] `cursus/labs/tokenizer.html`", ticked)
        self.assertIn("([evidence](https://github.test/c/1))", ticked)
        self.assertEqual(issue_parser.body_hash(body), issue_parser.body_hash(ticked))
        checked = [i.id for i in issue_parser.ledger(ticked) if i.checked]
        self.assertEqual(checked, ["D1", "A2"])
        self.assertEqual(issue_parser.tick(ticked, {"D1": "https://github.test/c/1"}), ticked)

    def test_editing_a_criterion_changes_the_hash(self):
        body = self.tokenizer.body
        edited = body.replace("under 50 ms", "under 20 ms")
        self.assertNotEqual(issue_parser.body_hash(body), issue_parser.body_hash(edited))

    def test_path_tokens_exclude_commands_and_numbers(self):
        self.assertTrue(issue_parser._is_path("tools/html-pages/GUIDE.md"))
        self.assertTrue(issue_parser._is_path(".github/workflows/checks.yml"))
        self.assertTrue(issue_parser._is_path("uv.lock"))
        for token in ("uv run pytest", "0.8", "--group", "gh api user", "data-design-system=\"cursus\"",
                      "refs/heads/homework/**", "~/projects/x", "file://", ".venv"):
            self.assertFalse(issue_parser._is_path(token), token)


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.gh = FakeGitHub(load_fixture())

    def test_epic_10_plan_matches_the_filed_waves(self):
        plan = build_plan(self.gh, 10, REPO_ROOT)
        self.assertEqual(plan.mode, "epic")
        self.assertEqual(len(plan.work), 33)
        self.assertEqual(sorted(plan.tracking[10]), list(range(11, 19)))
        self.assertEqual(plan.waves[20], 0)
        self.assertEqual(plan.waves[23], 1)
        self.assertEqual(plan.waves[48], 4)
        self.assertEqual(plan.waves[51], 6)
        self.assertEqual(plan.deps[46], {19, 28, 29, 38, 39})
        self.assertEqual(plan.external, set())
        self.assertEqual(plan.warnings, [])
        order = plan.work
        for n, deps in plan.deps.items():
            for d in deps:
                self.assertLess(order.index(d), order.index(n), f"#{d} must come before #{n}")

    def test_single_issue_pulls_in_its_open_prerequisite_closure(self):
        plan = build_plan(self.gh, 46, REPO_ROOT)
        self.assertEqual(plan.mode, "issue")
        self.assertEqual(plan.work[-1], 46)
        self.assertTrue({19, 20, 21, 27, 28, 29, 38, 39}.issubset(set(plan.work)))
        self.assertNotIn(51, plan.work)
        self.assertIn(28, plan.external)

    def test_closed_prerequisites_are_satisfied(self):
        self.gh.issues[21]["state"] = "closed"
        plan = build_plan(self.gh, 28, REPO_ROOT)
        self.assertEqual(plan.deps[28], {20})
        self.assertEqual(plan.satisfied[28], {21})

    def test_cycles_are_reported(self):
        gh = FakeGitHub()
        gh.add_issue(1, "a", blocked_by=(2,))
        gh.add_issue(2, "b", blocked_by=(1,))
        with self.assertRaises(CycleError) as ctx:
            build_plan(gh, 1, REPO_ROOT)
        self.assertEqual(ctx.exception.members, [1, 2])

    def test_order_is_stable_and_waves_follow_longest_path(self):
        deps = {1: set(), 2: {1}, 3: {1}, 4: {2, 3}, 5: set()}
        order = topological_order(set(deps), deps)
        self.assertEqual(order, [1, 2, 3, 4, 5])
        self.assertEqual(compute_waves(order, deps), {1: 0, 2: 1, 3: 1, 4: 2, 5: 0})


if __name__ == "__main__":
    unittest.main()
