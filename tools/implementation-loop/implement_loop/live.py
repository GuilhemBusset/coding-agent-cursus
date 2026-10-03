"""Live agents: one fresh headless Claude Code (`claude -p`) or Codex (`codex exec`) process per
call, with per-role permissions, schema-validated answers, retries, and a full call record.

Read-only roles (explore, propose, audit, critique, judge, review) get read-only tools (Claude)
or the read-only sandbox (Codex). Writing roles (write_checks, implement) may edit their worktree
and run commands, but cannot commit, push or call `gh`. Finding verification runs in a disposable
worktree that is deleted afterwards. Every prompt and answer is kept under the run directory.
"""

from __future__ import annotations

import itertools
import json
import os
import signal
import subprocess
import threading
import time
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import schemas
from .agents import Design, DesignRequest, ImplementResult, Objection, Proposal, ReviewResult
from .model import CheckSpec, Finding

PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
CONFIG_FILE = Path(__file__).resolve().parent.parent / "loop.toml"
DIFF_LIMIT = 60_000


class AgentFailure(RuntimeError):
    pass


class AgentStopped(RuntimeError):
    """The run was stopped while this agent worked; the step keeps its phase and resumes later."""


@dataclass
class RoleSettings:
    effort: str = "high"
    timeout_s: int = 1800
    claude_model: str | None = None
    codex_model: str | None = None


DEFAULT_ROLES = {
    "explore": RoleSettings(effort="low", timeout_s=900, claude_model="sonnet"),
    "propose": RoleSettings(timeout_s=1800),
    "audit": RoleSettings(timeout_s=1200),
    "critique": RoleSettings(timeout_s=1200),
    "judge": RoleSettings(timeout_s=1800),
    "write_checks": RoleSettings(timeout_s=2400),
    "implement": RoleSettings(timeout_s=5400),
    "review": RoleSettings(timeout_s=2400),
    "verify_finding": RoleSettings(timeout_s=1800),
}
READ_ONLY = {"explore", "propose", "audit", "critique", "judge", "review"}
# Writers that may need the network (installing or locking dependencies, fetching references).
NETWORK_ROLES = {"implement", "verify_finding"}
CLAUDE_READ_TOOLS = "Read,Glob,Grep"
CLAUDE_WRITE_TOOLS = "Read,Glob,Grep,Edit,Write,Bash"
# Convenience only: Claude Code matches these as command prefixes, so `git add x && git commit`
# slips past. The real boundaries are agent_env() (no GitHub credentials) and the engine, which
# absorbs any commit an agent makes and verifies the exact head it merges.
CLAUDE_DENY = ["Bash(git commit *)", "Bash(git push *)", "Bash(git reset *)", "Bash(git rebase *)",
               "Bash(git checkout *)", "Bash(git switch *)", "Bash(git merge *)", "Bash(gh *)"]
ROLE_FOCUS = {
    "cross": "You are from a different vendor than the implementer. Look for anything that makes the result "
             "wrong while the checks are green: misread requirements, weak or special-cased checks, broken "
             "edge cases, files the design did not ask for.",
    "acceptance": "Check every ledger item against the evidence and the diff. Is each item actually met, not "
                  "just its check green? Is anything the issue asks for missing?",
    "visual": "Look at the rendered screenshots the page checker wrote under artifacts/html-pages/ and at the "
              "HTML. Does the page follow tools/html-pages/GUIDE.md, read clearly, and work at desktop and "
              "mobile widths? Are interactive controls usable from the keyboard?",
}


CREDENTIAL_VARS = ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN", "SSH_AUTH_SOCK")


def agent_env(no_gh_dir: Path) -> dict[str, str]:
    """The environment agents run in: no GitHub credentials, so they cannot push, call the
    GitHub API, or touch issues and pull requests, whatever their own permission settings allow."""
    env = {k: v for k, v in os.environ.items() if k not in CREDENTIAL_VARS}
    no_gh_dir.mkdir(parents=True, exist_ok=True)
    env["GH_CONFIG_DIR"] = str(no_gh_dir)          # gh finds no stored login
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_CONFIG_COUNT"] = "1"                 # an empty credential.helper clears every helper
    env["GIT_CONFIG_KEY_0"] = "credential.helper"
    env["GIT_CONFIG_VALUE_0"] = ""
    return env


def load_roles(path: Path = CONFIG_FILE) -> dict[str, RoleSettings]:
    roles = {k: RoleSettings(**asdict(v)) for k, v in DEFAULT_ROLES.items()}
    if path.exists():
        for role, values in tomllib.loads(path.read_text()).get("roles", {}).items():
            if role in roles:
                for key, value in values.items():
                    if hasattr(roles[role], key):
                        setattr(roles[role], key, value or None if key.endswith("_model") else value)
    return roles


