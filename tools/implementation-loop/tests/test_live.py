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
import tomllib
import unittest
from contextlib import contextmanager
from pathlib import Path

from helpers import REPO_ROOT, TempRepo, git, load_fixture

from implement_loop import live, schemas
from implement_loop.agents import IssueRequest
from implement_loop.issue_parser import parse
from implement_loop.model import CheckSpec, Issue

FAKE = r'''#!{python}
import json, os, sys, time
vendor = os.path.basename(sys.argv[0])
if sys.argv[1:3] == ["mcp", "list"]:
    local = os.path.join(os.getcwd(), ".fake-mcp.json")   # stands in for a project .codex/config.toml
    print(open(local).read() if os.path.exists(local) else os.environ.get("FAKE_MCP", "[]"))
    sys.exit(0)
prompt = sys.stdin.read()
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps({{"vendor": vendor, "argv": sys.argv[1:], "prompt": prompt, "cwd": os.getcwd(),
                         "env": {{k: os.environ.get(k) for k in ("GH_TOKEN", "GITHUB_TOKEN", "SSH_AUTH_SOCK", "GH_CONFIG_DIR",
                                                               "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0")}}}}) + "\n")
if os.environ.get("FAKE_SLEEP"):
    time.sleep(float(os.environ["FAKE_SLEEP"]))
if os.environ.get("FAKE_EXIT"):
    sys.stderr.write(os.environ.get("FAKE_STDERR", "boom") + "\n")
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

PLAN = {"items": [{"id": "D1", "reading": "a lab page", "quote": "type-to-tokenize colored chips", "proof": "test"}],
        "zones": ["cursus/labs/"], "notes": ""}

ANSWERS = {
    "explore": {"notes": "x"},
    "plan": {"items": [
        {"id": "D1", "reading": "a lab page", "quote": "type-to-tokenize colored chips", "proof": "test",
         "capability": None, "agent_part": None, "depends_on": None, "depends_quote": None},
        {"id": "A1", "reading": "fast on a laptop", "quote": "updates in under 50 ms", "proof": "owner",
         "capability": "hardware:laptop", "agent_part": "measure it on this host", "depends_on": None,
         "depends_quote": None}],
        "zones": ["cursus/labs/tokenizer.html"],
        "decisions": [{"id": "lib", "choice": "gpt-tokenizer", "rationale": "UMD build"}], "notes": "plan notes"},
    "triage": {"objections": [{"kind": "misreading", "text": "it is a lab, not a deck", "item": "D1",
                               "quote": "type-to-tokenize colored chips", "proof": None, "capability": None,
                               "depends_on": None, "depends_quote": None}]},
    "build": {"status": "done", "note": "built", "tests": ["tests/test_lab.py"],
              "commands": [{"criterion": "D1", "command": "pytest -q tests/test_lab.py", "cwd": ".", "timeout_s": None}],
              "dispositions": [{"test": "tests/test_lab.py::test_speed", "disposition": "owner-run"}],
              "decisions": [{"id": "layout", "choice": "one page", "rationale": "simplest"}],
              "requests": [{"kind": "command_change", "detail": "select one more test", "paths": [], "item": "D1",
                            "finding": None, "capability": None, "depends_on": None, "depends_quote": None,
                            "command": "pytest -q tests", "cwd": "tests", "timeout_s": 600}]},
    "resolve_locked": {"files": ["checks/shared.sh"], "note": "kept both sides"},
    "examine": {"verdicts": [{"item": "A2", "verdict": "unmet", "quote": "Page weight is documented", "note": "missing"}],
                "findings": [{"title": "the toggle loses the text", "item": "D1", "quote": "a GPT-2 (r50k) vs o200k toggle",
                              "invariant": None, "observed": "empty box", "expected": "the text stays",
                              "reproduction": "node checks/toggle.mjs", "cwd": ".", "probe": None, "file": "x.html",
                              "line": 3, "severity": 2}],
                "probes": [{"file": "checks/probe_toggle.sh", "criterion": "D1", "command": "bash checks/probe_toggle.sh",
                            "cwd": ".", "content": "#!/usr/bin/env bash\ntest -s cursus/labs/tokenizer.html\n"}],
                "certify": False, "summary": "one finding"},
    "decide": {"decisions": [{"request": "R28-1", "approve": True, "reason": "the suite needs it",
                              "dispositions": [{"test": "tests/test_lab.py::test_net", "disposition": "excluded: needs CDN"}]}]},
    "arbitrate": {"upheld": False, "reason": "the item does not ask for it"},
}
READ_ONLY_ROLES = ("plan", "triage", "arbitrate")
WORKING_ROLES = ("build", "resolve_locked", "examine", "decide")


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
        try:
            yield scratch
        finally:
            self.disposed.append(scratch)


class RecordingMeter:
    def __init__(self):
        self.events = []

    def before(self, issue, role, vendor):
        self.events.append(("before", issue, role, vendor))

    def after(self, issue, role, vendor, outcome):
        self.events.append(("after", issue, role, vendor, outcome))

    def outcomes(self):
        return [e[4] for e in self.events if e[0] == "after"]


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
        self.agents = self.new_agents()
        issue = Issue.from_api(load_fixture()["issues"]["28"])
        self.req = IssueRequest(issue=issue, spec=parse(issue, []), context="ctx", feedback=["the plan feedback"],
                                facts={"lacks": ["hardware:laptop"], "invariants": ["secret exposure"]})

    def new_agents(self, run="run", **kwargs):
        bins = self.tmp / "bin"
        agents = live.LiveAgents("claude", self.tmp / run, StubWorkspace(self.tmp), claude_bin=str(bins / "claude"),
                                 codex_bin=str(bins / "codex"), sleep=self.sleeps.append, **kwargs)
        agents.meter = self.meter = RecordingMeter()
        return agents

    def tearDown(self):
        for key in ("FAKE_LOG", "FAKE_ANSWER", "FAKE_EXIT", "FAKE_SLEEP", "FAKE_STDERR", "FAKE_MCP"):
            os.environ.pop(key, None)

    def answer_with(self, value):
        self.answer.write_text(json.dumps(value))

    def calls(self):
        return [json.loads(l) for l in self.log.read_text().splitlines()]

    def invoke(self, role, vendor, cwd=None, since=None, memory=()):
        """Call `role` through the adapter's own method, with that role's valid answer."""
        cwd = cwd or self.tmp
        self.answer_with(ANSWERS[role])
        a, req = self.agents, self.req
        if role == "explore":
            return a.explore(vendor, "what validates work here?", "the briefing")
        if role == "plan":
            return a.plan(vendor, req, None)
        if role == "triage":
            return a.triage(vendor, req, PLAN)
        if role == "build":
            return a.build(vendor, req, PLAN, cwd, ["fix the edge case"])
        if role == "resolve_locked":
            return a.resolve_locked(vendor, req, cwd, ["checks/shared.sh"], ["keep both sides"])
        if role == "examine":
            return a.examine(vendor, req, PLAN, cwd, "a" * 40, "b" * 40, [{"criterion": "D1", "passed": True}],
                             list(memory), [], since)
        if role == "decide":
            return a.decide(vendor, req, cwd, [{"id": "R28-1", "kind": "paths", "paths": ["setup/suites.txt"]}])
        if role == "arbitrate":
            return a.arbitrate(vendor, req, {"kind": "finding", "argument": "the item never asks for offline"})
        raise AssertionError(role)

    # ---------------------------------------------------------------- permissions
    def test_read_only_roles_get_read_only_tools_and_sandbox(self):
        for role in READ_ONLY_ROLES:
            with self.subTest(role=role):
                self.invoke(role, "claude")
                self.invoke(role, "codex")
                claude, codex = self.calls()[-2:]
                a = claude["argv"]
                self.assertEqual(a[a.index("--permission-mode") + 1], "dontAsk")
                self.assertEqual(a[a.index("--tools") + 1], "Read,Glob,Grep")
                self.assertNotIn("--disallowedTools", a)
                self.assertIn("--json-schema", a)
                b = codex["argv"]
                self.assertEqual(b[b.index("--sandbox") + 1], "read-only")
                self.assertIn("--output-schema", b)
                self.assertFalse(any("mcp_servers" in x for x in b), "no MCP servers configured, nothing to disable")

    def test_explorers_may_also_search_the_web(self):
        self.invoke("explore", "claude")
        a = self.calls()[-1]["argv"]
        self.assertEqual(a[a.index("--tools") + 1], "Read,Glob,Grep,WebFetch,WebSearch")
        self.assertEqual(a[a.index("--model") + 1], "sonnet")

    def test_working_roles_get_the_same_access_from_both_vendors(self):
        # Sandbox parity (ADR 0012): a sandbox limit is an engine problem, never an owner obligation.
        for role in WORKING_ROLES:
            with self.subTest(role=role):
                self.invoke(role, "claude")
                self.invoke(role, "codex")
                claude, codex = self.calls()[-2:]
                a = claude["argv"]
                self.assertEqual(a[a.index("--permission-mode") + 1], "acceptEdits")
                self.assertIn("Bash", a[a.index("--tools") + 1])
                for denied in ("Bash(git commit *)", "Bash(git push *)", "Bash(gh *)"):
                    self.assertIn(denied, a)
                b = codex["argv"]
                self.assertEqual(b[b.index("--sandbox") + 1], "danger-full-access")
                self.assertNotIn("workspace-write", b)
                self.assertIn('approval_policy="never"', b)

    def test_agents_run_without_github_credentials(self):
        os.environ.update({"GH_TOKEN": "secret", "GITHUB_TOKEN": "secret", "SSH_AUTH_SOCK": "/tmp/agent.sock"})
        try:
            self.agents = self.new_agents("run2")
            self.invoke("build", "codex")
        finally:
            for k in ("GH_TOKEN", "GITHUB_TOKEN", "SSH_AUTH_SOCK"):
                os.environ.pop(k, None)
        env = self.calls()[-1]["env"]
        self.assertEqual((env["GH_TOKEN"], env["GITHUB_TOKEN"], env["SSH_AUTH_SOCK"]), (None, None, None))
        self.assertTrue(env["GH_CONFIG_DIR"].endswith("no-gh"))
        self.assertEqual((env["GIT_CONFIG_KEY_0"], env["GIT_CONFIG_VALUE_0"]), ("credential.helper", ""))

    def test_every_configured_codex_mcp_server_is_disabled_by_name(self):
        os.environ["FAKE_MCP"] = json.dumps([{"name": "github", "enabled": True}, {"name": "files", "enabled": True}])
        self.invoke("triage", "codex")
        argv = self.calls()[-1]["argv"]
        self.assertIn("mcp_servers.github.enabled=false", argv)
        self.assertIn("mcp_servers.files.enabled=false", argv)

    def test_mcp_servers_are_listed_where_each_call_runs(self):
        project = self.tmp / "worktree-with-project-config"
        project.mkdir()
        self.invoke("build", "codex", cwd=project)
        self.assertFalse(any("mcp_servers" in x for x in self.calls()[-1]["argv"]))
        (project / ".fake-mcp.json").write_text(json.dumps([{"name": "added-later"}]))
        self.invoke("build", "codex", cwd=project)
        self.assertIn("mcp_servers.added-later.enabled=false", self.calls()[-1]["argv"])

    def test_codex_is_refused_when_its_mcp_servers_cannot_be_listed(self):
        os.environ["FAKE_MCP"] = "not json"
        with self.assertRaises(live.AgentFailure):
            self.invoke("triage", "codex")
        self.assertFalse(self.log.exists(), "Codex never ran")
        # the attempt is reported to the meter, so the engine charges it and cannot spin on it
        self.assertEqual(self.meter.events, [("before", 28, "triage", "codex"),
                                             ("after", 28, "triage", "codex", "crash")])

    # ---------------------------------------------------------------- answers
    def test_plan_answers_are_mapped_into_engine_types(self):
        p = self.invoke("plan", "codex")
        self.assertEqual([(i.id, i.proof, i.capability) for i in p.items],
                         [("D1", "test", None), ("A1", "owner", "hardware:laptop")])
        self.assertEqual(p.items[1].agent_part, "measure it on this host")
        self.assertEqual((p.zones, p.decisions[0]["choice"], p.notes),
                         (["cursus/labs/tokenizer.html"], "gpt-tokenizer", "plan notes"))
        record = [json.loads(l) for l in (self.tmp / "run" / "agents.jsonl").read_text().splitlines()][-1]
        self.assertEqual((record["role"], record["vendor"], record["issue"], record["ok"], record["outcome"]),
                         ("plan", "codex", 28, True, "answered"))
        self.assertEqual(record["usage"]["input_tokens"], 12)
        self.assertTrue(list((self.tmp / "run" / "calls").glob("*-plan-codex-28.prompt.md")))
        prompt = self.calls()[-1]["prompt"]
        self.assertIn("There is no branch yet", prompt)
        self.assertIn("the plan feedback", prompt)
        self.assertIn("hardware:laptop", prompt, "the planner knows what the host lacks")

    def test_build_answers_are_mapped_into_engine_types(self):
        b = self.invoke("build", "claude")
        self.assertEqual((b.status, b.tests), ("done", ["tests/test_lab.py"]))
        self.assertEqual(b.commands, [CheckSpec(criterion="D1", command="pytest -q tests/test_lab.py", cwd=".",
                                                timeout_s=None)])
        self.assertEqual(b.dispositions, {"tests/test_lab.py::test_speed": "owner-run"})
        self.assertEqual(b.decisions[0]["id"], "layout")
        r = b.requests[0]
        self.assertEqual((r.kind, r.item, r.paths), ("command_change", "D1", []))
        self.assertEqual(r.command, {"criterion": "D1", "command": "pytest -q tests", "cwd": "tests",
                                     "timeout_s": 600, "author": "builder"})
        prompt = self.calls()[-1]["prompt"]
        self.assertIn("fix the edge case", prompt)
        self.assertNotIn("the plan feedback", prompt, "a build gets this round's feedback, not the plan's")
        self.assertIn('"cursus/labs/"', prompt, "the builder sees its plan")

    def test_the_locked_conflict_resolver_is_told_its_files(self):
        self.invoke("resolve_locked", "codex")
        prompt = self.calls()[-1]["prompt"]
        self.assertIn("`checks/shared.sh`", prompt)
        self.assertIn("keep both sides", prompt)

    def test_examine_answers_are_mapped_and_it_runs_in_a_disposable_copy(self):
        e = self.invoke("examine", "codex")
        self.assertEqual((e.certify, e.summary, e.decisions), (False, "one finding", []))
        self.assertEqual(e.verdicts[0]["verdict"], "unmet")
        f = e.findings[0]
        self.assertEqual((f.id, f.item, f.reproduction, f.line, f.status), ("", "D1", "node checks/toggle.mjs", 3, "new"))
        self.assertEqual((e.probes[0].file, e.probes[0].criterion), ("checks/probe_toggle.sh", "D1"))
        self.assertEqual(len(self.agents.ws.disposed), 1)
        call = self.calls()[-1]
        self.assertEqual(Path(call["cwd"]).resolve(), (self.tmp / "scratch").resolve())
        self.assertIn("This is the first examination", call["prompt"])
        self.assertIn("secret exposure", call["prompt"], "the examiner knows the safety invariants")

    def test_a_follow_up_examination_sees_its_memory_and_the_delta(self):
        memory = [{"id": "E28-1-1", "title": "the toggle loses the text", "status": "open"}]
        self.invoke("examine", "claude", since="c" * 40, memory=memory)
        prompt = self.calls()[-1]["prompt"]
        self.assertIn("follow-up examination", prompt)
        self.assertIn("c" * 12, prompt)
        self.assertIn("E28-1-1", prompt)

    def test_decide_and_arbitrate_answers_are_mapped(self):
        d = self.invoke("decide", "codex")
        self.assertEqual((d[0].request, d[0].approve, d[0].dispositions),
                         ("R28-1", True, {"tests/test_lab.py::test_net": "excluded: needs CDN"}))
        self.assertIn("setup/suites.txt", self.calls()[-1]["prompt"])
        r = self.invoke("arbitrate", "claude")
        self.assertEqual((r.upheld, r.reason), (False, "the item does not ask for it"))
        self.assertIn("the item never asks for offline", self.calls()[-1]["prompt"])

    def test_every_prompt_is_sent_without_leftover_placeholders(self):
        for role in ("explore", *READ_ONLY_ROLES, *WORKING_ROLES):
            with self.subTest(role=role):
                self.invoke(role, "claude")
                self.assertNotIn("{{", self.calls()[-1]["prompt"])

    def test_every_prompt_file_renders_with_the_adapter_variables(self):
        keys = ("role", "number", "title", "body", "ledger", "context", "ledger_ids", "feedback", "lacks", "invariants",
                "decisions", "repair", "plan", "branch_note", "files", "base", "head", "scope", "diff", "evidence",
                "memory", "requests", "dispute", "question", "briefing")
        names = [p.stem for p in live.PROMPTS.glob("*.md") if not p.stem.startswith("_")]
        self.assertEqual(sorted(names), sorted(set(live.DEFAULT_ROLES)))
        for name in names:
            self.assertNotIn("{{", live.render(name, **{k: "x" for k in keys}), name)

    # ---------------------------------------------------------------- failures and the meter
    def test_every_attempt_is_metered(self):
        self.invoke("triage", "claude")
        self.assertEqual(self.meter.events, [("before", 28, "triage", "claude"),
                                             ("after", 28, "triage", "claude", "answered")])
        self.invoke("explore", "codex")
        self.assertEqual(self.meter.events[-1], ("after", None, "explore", "codex", "answered"))

    def test_an_answer_off_schema_is_rejected_and_retried_then_fails(self):
        self.answer_with({"status": "finished"})
        with self.assertRaises(live.AgentFailure) as caught:
            self.agents.build("claude", self.req, PLAN, self.tmp, [])
        self.assertEqual(caught.exception.kind, "crash")
        calls = self.calls()
        self.assertEqual(len(calls), 3)
        self.assertIn("Your previous answer was rejected", calls[1]["prompt"])
        self.assertEqual(self.sleeps, [], "schema problems are retried at once")
        self.assertEqual(self.meter.outcomes(), ["answered"] * 3, "an answer is charged even when it is unusable")

    def test_a_crashing_cli_is_retried_with_backoff_then_reported_as_a_crash(self):
        os.environ["FAKE_EXIT"] = "2"
        with self.assertRaises(live.AgentFailure) as caught:
            self.invoke("explore", "claude")
        self.assertEqual((caught.exception.kind, caught.exception.vendor), ("crash", "claude"))
        self.assertEqual(self.sleeps, [30, 90])
        self.assertEqual(self.meter.outcomes(), ["crash"] * 3)

    def test_a_vendor_that_cannot_reach_its_service_is_an_outage(self):
        os.environ["FAKE_EXIT"] = "1"
        os.environ["FAKE_STDERR"] = "API Error: 529 {\"type\":\"overloaded_error\"}"
        with self.assertRaises(live.AgentFailure) as caught:
            self.invoke("examine", "codex")
        self.assertEqual((caught.exception.kind, caught.exception.vendor), ("outage", "codex"))
        self.assertEqual(self.meter.outcomes(), ["outage"] * 3)
        self.assertEqual(len(self.agents.ws.disposed), 1, "the disposable copy goes, whatever happens")

    def test_a_call_that_runs_past_its_timeout_is_a_timeout(self):
        self.agents = self.new_agents("run3", retries=0)
        self.agents.roles["build"].timeout_s = 1
        os.environ["FAKE_SLEEP"] = "20"
        started = time.monotonic()
        with self.assertRaises(live.AgentFailure) as caught:
            self.invoke("build", "claude")
        self.assertLess(time.monotonic() - started, 15)
        self.assertEqual(caught.exception.kind, "timeout")
        self.assertEqual(self.meter.outcomes(), ["timeout"])

    def test_failures_are_classified_from_what_the_cli_printed(self):
        for stderr, code, kind in (("Error: rate limit exceeded", 1, "outage"),
                                   ("stream disconnected before completion", 1, "outage"),
                                   ("getaddrinfo ENOTFOUND api.anthropic.com", 1, "outage"),
                                   ("HTTP 503 Service Unavailable", 1, "outage"),
                                   ("Traceback (most recent call last): KeyError", 1, "crash"),
                                   ("", None, "timeout"), ("", 137, "crash")):
            with self.subTest(stderr=stderr, code=code):
                self.assertEqual(live.classify_failure(code, stderr), kind)

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

    # ---------------------------------------------------------------- settings and schemas
    def test_role_settings_come_from_loop_toml(self):
        roles = live.load_roles()
        self.assertEqual(roles["explore"].effort, "low")
        self.assertEqual(roles["explore"].claude_model, "sonnet")
        self.assertIsNone(roles["explore"].codex_model)
        self.assertEqual(roles["build"].timeout_s, 5400)
        configured = tomllib.loads(live.CONFIG_FILE.read_text())["roles"]
        self.assertEqual(set(configured), set(live.DEFAULT_ROLES))
        self.assertTrue(set(live.DEFAULT_ROLES) <= set(schemas.BY_ROLE))

    def test_every_schema_is_in_the_strict_form_both_vendors_accept(self):
        def strict(schema, path):
            if schema.get("type") == "object":
                self.assertEqual(sorted(schema["required"]), sorted(schema["properties"]), path)
                self.assertIs(schema["additionalProperties"], False, path)
                for key, sub in schema["properties"].items():
                    strict(sub, f"{path}.{key}")
            if "items" in schema:
                strict(schema["items"], f"{path}[]")
        for role, schema in schemas.BY_ROLE.items():
            strict(schema, role)
        for role, answer in ANSWERS.items():
            self.assertEqual(schemas.validate(answer, schemas.BY_ROLE[role]), [], role)


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

    def test_a_retired_check_is_no_longer_locked(self):
        self.commit("tests/test_old.py", "def test_old(): pass\n", "acceptance-checks")
        (self.wt / "tests" / "test_old.py").unlink()
        git("add", "-A", cwd=self.wt)
        git("commit", "-q", "-m", "retire\n\nLoop-Phase: acceptance-checks\nLoop-Unlocks: tests/test_old.py", cwd=self.wt)
        self.commit("tests/test_old.py", "the implementer may reuse the path\n", "implementation")
        self.assertEqual(self.guard().returncode, 0)

    def test_unlocking_one_check_keeps_the_others_locked(self):
        self.commit("tests/test_a.py", "def test_a(): pass\n", "acceptance-checks")
        self.commit("tests/test_b.py", "def test_b(): pass\n", "acceptance-checks")
        git("commit", "-q", "--allow-empty", "-m", "retire a\n\nLoop-Phase: acceptance-checks\nLoop-Unlocks: tests/test_a.py", cwd=self.wt)
        self.commit("tests/test_b.py", "def test_b(): assert True\n", "implementation")
        result = self.guard()
        self.assertEqual(result.returncode, 1)
        self.assertIn("tests/test_b.py was locked", result.stdout)

    # Loop-Locks: lock files already on the branch, which the acceptance-checks commit leaves unchanged

    def trailers(self, phase, **paths):
        """An empty commit carrying `phase` and one Loop-Locks / Loop-Unlocks line per path."""
        lines = [f"Loop-Phase: {phase}"]
        for key, name in (("locks", "Loop-Locks"), ("unlocks", "Loop-Unlocks")):
            lines += [f"{name}: {p}" for p in paths.get(key, ())]
        git("commit", "-q", "--allow-empty", "-m", "lock\n\n" + "\n".join(lines), cwd=self.wt)
        return git("rev-parse", "HEAD", cwd=self.wt)

    def head(self):
        return git("rev-parse", "HEAD", cwd=self.wt)

    def test_a_file_locked_by_trailer_then_changed_by_an_implementation_commit_fails(self):
        self.commit("tests/test_a.py", "def test_a(): pass\n", "implementation")   # the builder wrote it
        locker = self.trailers("acceptance-checks", locks=["tests/test_a.py"])
        self.commit("tests/test_a.py", "def test_a(): assert True\n", "implementation")
        result = self.guard()
        self.assertEqual(result.returncode, 1)
        self.assertIn(f"::error file=tests/test_a.py::tests/test_a.py was locked by acceptance-checks commit "
                      f"{locker[:7]} but changed by {self.head()[:7]}", result.stdout)
        self.assertEqual(result.stdout.count("::error"), 1, "the commit before the lock is not judged")

    def test_a_file_locked_by_trailer_may_change_in_a_later_acceptance_checks_commit(self):
        self.commit("tests/test_a.py", "def test_a(): pass\n", "implementation")
        self.trailers("acceptance-checks", locks=["tests/test_a.py"])
        self.commit("tests/test_a.py", "def test_a(): assert 1\n", "acceptance-checks")
        self.commit("src/a.py", "x = 1\n", "implementation")
        self.assertEqual(self.guard().returncode, 0)

    def test_a_file_locked_by_trailer_and_released_by_loop_unlocks_may_change(self):
        self.commit("tests/test_a.py", "def test_a(): pass\n", "implementation")
        self.trailers("acceptance-checks", locks=["tests/test_a.py"])
        self.trailers("acceptance-checks", unlocks=["tests/test_a.py"])
        self.commit("tests/test_a.py", "def test_a(): assert True\n", "implementation")
        self.assertEqual(self.guard().returncode, 0)

    def test_several_loop_locks_trailers_lock_each_path(self):
        self.commit("tests/test_a.py", "def test_a(): pass\n", "implementation")
        self.commit("tests/test_b.py", "def test_b(): pass\n", "implementation")
        self.trailers("acceptance-checks", locks=["tests/test_a.py", "tests/test_b.py"])
        self.commit("tests/test_b.py", "def test_b(): assert True\n", "implementation")
        self.commit("tests/test_a.py", "def test_a(): assert True\n", "implementation")
        result = self.guard()
        self.assertEqual(result.returncode, 1)
        self.assertIn("tests/test_a.py was locked", result.stdout)
        self.assertIn("tests/test_b.py was locked", result.stdout)

    def test_a_file_both_written_and_named_in_loop_locks_is_reported_once(self):
        (self.wt / "tests").mkdir()
        (self.wt / "tests" / "test_a.py").write_text("def test_a(): pass\n")
        git("add", "-A", cwd=self.wt)
        git("commit", "-q", "-m", "checks\n\nLoop-Phase: acceptance-checks\nLoop-Locks: tests/test_a.py", cwd=self.wt)
        self.commit("tests/test_a.py", "def test_a(): assert True\n", "implementation")
        result = self.guard()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout.count("::error"), 1)

    def test_loop_locks_on_a_commit_that_is_not_acceptance_checks_locks_nothing(self):
        self.commit("tests/test_a.py", "def test_a(): pass\n", "implementation")
        self.trailers("implementation", locks=["tests/test_a.py"])
        self.commit("tests/test_a.py", "def test_a(): assert True\n", "implementation")
        self.assertEqual(self.guard().returncode, 0)


if __name__ == "__main__":
    unittest.main()
