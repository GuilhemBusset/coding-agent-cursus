"""The live adapter, driven against fake `claude` and `codex` executables: no tokens spent.
Also the CI loop guard, against real commits."""

import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path

from helpers import REPO_ROOT, TempRepo, git, load_fixture

from implement_loop import live, schemas
from implement_loop.agents import DesignRequest
from implement_loop.issue_parser import parse
from implement_loop.model import Finding, Issue

FAKE = r'''#!{python}
import json, os, sys, time
vendor = os.path.basename(sys.argv[0])
if sys.argv[1:3] == ["mcp", "list"]:
    print(os.environ.get("FAKE_MCP", "[]"))
    sys.exit(0)
prompt = sys.stdin.read()
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps({{"vendor": vendor, "argv": sys.argv[1:], "prompt": prompt,
                         "env": {{k: os.environ.get(k) for k in ("GH_TOKEN", "GITHUB_TOKEN", "SSH_AUTH_SOCK", "GH_CONFIG_DIR",
                                                               "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0")}}}}) + "\n")
if os.environ.get("FAKE_SLEEP"):
    time.sleep(float(os.environ["FAKE_SLEEP"]))
if os.environ.get("FAKE_EXIT"):
    sys.stderr.write("boom\n")
    sys.exit(int(os.environ["FAKE_EXIT"]))
answer = json.load(open(os.environ["FAKE_ANSWER"]))
if vendor == "claude":
    print(json.dumps({{"type": "result", "is_error": False, "structured_output": answer,
                       "total_cost_usd": 0.01, "usage": {{"input_tokens": 10, "output_tokens": 5}}}}))
else:
    out = sys.argv[sys.argv.index("-o") + 1]
    open(out, "w").write(json.dumps(answer))
    print(json.dumps({{"type": "turn.completed", "usage": {{"input_tokens": 12, "output_tokens": 3}}}}))
'''


class StubWorkspace:
    def __init__(self, root: Path):
        self.root = root
        self.disposed = []

    def coord_path(self):
        return self.root

    @contextmanager
    def disposable(self, worktree):
        scratch = self.root / "scratch"
        scratch.mkdir(exist_ok=True)
        yield scratch
        self.disposed.append(scratch)


class LiveAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        bins = self.tmp / "bin"
        bins.mkdir()
        for name in ("claude", "codex"):
            path = bins / name
            path.write_text(FAKE.format(python=sys.executable))
            path.chmod(path.stat().st_mode | stat.S_IEXEC)
        self.log = self.tmp / "calls.jsonl"
        self.answer = self.tmp / "answer.json"
        self.env = {"FAKE_LOG": str(self.log), "FAKE_ANSWER": str(self.answer)}
        os.environ.update(self.env)
        self.sleeps = []
        self.agents = live.LiveAgents("claude", self.tmp / "run", StubWorkspace(self.tmp),
                                      claude_bin=str(bins / "claude"), codex_bin=str(bins / "codex"),
                                      sleep=self.sleeps.append)
        issue = Issue.from_api(load_fixture()["issues"]["28"])
        self.req = DesignRequest(issue=issue, spec=parse(issue, []), context="ctx")

    def tearDown(self):
        for key in ("FAKE_LOG", "FAKE_ANSWER", "FAKE_EXIT", "FAKE_SLEEP"):
            os.environ.pop(key, None)

    def answer_with(self, value):
        self.answer.write_text(json.dumps(value))

    def calls(self):
        return [json.loads(l) for l in self.log.read_text().splitlines()]

    def test_read_only_roles_get_read_only_tools_and_sandbox(self):
        self.answer_with({"objections": []})
        self.agents.audit("claude", self.req, [])
        self.agents.audit("codex", self.req, [])
        claude, codex = self.calls()
        a = claude["argv"]
        self.assertEqual(a[a.index("--permission-mode") + 1], "dontAsk")
        self.assertEqual(a[a.index("--tools") + 1], "Read,Glob,Grep")
        self.assertNotIn("--disallowedTools", a)
        self.assertIn("--json-schema", a)
        b = codex["argv"]
        self.assertEqual(b[b.index("--sandbox") + 1], "read-only")
        self.assertIn("--output-schema", b)
        self.assertNotIn("sandbox_workspace_write.network_access=true", b)
        self.assertFalse(any("mcp_servers" in x for x in b), "no MCP servers configured, nothing to disable")

    def test_writing_roles_can_edit_but_never_commit_push_or_call_gh(self):
        self.answer_with({"status": "done", "note": ""})
        from implement_loop.agents import Design
        design = Design(decisions={}, checks=[], files=["a.txt"], check_files=["tests/t.py"])
        self.agents.implement("claude", self.req, design, self.tmp, [])
        self.agents.implement("codex", self.req, design, self.tmp, ["fix the edge case"])
        claude, codex = self.calls()
        a = claude["argv"]
        self.assertEqual(a[a.index("--permission-mode") + 1], "acceptEdits")
        self.assertIn("Bash", a[a.index("--tools") + 1])
        for denied in ("Bash(git commit *)", "Bash(git push *)", "Bash(gh *)"):
            self.assertIn(denied, a)
        b = codex["argv"]
        self.assertEqual(b[b.index("--sandbox") + 1], "workspace-write")
        self.assertIn("sandbox_workspace_write.network_access=true", b)
        self.assertIn("fix the edge case", codex["prompt"])
        self.assertIn("`tests/t.py`", codex["prompt"])

    def test_agents_run_without_github_credentials(self):
        os.environ.update({"GH_TOKEN": "secret", "GITHUB_TOKEN": "secret", "SSH_AUTH_SOCK": "/tmp/agent.sock"})
        try:
            agents = live.LiveAgents("claude", self.tmp / "run2", StubWorkspace(self.tmp),
                                     claude_bin=self.agents.bins["claude"], codex_bin=self.agents.bins["codex"])
            self.answer_with({"notes": "x"})
            agents.explore("codex", "q", "b")
        finally:
            for k in ("GH_TOKEN", "GITHUB_TOKEN", "SSH_AUTH_SOCK"):
                os.environ.pop(k, None)
        env = self.calls()[-1]["env"]
        self.assertEqual((env["GH_TOKEN"], env["GITHUB_TOKEN"], env["SSH_AUTH_SOCK"]), (None, None, None))
        self.assertTrue(env["GH_CONFIG_DIR"].endswith("no-gh"))
        self.assertEqual((env["GIT_CONFIG_KEY_0"], env["GIT_CONFIG_VALUE_0"]), ("credential.helper", ""))

    def test_the_codex_check_author_has_no_network(self):
        self.answer_with({"files_written": [], "note": ""})
        from implement_loop.agents import Design
        design = Design(decisions={}, checks=[], files=[], check_files=["tests/t.py"])
        self.agents.write_checks("codex", self.req, design, self.tmp)
        argv = self.calls()[-1]["argv"]
        self.assertEqual(argv[argv.index("--sandbox") + 1], "workspace-write")
        self.assertNotIn("sandbox_workspace_write.network_access=true", argv)

    def test_every_configured_codex_mcp_server_is_disabled_by_name(self):
        os.environ["FAKE_MCP"] = json.dumps([{"name": "github", "enabled": True}, {"name": "files", "enabled": True}])
        try:
            self.answer_with({"objections": []})
            self.agents.audit("codex", self.req, [])
        finally:
            os.environ.pop("FAKE_MCP", None)
        argv = self.calls()[-1]["argv"]
        self.assertIn("mcp_servers.github.enabled=false", argv)
        self.assertIn("mcp_servers.files.enabled=false", argv)

    def test_codex_is_refused_when_its_mcp_servers_cannot_be_listed(self):
        os.environ["FAKE_MCP"] = "not json"
        try:
            self.answer_with({"objections": []})
            with self.assertRaises(live.AgentFailure):
                self.agents.audit("codex", self.req, [])
        finally:
            os.environ.pop("FAKE_MCP", None)

    def test_answers_are_mapped_into_engine_types(self):
        self.answer_with({"decisions": [{"id": "lib", "choice": "gpt-tokenizer", "rationale": "UMD build"}],
                          "checks": [{"criterion": "A1", "kind": "command", "command": "pytest -q", "cwd": ".", "description": ""}],
                          "files": ["x.html"], "check_files": ["tests/test_x.py"], "open_questions": []})
        p = self.agents.propose("codex", self.req, "B")
        self.assertEqual(p.decisions, {"lib": "gpt-tokenizer"})
        self.assertEqual(p.checks[0].command, "pytest -q")
        self.assertEqual(p.author, "B")
        record = [json.loads(l) for l in (self.tmp / "run" / "agents.jsonl").read_text().splitlines()][-1]
        self.assertEqual((record["role"], record["vendor"], record["issue"], record["ok"]), ("propose", "codex", 28, True))
        self.assertEqual(record["usage"]["input_tokens"], 12)
        self.assertTrue(list((self.tmp / "run" / "calls").glob("*-propose-codex-28.prompt.md")))

    def test_an_answer_off_schema_is_rejected_and_retried_then_fails(self):
        self.answer_with({"status": "finished"})
        from implement_loop.agents import Design
        design = Design(decisions={}, checks=[], files=[], check_files=[])
        with self.assertRaises(live.AgentFailure):
            self.agents.implement("claude", self.req, design, self.tmp, [])
        calls = self.calls()
        self.assertEqual(len(calls), 3)
        self.assertIn("Your previous answer was rejected", calls[1]["prompt"])
        self.assertEqual(self.sleeps, [], "schema problems are retried at once")

    def test_a_crashing_cli_is_retried_with_backoff(self):
        os.environ["FAKE_EXIT"] = "2"
        self.answer_with({"notes": "x"})
        with self.assertRaises(live.AgentFailure):
            self.agents.explore("claude", "q", "b")
        self.assertEqual(self.sleeps, [30, 90])

    def test_a_failed_review_reports_missing_not_approval(self):
        os.environ["FAKE_EXIT"] = "1"
        from implement_loop.agents import Design
        design = Design(decisions={}, checks=[], files=[], check_files=[])
        repo = TempRepo()
        try:
            head = git("rev-parse", "HEAD", cwd=repo.work)
            self.assertIsNone(self.agents.review("codex", "cross", self.req, design, repo.work, head, head, []))
        finally:
            repo.cleanup()

    def test_finding_verification_without_a_verdict_is_unresolved(self):
        os.environ["FAKE_EXIT"] = "1"
        finding = Finding(id="F1", reviewer="cross", priority=0, confidence=0.9, title="t")
        self.assertIsNone(self.agents.verify_finding("claude", self.req, self.tmp, finding))

    def test_finding_verification_runs_in_a_disposable_copy(self):
        self.answer_with({"reproduced": True, "evidence": "saw it"})
        finding = Finding(id="F1", reviewer="cross", priority=1, confidence=0.9, title="t")
        self.assertTrue(self.agents.verify_finding("claude", self.req, self.tmp, finding))
        self.assertEqual(len(self.agents.ws.disposed), 1)

    def test_stopping_terminates_running_agents(self):
        os.environ["FAKE_SLEEP"] = "30"
        self.answer_with({"notes": "x"})
        errors = []

        def run():
            try:
                self.agents.explore("claude", "q", "b")
            except Exception as e:  # noqa: BLE001
                errors.append(e)
        t = threading.Thread(target=run)
        started = time.monotonic()
        t.start()
        time.sleep(0.5)
        self.agents.terminate_all()
        t.join(10)
        self.assertLess(time.monotonic() - started, 10)
        self.assertIsInstance(errors[0], live.AgentStopped)

    def test_every_prompt_renders_without_leftover_placeholders(self):
        values = {k: "x" for k in ("role", "number", "title", "body", "ledger", "context", "ledger_ids", "feedback",
                                   "lens", "author", "proposals", "objections", "design", "check_files", "files",
                                   "commands", "review_role", "role_focus", "base", "head", "diff", "evidence",
                                   "artifact_ids", "finding", "question", "briefing")}
        for name in schemas.BY_ROLE:
            text = live.render(name, **values)
            self.assertNotIn("{{", text, name)

    def test_role_settings_come_from_loop_toml(self):
        roles = live.load_roles()
        self.assertEqual(roles["explore"].effort, "low")
        self.assertEqual(roles["explore"].claude_model, "sonnet")
        self.assertIsNone(roles["explore"].codex_model)
        self.assertEqual(roles["implement"].timeout_s, 5400)


