"""Test accounting of the trusted verifier: the `loop_pytest` plugin's per-process records,
how `run_check` turns them into a verdict, the selection manifest, and the check files that
can never pass. Real pytest in temporary repositories; skipped where pytest is missing."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

from helpers import HAS_PYTEST

from implement_loop import verify
from implement_loop.model import CheckSpec

PY = sys.executable
PLUGIN_PATH = str(Path(verify.__file__).resolve().parent.parent)


class TempTree(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.work = self.root / ".work"

    def write(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text))

    def check(self, command: str, criterion: str = "A1", cwd: str = ".", **kw):
        return verify.run_check(self.root, CheckSpec(criterion, "command", command, cwd=cwd, **kw), "f00d" * 10, self.work)


@unittest.skipUnless(HAS_PYTEST, "pytest is not installed")
class PluginRecordTests(TempTree):
    """The records `loop_pytest` writes, read straight from the report directory."""

    def pytest(self, *args: str, cwd: Path | None = None, env: dict | None = None) -> list[dict]:
        reports = self.root / ".reports"
        base = {k: v for k, v in os.environ.items() if not k.startswith("LOOP_")}
        base |= {"LOOP_REPORT_DIR": str(reports), "LOOP_REPO_ROOT": str(self.root), "PYTHONPATH": PLUGIN_PATH}
        subprocess.run([PY, "-m", "pytest", "-p", "implement_loop.loop_pytest", "-p", "no:cacheprovider", *args],
                       cwd=cwd or self.root, env=base | (env or {}), capture_output=True, text=True)
        return [json.loads(p.read_text()) for p in sorted(reports.glob("run-*.json"))]

    def test_every_outcome_is_recorded_with_repo_relative_ids(self):
        self.write("tests/test_all.py", """
            import pytest

            @pytest.fixture
            def broken_setup():
                raise RuntimeError("setup")

            @pytest.fixture
            def broken_teardown():
                yield
                raise RuntimeError("teardown")

            @pytest.mark.parametrize("n", [1, 2])
            def test_param(n):
                assert n

            class TestGroup:
                def test_method(self):
                    pass

            def test_fails():
                assert 1 == 2

            def test_skips():
                pytest.skip("later")

            @pytest.mark.xfail
            def test_xfails():
                assert False

            @pytest.mark.xfail
            def test_xpasses():
                pass

            def test_setup_error(broken_setup):
                pass

            def test_teardown_error(broken_teardown):
                pass
        """)
        [record] = self.pytest("tests/test_all.py")
        outcomes = {c["id"]: c["outcome"] for c in record["cases"]}
        p = "tests/test_all.py::"
        self.assertEqual(outcomes, {
            p + "test_param[1]": "passed", p + "test_param[2]": "passed", p + "TestGroup::test_method": "passed",
            p + "test_fails": "failed", p + "test_skips": "skipped", p + "test_xfails": "xfailed",
            p + "test_xpasses": "xpassed", p + "test_setup_error": "error", p + "test_teardown_error": "error"})
        self.assertEqual(record["exitstatus"], 1)
        self.assertEqual(len(record["collected"]), 9)
        self.assertEqual(set(record), {"cwd", "rootdir", "exitstatus", "cases", "collected"})

    def test_ids_are_repo_relative_when_the_rootdir_is_a_subfolder(self):
        self.write("sessions/01-x/pyproject.toml", """
            [project]
            name = "x"
            version = "0"

            [tool.pytest.ini_options]
            testpaths = ["tests"]
        """)
        self.write("sessions/01-x/tests/test_s.py", "import pytest\n\n@pytest.mark.parametrize('w', ['a', 'b'])\ndef test_s(w):\n    pass\n")
        [record] = self.pytest(cwd=self.root / "sessions/01-x")
        self.assertEqual(Path(record["rootdir"]), (self.root / "sessions/01-x").resolve())
        self.assertEqual(sorted(c["id"] for c in record["cases"]),
                         ["sessions/01-x/tests/test_s.py::test_s[a]", "sessions/01-x/tests/test_s.py::test_s[b]"])

    def test_collected_is_what_survived_deselection(self):
        self.write("tests/test_k.py", "def test_keep():\n    pass\n\ndef test_drop():\n    pass\n")
        [record] = self.pytest("tests/test_k.py", "-k", "keep")
        self.assertEqual(record["collected"], ["tests/test_k.py::test_keep"])
        self.assertEqual(record["cases"], [{"id": "tests/test_k.py::test_keep", "outcome": "passed"}])

    def test_a_file_that_fails_to_collect_is_an_error(self):
        self.write("tests/test_broken.py", "import not_a_module_anywhere\n\ndef test_a():\n    pass\n")
        [record] = self.pytest("tests/test_broken.py")
        self.assertEqual(record["cases"], [{"id": "tests/test_broken.py", "outcome": "error"}])
        self.assertEqual(record["exitstatus"], 2)

    def test_without_its_environment_the_plugin_does_nothing(self):
        self.write("tests/test_a.py", "def test_a():\n    pass\n")
        reports = self.root / ".reports"
        env = {k: v for k, v in os.environ.items() if not k.startswith("LOOP_")} | {"PYTHONPATH": PLUGIN_PATH}
        proc = subprocess.run([PY, "-m", "pytest", "-p", "implement_loop.loop_pytest", "tests/test_a.py"],
                              cwd=self.root, env=env, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertFalse(reports.exists())


@unittest.skipUnless(HAS_PYTEST, "pytest is not installed")
class RunCheckTests(TempTree):
    def test_two_chained_pytest_processes_are_both_accounted(self):
        self.write("tests/test_a.py", "def test_a():\n    pass\n")
        self.write("tests/test_b.py", "def test_b():\n    pass\n")
        ev, cases = self.check(f"{PY} -m pytest -q tests/test_a.py && {PY} -m pytest -q tests/test_b.py")
        self.assertTrue(ev.passed, ev.note)
        self.assertEqual(cases["processes"], 2)
        self.assertEqual(cases["passed"], ["tests/test_a.py::test_a", "tests/test_b.py::test_b"])
        self.assertEqual(sorted(cases["collected"]), ["tests/test_a.py::test_a", "tests/test_b.py::test_b"])
        self.assertEqual(ev.tests, {"passed": 2, "failed": 0, "skipped": 0})

    def test_a_failure_in_the_first_of_two_runs_is_not_lost(self):
        self.write("tests/test_a.py", "def test_a():\n    assert False\n")
        self.write("tests/test_b.py", "def test_b():\n    pass\n")
        ev, cases = self.check(f"{PY} -m pytest -q tests/test_a.py; {PY} -m pytest -q tests/test_b.py")
        self.assertEqual(ev.exit_code, 0)
        self.assertFalse(ev.passed)
        self.assertEqual(ev.note, "failed tests: ['tests/test_a.py::test_a']")
        self.assertEqual(cases["passed"], ["tests/test_b.py::test_b"])

    def test_a_skipped_test_fails_the_command(self):
        self.write("tests/test_a.py", "import pytest\n\ndef test_a():\n    pass\n\n@pytest.mark.skip(reason='later')\ndef test_b():\n    pass\n")
        ev, cases = self.check(f"{PY} -m pytest -q tests/test_a.py")
        self.assertEqual(ev.exit_code, 0)
        self.assertFalse(ev.passed)
        self.assertEqual(ev.note, "unexpected skip: ['tests/test_a.py::test_b']")

    def test_xfail_counts_as_not_run_and_xpass_as_failed(self):
        self.write("tests/test_x.py", """
            import pytest

            @pytest.mark.xfail
            def test_xfails():
                assert False

            @pytest.mark.xfail
            def test_xpasses():
                pass
        """)
        ev, cases = self.check(f"{PY} -m pytest -q tests/test_x.py")
        self.assertEqual(ev.exit_code, 0)
        self.assertFalse(ev.passed)
        self.assertEqual(cases["skipped"], ["tests/test_x.py::test_xfails"])
        self.assertEqual(cases["failed"], ["tests/test_x.py::test_xpasses"])

    def test_a_usage_error_gives_a_readable_note(self):
        self.write("tests/test_a.py", "def test_a():\n    pass\n")
        ev, cases = self.check(f"{PY} -m pytest -q tests/test_a.py && {PY} -m pytest -q tests/test_missing.py")
        self.assertFalse(ev.passed)
        self.assertEqual(ev.exit_code, 4)
        self.assertEqual(cases["bad_exit"], [4])
        self.assertEqual(ev.note, "pytest exited 4 (usage error: file or directory not found: tests/test_missing.py)")

    def test_a_bad_option_stops_pytest_before_any_test(self):
        self.write("tests/test_a.py", "def test_a():\n    pass\n")
        ev, cases = self.check(f"{PY} -m pytest -q --no-such-option tests/test_a.py")
        self.assertFalse(ev.passed)
        self.assertEqual(cases["bad_exit"], [None])
        self.assertTrue(ev.note.startswith("pytest stopped before running any test"), ev.note)
        self.assertIn("--no-such-option", ev.note)

    def test_nothing_selected_is_no_tests_ran(self):
        self.write("tests/test_a.py", "def test_a():\n    pass\n")
        ev, _ = self.check(f"{PY} -m pytest -q tests/test_a.py -k nothing_matches")
        self.assertFalse(ev.passed)
        self.assertEqual(ev.note, "no tests ran")

    def test_a_command_that_replaces_pythonpath_is_told_how_to_fix_it(self):
        self.write("tests/test_a.py", "def test_a():\n    pass\n")
        ev, cases = self.check(f"PYTHONPATH=src {PY} -m pytest -q tests/test_a.py")
        self.assertIsNone(cases)
        self.assertFalse(ev.passed)
        self.assertIn("extend it (PYTHONPATH=src:$PYTHONPATH)", ev.note)

    def test_a_pytest_run_by_a_test_is_not_the_checks_own(self):
        """A test of a test runner starts pytest on deliberately failing fixtures: those are
        not results of the check."""
        self.write("fixtures/check_inner.py", "def test_inner():\n    assert False\n")
        self.write("tests/test_runner.py", f"""
            import subprocess

            def test_runner_reports_the_failure():
                proc = subprocess.run([{PY!r}, "-m", "pytest", "-q", "fixtures/check_inner.py"])
                assert proc.returncode == 1
        """)
        ev, cases = self.check(f"{PY} -m pytest -q tests/test_runner.py")
        self.assertTrue(ev.passed, ev.note + ev.output_tail)
        self.assertEqual(cases["passed"], ["tests/test_runner.py::test_runner_reports_the_failure"])
        self.assertEqual(cases["processes"], 1)

    def test_a_worktrees_own_engine_package_is_the_one_its_tests_import(self):
        self.write("tools/implement_loop/__init__.py", "WHO = 'worktree'\n")
        self.write("tests/test_engine_copy.py", """
            import sys
            from pathlib import Path

            sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

            def test_imports_the_worktree_copy():
                import implement_loop
                assert implement_loop.WHO == "worktree"
        """)
        ev, _ = self.check(f"{PY} -m pytest -q tests/test_engine_copy.py")
        self.assertTrue(ev.passed, ev.note + ev.output_tail)

    def test_pytest_through_uv_run_with_its_own_project_is_accounted(self):
        if not shutil.which("uv") or subprocess.run(
                ["uv", "run", "--offline", "--no-project", "--with", "pytest==8.3.5", "python", "-c", "import pytest"],
                capture_output=True).returncode != 0:
            self.skipTest("uv with pytest==8.3.5 in its cache is not available offline")
        self.write("sessions/01-x/pyproject.toml", "[tool.pytest.ini_options]\naddopts = '-q'\n")
        self.write("sessions/01-x/tests/test_s.py", "def test_s():\n    pass\n")
        ev, cases = self.check("uv run --offline --no-project --with pytest==8.3.5 pytest tests", cwd="sessions/01-x")
        self.assertTrue(ev.passed, ev.note + ev.output_tail)
        self.assertEqual(cases["passed"], ["sessions/01-x/tests/test_s.py::test_s"])


class RunCheckWithoutPytestTests(TempTree):
    def test_a_timeout_stops_every_process_the_command_started(self):
        start = time.monotonic()
        ev, cases = self.check("sleep 20; sleep 20", timeout_s=1)
        self.assertLess(time.monotonic() - start, 10)
        self.assertFalse(ev.passed)
        self.assertIsNone(cases)
        self.assertEqual(ev.note, "timed out after 1 s")

    def test_a_command_without_pytest_is_judged_by_its_exit_code(self):
        ev, cases = self.check("true")
        self.assertTrue(ev.passed)
        self.assertIsNone(cases)
        self.assertIsNone(ev.tests)
        ev, _ = self.check("exit 3")
        self.assertFalse(ev.passed)
        self.assertEqual(ev.note, "")


@unittest.skipUnless(HAS_PYTEST, "pytest is not installed")
class ManifestTests(TempTree):
    def setUp(self):
        super().setUp()
        self.write("tests/test_feature.py", """
            import pytest

            @pytest.mark.parametrize("n", [1, 2])
            def test_param(n):
                assert n

            def test_contract():
                pass

            def test_benchmark_owner_only():
                pass
        """)
        self.files = ["tests/test_feature.py"]
        self.locked = verify.lock(self.root, self.files, ["."])
        self.spec = CheckSpec("A1", "command", f"{PY} -m pytest -q tests/test_feature.py -k 'not benchmark'")

    def run_verify(self, manifest, specs=None):
        return verify.verify(self.root, specs or [self.spec], "sha", self.work, self.locked, self.files, manifest)

    def test_a_test_no_command_selects_is_not_a_failure_but_is_reported(self):
        ok, evidence, problems, ran = self.run_verify(None)
        self.assertTrue(ok, problems)
        self.assertEqual(ran, ["tests/test_feature.py::test_contract", "tests/test_feature.py::test_param[1]",
                               "tests/test_feature.py::test_param[2]"])
        manifest = verify.selection({e["criterion"]: e for e in evidence})
        self.assertEqual(manifest, {"A1": ran})
        ok, _, problems, _ = self.run_verify(manifest)
        self.assertTrue(ok, problems)
        self.assertEqual(verify.unselected(self.root, self.files, manifest, {}),
                         ["tests/test_feature.py::test_benchmark_owner_only"])
        self.assertEqual(verify.unselected(self.root, self.files, manifest,
                                           {"tests/test_feature.py::test_benchmark_owner_only": "owner-run"}), [])

    def test_a_missing_manifest_test_fails_verification(self):
        manifest = {"A1": ["tests/test_feature.py::test_contract", "tests/test_feature.py::test_param[1]"]}
        narrowed = CheckSpec("A1", "command", f"{PY} -m pytest -q tests/test_feature.py -k param")
        ok, _, problems, ran = self.run_verify(manifest, [narrowed])
        self.assertFalse(ok)
        self.assertEqual(problems, ["locked tests did not run: ['tests/test_feature.py::test_contract']"])
        self.assertNotIn("tests/test_feature.py::test_contract", ran)

    def test_parametrized_ids_match_exactly_and_bare_ids_match_any_case(self):
        only_one = CheckSpec("A1", "command", f"{PY} -m pytest -q 'tests/test_feature.py::test_param[1]'")
        ok, _, problems, _ = self.run_verify({"A1": ["tests/test_feature.py::test_param"]}, [only_one])
        self.assertTrue(ok, problems)
        ok, _, problems, _ = self.run_verify({"A1": ["tests/test_feature.py::test_param[2]"]}, [only_one])
        self.assertEqual(problems, ["locked tests did not run: ['tests/test_feature.py::test_param[2]']"])

    def test_tests_outside_the_manifest_may_run(self):
        ok, _, problems, _ = self.run_verify({"A1": ["tests/test_feature.py::test_contract"]})
        self.assertTrue(ok, problems)

    def test_a_skip_still_fails_even_when_the_manifest_is_met(self):
        self.write("tests/test_feature.py", "import pytest\n\ndef test_contract():\n    pass\n\ndef test_other():\n    pytest.skip('x')\n")
        self.locked = verify.lock(self.root, self.files, ["."])
        ok, _, problems, _ = self.run_verify({"A1": ["tests/test_feature.py::test_contract"]},
                                             [CheckSpec("A1", "command", f"{PY} -m pytest -q tests/test_feature.py")])
        self.assertFalse(ok)
        self.assertEqual(problems, ["A1 failed: unexpected skip: ['tests/test_feature.py::test_other']"])


class SelectionTests(unittest.TestCase):
    def test_selection_merges_commands_and_drops_criteria_without_tests(self):
        cases = {"A1": [{"passed": ["b::t", "a::t"]}, {"passed_tests": ["a::t", "c::t[1]"], "passed": True}],
                 "A2": None, "A3": {"passed": []}}
        self.assertEqual(verify.selection(cases), {"A1": ["a::t", "b::t", "c::t[1]"]})

    def test_unselected_compares_without_parameters(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        (root / "t").mkdir()
        (root / "t" / "test_u.py").write_text("def test_a():\n    pass\n\ndef test_b():\n    pass\n\ndef test_c():\n    pass\n")
        (root / "t" / "test_bad.py").write_text("def test_(:\n")
        manifest = {"A1": ["t/test_u.py::test_a[x-1]"]}
        self.assertEqual(verify.unselected(root, ["t/test_u.py", "t/test_bad.py"], manifest,
                                           {"t/test_u.py::test_b": "excluded: needs a GPU"}),
                         ["t/test_bad.py::<unparseable>", "t/test_u.py::test_c"])
        self.assertEqual(verify.unselected(root, ["t/test_u.py"], None, None),
                         ["t/test_u.py::test_a", "t/test_u.py::test_b", "t/test_u.py::test_c"])


class UnconditionalFailureTests(TempTree):
    def flagged(self, rel: str, text: str) -> list[str]:
        self.write(rel, text)
        return verify.unconditional_failures(self.root, [rel])

    def test_python_tests_that_cannot_pass(self):
        problems = self.flagged("tests/test_stub.py", """
            import pytest
            import unittest

            def test_assert_false():
                assert False, "not written yet"

            def test_assert_zero():
                assert 0

            def test_assert_none():
                assert None

            def test_pytest_fail():
                pytest.fail("todo")

            def test_raise_assertion():
                raise AssertionError("todo")

            def test_raise_exception():
                raise Exception

            def test_docstring_first():
                \"\"\"Describes the test.\"\"\"
                assert False

            class TestCase(unittest.TestCase):
                def test_self_fail(self):
                    self.fail("todo")
        """)
        self.assertEqual([p.split(" always fails")[0] for p in problems], [
            "tests/test_stub.py::test_assert_false", "tests/test_stub.py::test_assert_zero",
            "tests/test_stub.py::test_assert_none", "tests/test_stub.py::test_pytest_fail",
            "tests/test_stub.py::test_raise_assertion", "tests/test_stub.py::test_raise_exception",
            "tests/test_stub.py::test_docstring_first", "tests/test_stub.py::TestCase::test_self_fail"])
        self.assertIn("its first statement is `assert False, 'not written yet'`", problems[0])

    def test_ordinary_python_tests_are_left_alone(self):
        self.assertEqual(self.flagged("tests/test_ok.py", """
            import pytest
            from pkg import add

            def helper():
                assert False

            def test_value():
                assert add(1, 2) == 3

            def test_negation():
                assert not add(0, 0)

            def test_raises():
                with pytest.raises(ValueError):
                    add("a", None)

            def test_conditional():
                if add(1, 1) != 2:
                    pytest.fail("wrong sum")

            def test_fail_later():
                result = add(1, 2)
                assert False, result

            def test_truthy_constant():
                assert True

            def test_raise_other():
                raise ValueError("a test that checks the code raises, written oddly")
        """), [])

    def test_javascript_tests_that_cannot_pass(self):
        problems = self.flagged("tests/widget.test.mjs", """
            import { test, it } from 'node:test';
            import assert from 'node:assert/strict';

            test('renders the widget', () => {
              assert.fail('not implemented');
            });

            it("counts tokens", async function () {
              // to do
              throw new Error("todo");
            });

            test(`keeps state`, async (t) => {
              /* later */ assert.ok(false, 'pending');
            });
        """)
        self.assertEqual(len(problems), 3, problems)
        self.assertTrue(problems[0].startswith("tests/widget.test.mjs:5: the test always fails"), problems[0])

    def test_ordinary_javascript_tests_are_left_alone(self):
        self.assertEqual(self.flagged("tests/widget.test.ts", """
            import { test } from 'node:test';
            import assert from 'node:assert/strict';
            import { add } from '../src/add.ts';

            test('adds', () => {
              assert.equal(add(1, 2), 3);
            });

            test('rejects bad input', () => {
              assert.throws(() => { throw new Error('bad'); });
            });

            test('a todo', { todo: true }, () => {
              assert.fail('later');
            });

            // test('commented out', () => { assert.fail('x'); });

            test('falsy names are fine', (t) => {
              assert.ok(falseStart === undefined);
            });

            if (/pattern/.test(name)) { throw new Error('unrelated'); }
        """), [])

    def test_shell_scripts_that_cannot_pass(self):
        self.assertEqual(self.flagged("checks/a.sh", "#!/usr/bin/env bash\nset -euo pipefail\n# not written yet\necho 'todo' >&2\nexit 1\n"),
                         ["checks/a.sh: the script always fails: its only command is `exit 1`"])
        self.assertEqual(len(self.flagged("checks/b", "#!/bin/sh\nfalse\n")), 1)

    def test_ordinary_shell_scripts_are_left_alone(self):
        self.assertEqual(self.flagged("checks/c.sh", "test -f out.txt || exit 1\n"), [])
        self.assertEqual(self.flagged("checks/d.sh", "#!/bin/bash\nif ! grep -q ok out.txt; then\n  exit 1\nfi\n"), [])
        self.assertEqual(self.flagged("checks/e.sh", "exit 0\n"), [])
        self.assertEqual(self.flagged("checks/f.sh", "grep -q ok out.txt\n"), [])


if __name__ == "__main__":
    unittest.main()