def render(name: str, **values) -> str:
    text = (PROMPTS / f"{name}.md").read_text()
    if name != "explore":
        text = (PROMPTS / "_common.md").read_text() + "\n---\n\n" + text
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text


class LiveAgents:
    def __init__(self, operator: str, run_dir: Path, workspace, roles: dict[str, RoleSettings] | None = None,
                 claude_bin: str = "claude", codex_bin: str = "codex", retries: int = 2,
                 backoff_s: tuple[float, ...] = (30, 90), sleep=time.sleep):
        if operator not in ("claude", "codex"):
            raise ValueError("operator must be 'claude' or 'codex'")
        self.operator = operator
        self.other = "codex" if operator == "claude" else "claude"
        self.ws = workspace
        self.roles = roles or load_roles()
        self.bins = {"claude": claude_bin, "codex": codex_bin}
        self.retries, self.backoff, self.sleep = retries, backoff_s, sleep
        self.no_gh_dir = run_dir / "no-gh"
        self.calls_dir = run_dir / "calls"
        self.calls_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = run_dir / "agents.jsonl"
        self._seq = itertools.count(len(list(self.calls_dir.glob("*.prompt.md"))) + 1)
        self._lock = threading.Lock()
        self._active: set[subprocess.Popen] = set()
        self._stopped = False
        self._codex_mcp: list[str] | None = None

    # ---------------------------------------------------------------- process control
    def terminate_all(self) -> None:
        """Stop every running agent (its whole process group)."""
        self._stopped = True
        with self._lock:
            procs = list(self._active)
        for proc in procs:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    def _spawn(self, cmd: list[str], prompt: str, cwd: Path, timeout: int) -> tuple[int | None, str, str]:
        if self._stopped:
            raise AgentStopped("run stopped")
        proc = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, start_new_session=True, env=agent_env(self.no_gh_dir))
        with self._lock:
            self._active.add(proc)
        try:
            out, err = proc.communicate(prompt, timeout=timeout)
            code = proc.returncode
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            out, err = proc.communicate()
            code = None
        finally:
            with self._lock:
                self._active.discard(proc)
        if self._stopped:
            raise AgentStopped("run stopped")
        return code, out or "", err or ""

    def _codex_mcp_off(self) -> list[str]:
        """`-c` overrides disabling every MCP server Codex would load: inherited MCP tools are not
        bound by the sandbox. An empty-table override does not clear servers defined in config
        files (tables merge), so each one is disabled by name. Fails closed if they can't be listed."""
        if self._codex_mcp is None:
            try:
                proc = subprocess.run([self.bins["codex"], "mcp", "list", "--json"], cwd=self._root(),
                                      capture_output=True, text=True, timeout=60, env=agent_env(self.no_gh_dir))
                servers = json.loads(proc.stdout[proc.stdout.index("["):]) if proc.returncode == 0 else None
            except (OSError, ValueError, subprocess.TimeoutExpired):
                servers = None
            if not isinstance(servers, list):
                raise AgentFailure("could not list Codex MCP servers to disable them; refusing to run Codex")
            self._codex_mcp = sorted(s["name"] for s in servers if isinstance(s, dict) and s.get("name"))
        return [arg for name in self._codex_mcp for arg in ("-c", f"mcp_servers.{name}.enabled=false")]

    # ---------------------------------------------------------------- one call
    def _command(self, vendor: str, role: str, cwd: Path, schema: dict, out_file: Path) -> list[str]:
        s = self.roles[role]
        write = role not in READ_ONLY
        if vendor == "claude":
            tools = CLAUDE_WRITE_TOOLS if write else CLAUDE_READ_TOOLS + (",WebFetch,WebSearch" if role == "explore" else "")
            cmd = [self.bins["claude"], "-p", "--output-format", "json", "--json-schema", json.dumps(schema),
                   "--no-session-persistence", "--strict-mcp-config", "--effort", s.effort,
                   "--tools", tools, "--allowedTools", tools,
                   "--permission-mode", "acceptEdits" if write else "dontAsk"]
            if write:
                cmd += ["--disallowedTools", *CLAUDE_DENY]
            if s.claude_model:
                cmd += ["--model", s.claude_model]
            return cmd
        schema_file = out_file.with_suffix(".schema.json")
        schema_file.write_text(json.dumps(schema))
        cmd = [self.bins["codex"], "exec", "-C", str(cwd), "--json", "--ephemeral",
               "--output-schema", str(schema_file), "-o", str(out_file),
               "-c", 'approval_policy="never"', "-c", f'model_reasoning_effort="{s.effort}"',
               *self._codex_mcp_off(),
               "--sandbox", "workspace-write" if write else "read-only"]
        if role in NETWORK_ROLES:
            cmd += ["-c", "sandbox_workspace_write.network_access=true"]
        if s.codex_model:
            cmd += ["-m", s.codex_model]
        return cmd + ["-"]

    @staticmethod
    def _parse(vendor: str, stdout: str, out_file: Path) -> tuple[dict | None, dict]:
        meta: dict = {}
        if vendor == "claude":
            try:
                data = json.loads(stdout)
            except ValueError:
                return None, {"parse_error": stdout[-300:]}
            meta = {"cost_usd": data.get("total_cost_usd"), "usage": data.get("usage"), "is_error": data.get("is_error"),
                    "denials": len(data.get("permission_denials") or [])}
            value = data.get("structured_output")
            if value is None and isinstance(data.get("result"), str):
                try:
                    value = json.loads(data["result"])
                except ValueError:
                    value = None
            return value, meta
        for line in stdout.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("type") == "turn.completed" and "usage" in event:
                meta["usage"] = event["usage"]
        try:
            return json.loads(out_file.read_text()), meta
        except (OSError, ValueError):
            return None, meta

    def call(self, vendor: str, role: str, cwd: Path, prompt: str, issue: int | None = None) -> dict:
        schema = schemas.BY_ROLE[role]
        s = self.roles[role]
        last_error = ""
        for attempt in range(self.retries + 1):
            seq = next(self._seq)
            stem = self.calls_dir / (f"{seq:04d}-{role}-{vendor}" + (f"-{issue}" if issue else ""))
            out_file = stem.with_suffix(".out.json")
            full_prompt = prompt + (f"\n\nYour previous answer was rejected: {last_error}. Answer again, matching the schema."
                                    if last_error and "schema" in last_error else "")
            stem.with_suffix(".prompt.md").write_text(full_prompt)
            started = time.monotonic()
            code, out, err = self._spawn(self._command(vendor, role, cwd, schema, out_file), full_prompt, cwd, s.timeout_s)
            value, meta = self._parse(vendor, out, out_file)
            if vendor == "claude":
                out_file.write_text(out)
            problems = schemas.validate(value, schema) if value is not None else ["no structured answer"]
            record = {"seq": seq, "role": role, "vendor": vendor, "issue": issue, "attempt": attempt + 1,
                      "exit": code, "seconds": round(time.monotonic() - started, 1), "ok": code == 0 and not problems,
                      "problems": problems[:5], "stderr_tail": err[-400:], **meta}
            with self._lock, self.log_path.open("a") as f:
                f.write(json.dumps(record, default=str) + "\n")
            if code == 0 and not problems:
                return value
            if code == 0:
                last_error = "it did not match the schema: " + "; ".join(problems[:3])
            else:
                last_error = f"{vendor} exited {code}: {err.strip()[-300:]}"
                if attempt < self.retries:
                    self.sleep(self.backoff[min(attempt, len(self.backoff) - 1)])
        raise AgentFailure(f"{vendor} {role} failed after {self.retries + 1} attempts: {last_error}")

    # ---------------------------------------------------------------- prompt pieces
    @staticmethod
    def _issue_vars(req: DesignRequest, role: str) -> dict:
        ledger = "\n".join(f"- {i.id} ({i.section}): {i.text}" for i in req.spec.ledger)
        feedback = ("Feedback you must address:\n" + "\n".join(f"- {f}" for f in req.feedback)) if req.feedback else ""
        return {"role": role, "number": req.issue.number, "title": req.issue.title, "body": req.issue.body,
                "ledger": ledger or "(no checkboxes)", "context": req.context or "(none)",
                "ledger_ids": ", ".join(i.id for i in req.spec.ledger), "feedback": feedback, "lens": req.lens}

    @staticmethod
    def _proposal_text(proposals: list[Proposal]) -> str:
        return "\n\n".join(f"Proposal {p.author}:\n" + json.dumps(_proposal_json(p), indent=1) for p in proposals)

    def _root(self) -> Path:
        return self.ws.coord_path()

    # ---------------------------------------------------------------- the Agents interface
    def explore(self, vendor, question, briefing):
        prompt = render("explore", question=question, briefing=briefing)
        return self.call(vendor, "explore", self._root(), prompt)["notes"]

    def propose(self, vendor, req, author):
        prompt = render("propose", author=author, **self._issue_vars(req, "proposer"))
        value = self.call(vendor, "propose", self._root(), prompt, req.issue.number)
        return Proposal(author=author, decisions={d["id"]: d["choice"] for d in value["decisions"]},
                        checks=[CheckSpec(**c) for c in value["checks"]], files=value["files"],
                        check_files=value["check_files"], open_questions=value["open_questions"])

    def _objections(self, vendor, role, req, proposals, extra: str = "") -> list[Objection]:
        prompt = render(role, proposals=self._proposal_text(proposals), objections=extra or "(none)",
                        **self._issue_vars(req, "criteria auditor" if role == "audit" else "critic"))
        value = self.call(vendor, role, self._root(), prompt, req.issue.number)
        return [Objection(**o) for o in value["objections"]]

    def audit(self, vendor, req, proposals):
        return self._objections(vendor, "audit", req, proposals)

    def critique(self, vendor, req, proposals):
        return self._objections(vendor, "critique", req, proposals)

    def judge(self, vendor, req, proposals, objections):
        prompt = render("judge", proposals=self._proposal_text(proposals),
                        objections=json.dumps([asdict(o) for o in objections], indent=1) or "[]",
                        **self._issue_vars(req, "judge"))
        v = self.call(vendor, "judge", self._root(), prompt, req.issue.number)
        return Design(decisions={d["id"]: d["choice"] for d in v["decisions"]}, checks=[CheckSpec(**c) for c in v["checks"]],
                      files=v["files"], check_files=v["check_files"], notes=v["notes"],
                      criterion_disputes=v["criterion_disputes"])

    def write_checks(self, vendor, req, design, worktree):
        prompt = render("write_checks", design=json.dumps(_design_json(design), indent=1),
                        check_files=", ".join(f"`{p}`" for p in design.check_files), **self._issue_vars(req, "check author"))
        self.call(vendor, "write_checks", worktree, prompt, req.issue.number)

    def implement(self, vendor, req, design, worktree, feedback):
        commands = "\n".join(f"  - `{c.command}` (from `{c.cwd}`)" for c in design.checks if c.kind == "command" and c.command)
        req = DesignRequest(issue=req.issue, spec=req.spec, context=req.context, lens=req.lens, feedback=feedback)
        prompt = render("implement", design=json.dumps(_design_json(design), indent=1),
                        files=", ".join(f"`{p}`" for p in design.files), check_files=", ".join(f"`{p}`" for p in design.check_files),
                        commands=commands or "  (none)", **self._issue_vars(req, "implementer"))
        v = self.call(vendor, "implement", worktree, prompt, req.issue.number)
        return ImplementResult(status=v["status"], note=v["note"])

    def review(self, vendor, role, req, design, worktree, base_sha, head_sha, evidence):
        diff = subprocess.run(["git", "diff", f"{base_sha}..{head_sha}"], cwd=worktree, capture_output=True, text=True).stdout
        if len(diff) > DIFF_LIMIT:
            diff = diff[:DIFF_LIMIT] + f"\n[diff truncated at {DIFF_LIMIT} characters; read the files directly]"
        compact = [{k: e.get(k) for k in ("criterion", "kind", "command", "passed", "exit_code", "note", "tests")} |
                   {"output_tail": (e.get("output_tail") or "")[-800:]} for e in evidence]
        artifact_ids = ", ".join(c.criterion for c in design.checks if c.kind == "artifact") or "(none)"
        prompt = render("review", review_role=role, role_focus=ROLE_FOCUS[role], design=json.dumps(_design_json(design), indent=1),
                        base=base_sha[:12], head=head_sha[:12], diff=diff or "(empty)", evidence=json.dumps(compact, indent=1),
                        artifact_ids=artifact_ids, **self._issue_vars(req, f"{role} reviewer"))
        try:
            v = self.call(vendor, "review", worktree, prompt, req.issue.number)
        except AgentFailure:
            return None
        findings = [Finding(reviewer=role, **f) for f in v["findings"]]
        return ReviewResult(findings=findings, coverage={c["criterion"]: c["met"] for c in v["coverage"]})

    def verify_finding(self, vendor, req, worktree, finding):
        with self.ws.disposable(worktree) as scratch:
            prompt = render("verify_finding", finding=json.dumps(asdict(finding), indent=1),
                            **self._issue_vars(req, "finding verifier"))
            try:
                v = self.call(vendor, "verify_finding", scratch, prompt, req.issue.number)
            except AgentFailure:
                return None  # no verdict is not a "not reproduced"
        return bool(v["reproduced"])


def _proposal_json(p: Proposal) -> dict:
    return {"decisions": p.decisions, "files": p.files, "check_files": p.check_files,
            "checks": [asdict(c) for c in p.checks], "open_questions": p.open_questions}


def _design_json(d: Design) -> dict:
    return {"decisions": d.decisions, "files": d.files, "check_files": d.check_files,
            "checks": [asdict(c) for c in d.checks], "notes": d.notes}