class LoopGuardTests(unittest.TestCase):
    def setUp(self):
        self.repo = TempRepo()
        self.wt = self.repo.work
        git("switch", "-q", "-c", "feat/x", cwd=self.wt)
        self.base = git("rev-parse", "HEAD", cwd=self.wt)

    def tearDown(self):
        self.repo.cleanup()

    def commit(self, path, content, trailer=None):
        (self.wt / path).parent.mkdir(parents=True, exist_ok=True)
        (self.wt / path).write_text(content)
        git("add", "-A", cwd=self.wt)
        msg = "change" + (f"\n\nLoop-Phase: {trailer}" if trailer else "")
        git("commit", "-q", "-m", msg, cwd=self.wt)

    def guard(self):
        head = git("rev-parse", "HEAD", cwd=self.wt)
        return subprocess.run(["bash", str(REPO_ROOT / "scripts" / "check-loop-guard.sh"), self.base, head],
                              cwd=self.wt, capture_output=True, text=True)

    def test_implementation_after_locked_checks_passes(self):
        self.commit("tests/test_a.py", "def test_a(): pass\n", "acceptance-checks")
        self.commit("src/a.py", "x = 1\n", "implementation")
        self.assertEqual(self.guard().returncode, 0)

    def test_editing_a_locked_check_later_fails(self):
        self.commit("tests/test_a.py", "def test_a(): pass\n", "acceptance-checks")
        self.commit("tests/test_a.py", "def test_a(): assert True\n", "implementation")
        result = self.guard()
        self.assertEqual(result.returncode, 1)
        self.assertIn("tests/test_a.py was locked", result.stdout)

    def test_relocking_after_changed_requirements_is_allowed(self):
        self.commit("tests/test_a.py", "def test_a(): pass\n", "acceptance-checks")
        self.commit("tests/test_a.py", "def test_a(): assert 1\n", "acceptance-checks")
        self.assertEqual(self.guard().returncode, 0)


if __name__ == "__main__":
    unittest.main()
