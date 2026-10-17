"""The per-issue state machine and the scheduling loop (ADR 0012).

Each issue moves through: pending -> plan -> planned -> build -> verify -> examine -> land ->
merged -> delivered | done. Two vendors hold two keys: the **builder** (the operator's vendor)
plans, writes the code, its tests and the commands that prove each item; the **examiner** (the
other vendor) triages the plan, examines and probes the exact head, approves or refuses the
builder's typed requests, and certifies the head that may land. The engine owns git, the
trusted verifier, the gates and every merge, and derives its bookkeeping from what happened.

A run never waits for a person and never parks:
- a failed verification or a blocking finding is one more build round; two rounds that change
  nothing bring a replan on the branch, two more end the issue `failed`;
- a merge queue another run holds, an outage, a CI check with no verdict or an environment the
  doctor can repair is a **wait** that resumes by itself (in this run, or under the supervisor);
- every answered agent call is charged to the issue's ceiling, every timeout or crash to its
  infrastructure budget; spending either ends the issue `failed`, filed as a loop fault, which a
  new engine version resumes once;
- an item that needs a capability the host lacks becomes an owner obligation; one that needs
  another issue waits for it in the run, or becomes a deferred obligation.

Steps run on a thread pool, so one issue can be examined while another builds and a third
plans. Landing is serialized through a repo-wide merge-queue claim, issues through per-issue
claims, so two runs never land at once or work the same issue.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import threading
import time
import traceback
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import asdict, replace
from pathlib import Path
from typing import Callable

from . import VERSION, gate, graph, issue_parser, report, scheduler, verify
from .agents import AgentFailure, AgentStopped, Agents, CeilingReached, IssueRequest
from .config import Config, ceiling, INFRA_PREFIXES, is_protected, is_safety_surface
from .github import GitHub, GitHubError
from .graph import Plan
from .model import (AGENT_PROOFS, IN_RUN_WAITS, SATISFIES_DEPENDENTS, TERMINAL, WAIT_CI, WAIT_CLAIM,
                    WAIT_ENGINE, WAIT_ENVIRONMENT, WAIT_GITHUB, WAIT_MERGE_QUEUE, WAIT_OUTAGE, WAIT_RUN_CEILING,
                    WRITING_PHASES, CheckSpec, Finding, Issue, IssueState, Phase)
from .state import FaultOutbox, RepoClaims, RunStore
from .workspace import AgentCall, GitError, MergeConflict, UpdateResult, Workspace

try:   # GitHubUnavailable arrives with the retrying GitHub client
    from .github import GitHubUnavailable
except ImportError:   # pragma: no cover - older github.py
    class GitHubUnavailable(GitHubError):
        pass

LABELS = {
    "loop:plan": ("C5DEF5", "implement loop: planning"),
    "loop:building": ("FBCA04", "implement loop: building or verifying"),
    "loop:examine": ("D4C5F9", "implement loop: examined by the other vendor"),
    "loop:landing": ("0E8A16", "implement loop: PR open, merging"),
    "loop:merged": ("BFDADC", "implement loop: merged, verifying on main"),
    "loop:delivered": ("F9D0C4", "implement loop: merged; owner obligations or deferred items remain"),
    "loop:waiting": ("EDEDED", "implement loop: waiting; resumes by itself"),
    "loop:failed": ("B60205", "implement loop: not delivered; filed as a loop fault"),
}
DEFERRED_LABEL = ("loop:deferred", "C2E0C6", "implement loop: an item waits for another issue")
FOLLOWUP_LABEL = ("loop:follow-up", "BFD4F2", "implement loop: non-blocking findings to consider")
LEGACY_LABELS = ("loop:awaiting-human", "loop:needs-human", "loop:parked", "loop:design", "loop:review")
ENGINE_BUG_LABEL = ("loop:engine-bug", "5319E7", "implement loop: a fault in the loop's own engine")
PHASE_LABEL = {
    Phase.PLAN: "loop:plan", Phase.PLANNED: "loop:plan",
    Phase.BUILD: "loop:building", Phase.VERIFY: "loop:building", Phase.EXAMINE: "loop:examine",
    Phase.LAND: "loop:landing", Phase.MERGED: "loop:merged", Phase.DELIVERED: "loop:delivered",
    Phase.WAITING: "loop:waiting", Phase.FAILED: "loop:failed",
}
EXPLORE_QUESTIONS = (
    "The issue graph and acceptance criteria: what must be true when this run is done?",
    "Existing material and conventions these issues must follow (ADRs, AGENTS.md, guides).",
    "Build, check and CI tooling: how is work validated in this repo today?",
    "External references the issues cite: what do they establish that the work depends on?",
)
MERGE_QUEUE = "merge-queue"
# Output that means the host cannot run a check, whatever the implementation does.
ENVIRONMENT_FAILURE = re.compile(
    r"error while loading shared libraries|Host system is missing dependencies|Executable doesn't exist at"
    r"|No module named pytest|\b(uv|node|npx|npm|python3): (command )?not found", re.IGNORECASE)
CI_NO_VERDICT = (None, "missing", "pending", "stale", "cancelled", "startup_failure")
CONFLICT_MARKER = re.compile(r"^(<{7}|>{7})( |$)", re.MULTILINE)


class Engine:
    def __init__(self, plan: Plan, store: RunStore, gh: GitHub, ws: Workspace, agents: Agents, cfg: Config,
                 repo_root: Path, log: Callable[[str], None] = print, sleep: Callable[[float], None] = time.sleep,
                 environment: dict | None = None, invoked_at: float | None = None, policy: dict | None = None):
        self.plan, self.store, self.gh, self.ws, self.agents, self.cfg = plan, store, gh, ws, agents, cfg
        self.repo_root = repo_root
        self.log, self.sleep = log, sleep
        self.caps = cfg.caps
        self.claims = RepoClaims(repo_root)
        self.faults = FaultOutbox(repo_root)
        self.owner = f"run-{plan.root}"
        self.op, self.other = agents.operator, agents.other
        environment = environment or {}
        self.env_fingerprint: str | None = environment.get("fingerprint")
        self.check_env: dict[str, str] = dict(environment.get("check_env") or {})
        policy = policy or {}
        self.lacks: list[str] = sorted(policy.get("lacks", []))
        self.invariants: tuple[str, ...] = tuple(policy.get("invariants") or gate.DEFAULT_INVARIANTS)
        self.admit = bool(policy.get("admit_prerequisites", plan.mode == "epic"))
        self.repair = bool(policy.get("repair", False))
        self._accept_lock = threading.Lock()   # post-merge verification uses the one coord worktree
        self._meter_lock = threading.Lock()
        self._polling: dict[int, float] = {}
        self.invoked_at = invoked_at if invoked_at is not None else time.time()
        self.run_calls = 0
        agents.meter = self

    # ------------------------------------------------------------------ public
    def run(self) -> dict:
        with self.store.lock():
            if self.store.clear_stop(older_than=self.invoked_at):
                self.store.event("stale_stop_cleared")
            self.store.event("run_started", root=self.plan.root, mode=self.plan.mode, work=self.plan.work,
                             operator=self.op, other=self.other, version=VERSION, environment=self.env_fingerprint,
                             repair=self.repair, admit=self.admit)
            self._ensure_labels()
            self._reconcile()
            stopped = False
            try:
                self._context()
                stopped = self._loop()
            except CeilingReached as e:   # the run's own ceiling, reached while gathering context
                self.store.event("run_ceiling", error=str(e))
            finally:
                self._release_claims()
            self._reconcile_delivered()
            self._flush_faults()
            summary = self._summary(stopped)
            self._post_run_summary()
            self.store.event("run_finished", **summary)
            return summary

    # ------------------------------------------------------------------ the meter (agents.meter)
    def _ceiling(self, n: int) -> int:
        issue = self.plan.issues[n]
        spec = self.plan.specs[n]
        st = self.store.issue(n)
        zones = (st.plan or {}).get("zones") or spec.declared_paths
        infra = any(z.startswith(INFRA_PREFIXES) for z in zones) or "loop:infra" in issue.labels
        return ceiling(issue.size, infra) + st.ceiling_bonus

    def _run_ceiling(self) -> int:
        return int(sum(ceiling(self.plan.issues[n].size, False) for n in self.plan.work)
                   * self.caps.run_ceiling_factor) + 8   # + the explorers

    def before(self, issue: int | None, role: str, vendor: str) -> None:
        """Refuse a call the issue's or the run's ceiling no longer covers."""
        with self._meter_lock:
            if self.run_calls >= self._run_ceiling():
                raise CeilingReached(f"the run's ceiling of {self._run_ceiling()} calls is spent", scope="run")
            if issue is None or issue not in self.plan.issues:
                return
            st = self.store.issue(issue)
            if st.calls >= self._ceiling(issue):
                raise CeilingReached(f"#{issue}'s ceiling of {self._ceiling(issue)} calls is spent")
            if st.infra >= self.caps.infra_budget:
                raise CeilingReached(f"#{issue}'s infrastructure budget of {self.caps.infra_budget} failed attempts is spent")

    def after(self, issue: int | None, role: str, vendor: str, outcome: str) -> None:
        """Charge an attempt: an answer to the work ceiling, a timeout or crash to the
        infrastructure budget; an outage is charged to neither (the issue waits for it)."""
        with self._meter_lock:
            if outcome == "answered":
                self.run_calls += 1
            if issue is None or issue not in self.plan.issues:
                return
            st = self.store.issue(issue)
            if outcome == "answered":
                st.calls += 1
            elif outcome in ("timeout", "crash"):
                st.infra += 1
            self.store.put(st)
            self.store.event("agent_attempt", issue=issue, role=role, vendor=vendor, outcome=outcome,
                             calls=st.calls, infra=st.infra)

    # ------------------------------------------------------------------ setup
    def _ensure_labels(self) -> None:
        for name, (color, desc) in LABELS.items():
            self._safe(self.gh.ensure_label, name, color, desc)
        for name, color, desc in (DEFERRED_LABEL, FOLLOWUP_LABEL):
            self._safe(self.gh.ensure_label, name, color, desc)

    def _reconcile(self) -> None:
        for n in list(self.plan.work):
            st = self.store.issue(n)
            spec = self.plan.specs[n]
            if st.wait and st.wait.get("kind") == "legacy":
                self._migrate(st)
            if not self._restore_branch(n):
                continue
            st = self.store.issue(n)
            if st.worktree and (Path(st.worktree) / ".git").exists():
                self._recover_worktree(n, Path(st.worktree))
            if st.body_hash and st.body_hash != spec.body_hash:
                if st.phase in (Phase.MERGED, Phase.DELIVERED, Phase.DONE):
                    self._new_round(st, ["the issue was edited after its work was merged; deliver the edited version"],
                                    owner_edit=True)
                else:
                    self.store.event("requirements_changed", issue=n, previous_phase=st.phase.value)
                    self._owner_edit(st)
            elif st.phase == Phase.DONE:
                self._new_round(st, ["the issue was reopened after it was closed; find what is missing and deliver it"],
                                owner_edit=True)
            elif st.phase == Phase.WAITING:
                self._maybe_resume(st)
            elif st.phase == Phase.FAILED:
                self._maybe_revive(st)
            elif st.phase in (Phase.PLANNED, Phase.BUILD, Phase.VERIFY, Phase.EXAMINE, Phase.LAND) and not st.plan:
                st.phase = Phase.PENDING
            st.body_hash = spec.body_hash
            st.branch = st.branch or spec.branch or f"loop/issue-{n}"
            self._declare(n, st)
            self.store.put(st)

    def _declare(self, n: int, st: IssueState) -> None:
        """What the scheduler sees an issue own: its zones, approved paths and tests."""
        if st.plan:
            spec = self.plan.specs[n]
            spec.declared_paths = sorted(set(st.plan.get("zones", [])) | {g["path"] for g in st.grants}
                                         | set(st.tests) | set(st.probes)) or spec.declared_paths

    def _migrate(self, st: IssueState) -> None:
        """State an earlier engine wrote (ADR 0008/0011): a parked issue resumes; a design becomes
        the starting point of a plan, its locked checks become the builder's tests (released in
        the CI guard at the next build), and nothing already written is lost."""
        legacy = st.wait or {}
        design = legacy.get("design") or {}
        st.wait = None
        old_tests = sorted(set(design.get("check_files", [])) | {f for f in legacy.get("locked", {})
                                                                  if Path(f).suffix in (".py", ".mjs", ".js", ".sh")})
        if old_tests:
            st.tests = sorted(set(st.tests) | set(old_tests))
            st.feedback = list(st.feedback) + [f"An earlier version of the loop wrote these tests on your branch: "
                                               f"{', '.join(old_tests)}. They are yours now; keep, fix or replace them."]
            st.requests.append({"id": "legacy-unlock", "kind": "legacy_unlock", "paths": sorted(legacy.get("locked", {})),
                                "status": "pending", "detail": "release an earlier engine's locked checks"})
        for f in design.get("files", []):
            st.grants.append({"path": f, "source": "earlier design", "protected": False})
        if legacy.get("reason"):
            st.feedback.append(f"An earlier version of the loop set this issue aside: {str(legacy['reason'])[:600]}")
        if st.phase not in (Phase.MERGED, Phase.DELIVERED, Phase.DONE):
            st.phase = Phase.PENDING
        st.locked = {}
        self.store.event("migrated", issue=st.number, park_kind=legacy.get("park_kind"), tests=old_tests)
        self.store.put(st)

    def _restore_branch(self, n: int) -> bool:
        """A worktree whose branch was deleted from under it gets its branch back from its own
        history. Without such evidence the issue starts a new round on a new branch: the work
        is lost, never guessed, and the issue carries on. False when a new round was started."""
        st = self.store.issue(n)
        wt = Path(st.worktree) if st.worktree else self.ws.dir / f"issue-{n}"
        if not (wt / ".git").exists():
            return True
        anchors = [st.base_sha, st.head_sha, st.verified_sha, st.examined_sha, st.certified_sha]
        try:
            restored = self.ws.restore_branch(wt, [a for a in anchors if a])
        except GitError as e:
            self.store.event("branch_restore_failed", issue=n, error=str(e)[:300])
            self._new_round(st, [f"the branch {st.branch} was lost and could not be restored from its history; "
                                 f"start again from main"], owner_edit=False)
            st.phase = Phase.PENDING
            self.store.put(st)
            return False
        if restored:
            self.store.event("branch_restored", issue=n, branch=restored[0].removeprefix("refs/heads/"), sha=restored[1])
        return True

    def _recover_worktree(self, n: int, wt: Path) -> None:
        try:
            self.ws.reattach(wt)
            op = self.ws.abort_in_progress(wt)
        except GitError as e:
            self.store.event("worktree_recovery_failed", issue=n, error=str(e)[:300])
            return
        if op:
            self.store.event("worktree_recovered", issue=n, operation=op, head=self.ws.head(wt))

    def _maybe_resume(self, st: IssueState) -> None:
        """A wait ends when what it waits for may have changed. The supervisor launches a run
        only once an outage is over and runs the doctor (which repairs the environment) first."""
        w = st.wait or {}
        kind = w.get("kind")
        resume = (kind in (WAIT_MERGE_QUEUE, WAIT_CLAIM, WAIT_CI, WAIT_GITHUB, WAIT_OUTAGE, WAIT_RUN_CEILING, "prerequisite")
                  or (kind == WAIT_ENVIRONMENT and (self.env_fingerprint is None or w.get("env") != self.env_fingerprint))
                  or (kind == WAIT_ENGINE and w.get("version") != VERSION))
        if not resume:
            return
        st.phase = Phase(w.get("resume") or Phase.PENDING.value)
        if st.phase in (Phase.PLANNED, Phase.BUILD, Phase.VERIFY, Phase.EXAMINE, Phase.LAND) and not st.plan:
            st.phase = Phase.PENDING
        st.wait = None
        self.store.event("resumed", issue=st.number, wait=kind, phase=st.phase.value)

    def _maybe_revive(self, st: IssueState) -> None:
        """A failed issue resumes once, with a fresh ceiling, on a new engine version: the loop
        repairs itself (as it did for #74 and #78) and tries again."""
        f = st.fail or {}
        if f.get("version") == VERSION or f.get("resumed"):
            return
        st.ceiling_bonus += st.calls
        st.infra = st.unproductive = 0
        st.replans = 0
        st.fail = {**f, "resumed": True}
        st.phase = Phase.BUILD if st.plan and st.worktree else Phase.PENDING
        st.feedback = [f"An earlier attempt failed ({f.get('cause')}): {str(f.get('detail'))[:500]}. "
                       f"A new engine version gives it one more try."]
        self.store.event("revived", issue=st.number, cause=f.get("cause"), phase=st.phase.value)

    def _owner_edit(self, st: IssueState) -> None:
        """The owner edited the issue: new evidence. Plan again on the branch, with the previous
        decisions as a starting point; budgets are reset; tests stay locked."""
        notes = ["The owner edited the issue; plan for the edited version, on your branch."]
        if st.decisions:
            notes.append("Decisions so far, to keep where they still fit: " + json.dumps(st.decisions)[:1500])
        st.plan = None
        st.feedback = notes
        st.calls = st.infra = st.unproductive = st.replans = st.ceiling_bonus = 0
        st.fix_forwards = st.reverts = st.merge_refusals = 0
        st.signature = ""
        st.certified_sha = st.verified_sha = None
        st.fail = st.wait = None
        st.phase = Phase.PENDING

    def _context(self) -> None:
        if self.store.state.get("context"):
            return
        briefing = report.render_briefing(self.plan)
        with ThreadPoolExecutor(max_workers=self.caps.max_parallel_agents) as pool:
            notes = list(pool.map(lambda q: self.agents.explore(self.op, q, briefing), EXPLORE_QUESTIONS))
        self.store.state["context"] = "\n\n".join(notes)
        self.store.save()
        self.store.event("context_gathered", explorers=len(notes))

    # ------------------------------------------------------------------ loop
    def _loop(self) -> bool:
        running: dict[int, Future] = {}
        stopped = False
        with ThreadPoolExecutor(max_workers=self.caps.max_parallel_agents) as pool:
            while True:
                for n, fut in list(running.items()):
                    if fut.done():
                        del running[n]
                        self._finished(n, fut.exception())
                if self.store.stop_requested():
                    if not stopped:
                        self.store.event("stop_requested")
                        stopped = True
                        terminate = getattr(self.agents, "terminate_all", None)
                        if terminate:
                            terminate()
                    if not running:
                        return True
                else:
                    self._dispatch(pool, running)
                if not running:
                    if self._polling and not self.store.stop_requested():
                        self.sleep(self.caps.queue_poll_s)
                        self._expire_polls()
                        continue
                    return stopped
                wait(list(running.values()), return_when=FIRST_COMPLETED)

    def _finished(self, n: int, exc: BaseException | None) -> None:
        if exc is None:
            return
        if isinstance(exc, AgentStopped) or type(exc).__name__ == "AgentStopped":
            self.store.event("step_interrupted", issue=n, phase=self.store.issue(n).phase.value)
        elif isinstance(exc, CeilingReached):
            if exc.scope == "run":
                self._wait(n, WAIT_RUN_CEILING, str(exc))
            else:
                self._fail(n, "ceiling", str(exc))
        elif isinstance(exc, AgentFailure) or type(exc).__name__ == "AgentFailure":
            kind = getattr(exc, "kind", "crash")
            self.store.event("agent_unavailable", issue=n, kind=kind, error=str(exc)[:500])
            if kind == "outage":
                self._wait(n, WAIT_OUTAGE, str(exc)[:300], vendor=getattr(exc, "vendor", ""))
            # a timeout or crash is charged to the infrastructure budget; the step is retried
        elif isinstance(exc, GitHubUnavailable):
            self._wait(n, WAIT_GITHUB, str(exc)[:300])
        else:
            self._engine_fault(n, exc)

    def _phases(self) -> dict[int, Phase]:
        return {n: self.store.issue(n).phase for n in self.plan.work}

    def _claim_issue(self, n: int) -> bool:
        """Two runs never work the same issue: a repo-wide claim per issue, held for the run."""
        if self.claims.acquire(f"issue-{n}", self.owner):
            self._polling.pop(-n, None)
            return True
        self._polling.setdefault(-n, time.monotonic())
        return False

    def _release_claims(self) -> None:
        for n in self.plan.work:
            self.claims.release(f"issue-{n}", self.owner)
        self.claims.release(MERGE_QUEUE, self.owner)

    def _expire_polls(self) -> None:
        """A merge queue or an issue another run holds is polled for `queue_wait_s`; past that
        the issue waits for the supervisor."""
        now = time.monotonic()
        for key, since in list(self._polling.items()):
            if now - since < self.caps.queue_wait_s:
                continue
            del self._polling[key]
            n = abs(key)
            self._wait(n, WAIT_CLAIM if key < 0 else WAIT_MERGE_QUEUE,
                       "another run held it for longer than the in-run wait")

    def _dispatch(self, pool: ThreadPoolExecutor, running: dict[int, Future]) -> None:
        phases = self._phases()
        writers = [n for n, ph in phases.items() if ph in WRITING_PHASES]
        landing = any(phases[n] == Phase.LAND for n in running)
        steps = {Phase.PLAN: self._step_plan, Phase.BUILD: self._step_build, Phase.VERIFY: self._step_verify,
                 Phase.EXAMINE: self._step_examine, Phase.MERGED: self._step_accept}
        for n in list(self.plan.work):
            if n in running:
                continue
            ph = phases.get(n, self.store.issue(n).phase)
            if ph in TERMINAL or ph == Phase.WAITING:
                continue
            if not self._claim_issue(n):
                continue
            if ph == Phase.PENDING:
                if scheduler.prerequisites_met(self.plan, phases, n):
                    if self.store.issue(n).plan:
                        self._set_phase(n, Phase.PLANNED)
                    else:
                        self._set_phase(n, Phase.PLAN)
                        running[n] = pool.submit(self._step_plan, n)
            elif ph == Phase.PLANNED:
                if scheduler.can_start_writing(self.plan, n, writers, self.caps.max_parallel_writers):
                    writers.append(n)
                    self._set_phase(n, Phase.BUILD)
                    running[n] = pool.submit(self._step_build, n)
            elif ph == Phase.LAND:
                if not landing and self.claims.acquire(MERGE_QUEUE, self.owner):
                    landing = True
                    self._polling.pop(n, None)
                    running[n] = pool.submit(self._step_land, n)
                elif not landing:
                    self._polling.setdefault(n, time.monotonic())   # another run is landing: poll
            elif ph in steps:
                running[n] = pool.submit(steps[ph], n)

    # ------------------------------------------------------------------ helpers
    def _req(self, n: int, feedback: list[str] | None = None) -> IssueRequest:
        st = self.store.issue(n)
        facts = {"lacks": self.lacks, "invariants": list(self.invariants), "repair": self.repair,
                 "decisions": st.decisions[-20:], "operator": self.op, "other": self.other}
        return IssueRequest(issue=self.plan.issues[n], spec=self.plan.specs[n],
                            context=self.store.state.get("context") or "", feedback=list(feedback or []), facts=facts)

    def _item_text(self, n: int) -> dict[str, str]:
        return {i.id: i.text for i in self.plan.specs[n].ledger}

    def _items(self, st: IssueState) -> list[dict]:
        return (st.plan or {}).get("items", [])

    def _agent_items(self, st: IssueState) -> set[str]:
        return {i["id"] for i in self._items(st) if i["proof"] in AGENT_PROOFS}

    def _owner_items(self, st: IssueState) -> set[str]:
        return {i["id"] for i in self._items(st) if i["proof"] in ("owner", "deferred")}

    def _review_items(self, st: IssueState) -> set[str]:
        return {i["id"] for i in self._items(st) if i["proof"] == "review"}

    def _specs(self, st: IssueState) -> list[CheckSpec]:
        fields = CheckSpec.__dataclass_fields__
        return [CheckSpec(**{k: v for k, v in c.items() if k in fields}) for c in st.commands]

    def _set_phase(self, n: int, phase: Phase, **changes) -> IssueState:
        st = self.store.issue(n)
        previous = st.phase
        st.phase = phase
        for k, v in changes.items():
            setattr(st, k, v)
        self.store.put(st)
        if previous != phase:
            self.store.event("phase", issue=n, frm=previous.value, to=phase.value)
            self.log(f"#{n} {previous.value} -> {phase.value}")
            self._sync(n)
        return st

    def _wait(self, n: int, kind: str, detail: str, resume: Phase | None = None, **extra) -> None:
        """Not terminal: the issue resumes by itself once its condition clears."""
        st = self.store.issue(n)
        resume_phase = resume or (st.phase if st.phase != Phase.WAITING else Phase.PENDING)
        st.wait = {"kind": kind, "resume": resume_phase.value, "detail": detail[:600], "since": time.time(), **extra}
        if kind == WAIT_ENVIRONMENT:
            st.wait["env"] = self.env_fingerprint
        if kind == WAIT_ENGINE:
            st.wait["version"] = VERSION
        self.store.put(st)
        self.store.event("waiting", issue=n, kind=kind, detail=detail[:600], resume=resume_phase.value)
        self.log(f"#{n} waiting ({kind}): {detail[:200]}")
        self._set_phase(n, Phase.WAITING)

    def _fail(self, n: int, cause: str, detail: str) -> None:
        """Explicit non-delivery: nothing partial is merged, nothing is called delivered. Filed as
        a loop fault; a new engine version resumes it once."""
        st = self.store.issue(n)
        st.fail = {"cause": cause, "detail": detail[:800], "version": VERSION, "resumed": bool((st.fail or {}).get("resumed"))}
        self.store.put(st)
        fingerprint = hashlib.sha256(f"stall:{cause}:{n}".encode()).hexdigest()[:10]
        body = (f"{report.FAULT_MARKER.format(fingerprint)}\nThe implement loop could not deliver #{n} (run for "
                f"#{self.plan.root}, engine {VERSION}): **{cause}**.\n\n{detail[:1500]}\n\nThe issue resumes once, with a "
                f"fresh ceiling, on the next engine version. Its branch keeps the work.\n")
        self.faults.record(fingerprint, f"implement loop: #{n} not delivered ({cause})", body, issue=n, run=self.plan.root)
        self.store.event("failed", issue=n, cause=cause, detail=detail[:800])
        self.log(f"#{n} failed ({cause}): {detail[:200]}")
        self._set_phase(n, Phase.FAILED)

    def _new_round(self, st: IssueState, feedback: list[str], owner_edit: bool) -> None:
        """Deliver an already-merged issue again (it was edited, reopened, or broke `main`): a new
        branch from `main`; the plan is kept unless the owner edited the issue."""
        n = st.number
        if st.worktree:
            self.ws.remove(Path(st.worktree))
        st.round += 1
        st.branch = f"{self.plan.specs[n].branch or f'loop/issue-{n}'}-r{st.round}"
        st.worktree = st.pr = st.head_sha = st.base_sha = None
        st.verified_sha = st.examined_sha = st.certified_sha = None
        st.locked, st.manifest, st.tests, st.probes = {}, {}, [], []
        st.findings = [f for f in st.findings if f.get("status") == "follow_up"]
        st.human_tasks, st.reverted = [], []
        st.feedback = list(feedback)
        if owner_edit:
            self._owner_edit(st)
            st.feedback = list(feedback) + st.feedback
        st.phase = Phase.PENDING
        self.store.event("new_round", issue=n, round=st.round, reason=feedback[0][:400] if feedback else "",
                         owner_edit=owner_edit)

    def _engine_fault(self, n: int, exc: BaseException) -> None:
        """An engine bug: journal it, queue one GitHub issue per distinct fault; the issue waits
        for a new engine version."""
        detail = redact("".join(traceback.format_exception(exc))[-2500:], self.repo_root)
        fingerprint = fault_fingerprint(exc)
        phase = self.store.issue(n).phase.value
        self.store.event("step_crashed", issue=n, error=redact(repr(exc), self.repo_root)[:500], traceback=detail,
                         fingerprint=fingerprint)
        title = f"implement loop: {type(exc).__name__} in the engine ({fingerprint})"
        body = (f"{report.FAULT_MARKER.format(fingerprint)}\nThe implement loop's engine raised `{type(exc).__name__}` "
                f"in phase `{phase}` while working on #{n} (run for #{self.plan.root}, engine {VERSION}). The issue "
                f"waits for a new engine version and the run carried on. The message and full traceback are in the "
                f"local run log (`events.jsonl`, event `step_crashed`, fingerprint `{fingerprint}`).\n\nEngine frames:\n\n"
                f"```\n{engine_frames(exc)}\n```\n\n"
                f"## Deliverables\n- [ ] A regression test reproduces this fault's path ({engine_frames(exc).splitlines()[-1] if engine_frames(exc) else 'unknown'}).\n"
                f"- [ ] The engine handles that path, and the test passes.\n\n## Acceptance criteria\n"
                f"- [ ] The engine's full test suite passes.\n- [ ] Nothing on the loop's safety surface changes.\n")
        self.faults.record(fingerprint, title, body, issue=n, run=self.plan.root)
        resume = Phase(phase) if phase not in (Phase.WAITING.value, Phase.FAILED.value) else Phase.PENDING
        self._wait(n, WAIT_ENGINE, f"engine error {type(exc).__name__} in phase {phase} (fault {fingerprint})",
                   resume=resume, fingerprint=fingerprint)

    def _flush_faults(self) -> None:
        self._safe(self.gh.ensure_label, *ENGINE_BUG_LABEL)
        for fingerprint, entry in self.faults.pending():
            try:
                number = entry.get("filed") or self.gh.find_issue(ENGINE_BUG_LABEL[0], report.FAULT_MARKER.format(fingerprint))
                if number:
                    self.gh.create_comment(number, f"Seen again: {entry['count']} occurrence(s) so far, latest on "
                                                   f"#{entry['issues'][-1]} (run for #{entry['runs'][-1]}).")
                else:
                    number = self.gh.create_issue(entry["title"], entry["body"], [ENGINE_BUG_LABEL[0]])["number"]
                self.faults.mark_reported(fingerprint, number)
                self.store.event("fault_filed", fingerprint=fingerprint, issue=number)
            except Exception as e:  # noqa: BLE001 - filing is best effort, by design
                self.store.event("fault_filing_failed", fingerprint=fingerprint, error=str(e)[:300])

    def _safe(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (GitHubError, OSError) as e:
            self.store.event("github_call_failed", call=getattr(fn, "__name__", str(fn)), error=str(e)[:300])
            return None

    def _sync(self, n: int) -> None:
        st = self.store.issue(n)
        wanted = PHASE_LABEL.get(st.phase)
        for label in (*LABELS, *LEGACY_LABELS):
            if label != wanted:
                self._safe(self.gh.remove_label, n, label)
        if wanted:
            self._safe(self.gh.add_labels, n, [wanted])
        self._upsert_comment(n, report.PROGRESS_MARKER, report.render_progress(st, self.plan.root))

    def _upsert_comment(self, n: int, marker: str, body: str) -> dict | None:
        comments = self._safe(self.gh.list_comments, n) or []
        for c in comments:
            if marker in (c.get("body") or ""):
                return self._safe(self.gh.update_comment, c["id"], body)
        return self._safe(self.gh.create_comment, n, body)

    def _requirements_current(self, n: int) -> bool:
        data = self.gh.get_issue(n)
        st = self.store.issue(n)
        if issue_parser.body_hash(data.get("body") or "") == st.body_hash:
            return True
        issue = Issue.from_api(data)
        self.plan.issues[n] = issue
        self.plan.specs[n] = issue_parser.parse(issue, graph.existing_session_dirs(self.repo_root))
        return False

    def _lookup_issue(self, m: int | None) -> gate.OpenIssue | None:
        if not m:
            return None
        if m in self.plan.issues:
            i = self.plan.issues[m]
        else:
            data = self._safe(self.gh.get_issue, m)
            if not data:
                return None
            i = Issue.from_api(data)
        return gate.OpenIssue(number=i.number, state=i.state, title=i.title, body=i.body,
                              tracking=i.sub_issue_total > 0 or m in self.plan.tracking)

    def _absorb_agent_commits(self, n: int, wt: Path, call: AgentCall, merge_head: str | None = None) -> None:
        """Only the engine creates history. The agent ran against a private git directory
        (`Workspace.agent_call`): its working tree is kept as it is, and is committed, verified and
        examined like everything else; the events say what was dropped."""
        if call.after_branch != call.branch:
            self.store.event("agent_checkout_undone", issue=n, was=call.after_branch or call.after_head,
                             branch=call.branch)
        if call.after_head and call.after_head != call.head:
            self.store.event("agent_commits_absorbed", issue=n, from_head=call.after_head, to=call.head)
        if call.branch:
            now = self.ws.git("rev-parse", "-q", "--verify", call.branch, check=False) or None
            if now != call.head:
                self.store.event("issue_branch_moved_externally", issue=n, branch=call.branch,
                                 **{"from": call.head, "to": now})
        if merge_head and call.after_merge_head is None and not call.merge_committed:
            self.ws.git("merge", "--quit", cwd=wt)
            self.store.event("agent_merge_dropped", issue=n, merge_head=merge_head)
        if call.created:
            self.store.event("agent_refs_deleted", issue=n, refs=call.created)
        if call.discarded:
            self.store.event("agent_ref_changes_discarded", issue=n, refs=call.discarded)

    def _delivery(self, st: IssueState, merged_head: str) -> tuple[str, list[str] | None]:
        reviewed, repo = st.certified_sha, self.ws.repo
        if not reviewed or merged_head == reviewed:
            return "same", []
        self.ws.git("fetch", "--quiet", self.ws.remote, merged_head, cwd=repo, check=False)
        if not self.ws.has_commit(repo, merged_head):
            return "later", None
        if not self.ws.is_ancestor(repo, reviewed, merged_head):
            return "stale", None
        touched = self.ws.git("diff", "--name-only", reviewed, merged_head, cwd=repo)
        allowed = self.plan.specs[st.number].declared_paths
        return "later", sorted({f for f in touched.splitlines() if f and any(scheduler.overlaps(f, a) for a in allowed)})

    def _verify(self, root: Path, st: IssueState, head: str, work_dir: Path, check_tamper: bool = True):
        return verify.verify(root, self._specs(st), head, work_dir, st.locked, sorted(set(st.tests) | set(st.probes)),
                             st.manifest or None, self.caps.check_timeout_s,
                             extra_env=self.check_env, check_tamper=check_tamper)

    def _decide(self, st: IssueState, entry: dict) -> None:
        st.decisions = [d for d in st.decisions if d.get("id") != entry.get("id")] + [entry]

    # ------------------------------------------------------------------ plan
    def _step_plan(self, n: int) -> None:
        st = self.store.issue(n)
        spec = self.plan.specs[n]
        wt = Path(st.worktree) if st.worktree and (Path(st.worktree) / ".git").exists() else None
        req = self._req(n, st.feedback)
        item_text = self._item_text(n)
        ledger_ids = [i.id for i in spec.ledger]
        res = self.agents.plan(self.op, req, wt)
        items = [asdict(i) for i in res.items]
        problems = gate.lint_plan(items, ledger_ids, item_text, self.lacks, self._lookup_issue, res.zones)
        if problems:   # one free retry, then the engine makes it usable itself
            res = self.agents.plan(self.op, replace(req, feedback=req.feedback + problems), wt)
            items = [asdict(i) for i in res.items]
            problems = gate.lint_plan(items, ledger_ids, item_text, self.lacks, self._lookup_issue, res.zones)
        st = self.store.issue(n)
        for d in res.decisions:
            self._decide(st, d)
        if problems:
            items, fixes = gate.repair_plan(items, ledger_ids, item_text)
            for d in fixes:
                self._decide(st, d)
            fixed = []
            for i in items:
                bad = gate.lint_plan([i], [i["id"]], item_text, self.lacks, self._lookup_issue, [])
                if bad and i["proof"] in ("owner", "deferred"):
                    i, d = gate.demote(i, "; ".join(bad))
                    self._decide(st, d)
                fixed.append(i)
            items = fixed
        plan = {"items": items, "zones": sorted({z.rstrip("/") for z in res.zones}), "notes": res.notes}
        st.plan = plan
        self.store.put(st)
        objections = [asdict(o) for o in self.agents.triage(self.other, self._req(n), plan)]
        kept = [o for o in objections if gate.keep_objection(o, item_text, self._lookup_issue)]
        st = self.store.issue(n)
        feedback = []
        infra = any(z.startswith(INFRA_PREFIXES) for z in plan["zones"])
        for o in kept:
            if o["kind"] == "classification":
                ruling = self.agents.arbitrate(self.other, self._req(n), {
                    "kind": "classification", "item": o["item"], "item_text": item_text.get(o["item"]),
                    "plan": next((i for i in items if i["id"] == o["item"]), None), "objection": o,
                    "lacks": self.lacks})
                if ruling.upheld and o.get("proof") in ("test", "command", "review", "owner", "deferred"):
                    item = next(i for i in plan["items"] if i["id"] == o["item"])
                    candidate = {**item, "proof": o["proof"], "capability": o.get("capability"),
                                 "depends_on": o.get("depends_on"), "depends_quote": o.get("depends_quote"),
                                 "agent_part": item.get("agent_part") or "the parts agents can do"}
                    if not gate.lint_plan([candidate], [o["item"]], item_text, self.lacks, self._lookup_issue, []):
                        plan["items"] = [candidate if i["id"] == o["item"] else i for i in plan["items"]]
                        self._decide(st, {"id": f"classification-{o['item']}", "choice": f"{o['item']} is {o['proof']}",
                                          "rationale": f"the arbiter upheld the examiner: {ruling.reason}"})
            elif o["kind"] == "dependency":
                self._depend(n, st, o["item"], o["depends_on"], o.get("depends_quote") or "")
            elif o["kind"] == "misreading":
                feedback.append(f"The examiner says the plan misreads {o['item']} (\"{o['quote']}\"): {o['text']} "
                                f"Accept or reject this reading, with a reason, in your decisions.")
            elif o["kind"] == "scenario" and infra:
                feedback.append(f"Failure scenario to cover: {o['text']}")
        for i in plan["items"]:
            if i["proof"] == "deferred" and i.get("depends_on"):
                self._depend(n, st, i["id"], int(i["depends_on"]), i.get("depends_quote") or "")
            if i["proof"] == "owner":
                self._obligate(st, {"item": i["id"], "kind": "capability", "detail": i.get("capability"),
                                    "agent_part": i.get("agent_part")})
        st.grants = [g for g in st.grants if g.get("source") != "plan"] + [
            {"path": z, "source": "plan", "protected": False} for z in plan["zones"]
            if not (self.repair and is_safety_surface(z))]
        st.plan = plan
        st.feedback = feedback
        self.store.put(st)
        self._declare(n, st)
        self.store.event("planned", issue=n, items={i["id"]: i["proof"] for i in plan["items"]}, zones=plan["zones"],
                         objections=len(objections), kept=len(kept), problems=problems)
        if not scheduler.prerequisites_met(self.plan, self._phases(), n):
            self._set_phase(n, Phase.PENDING)    # a prerequisite was added: wait for it
        else:
            self._set_phase(n, Phase.PLANNED)

    def _obligate(self, st: IssueState, ob: dict) -> None:
        st.obligations = [o for o in st.obligations if o["item"] != ob["item"]] + [ob]

    def _depend(self, n: int, st: IssueState, item: str, m: int, quote: str) -> None:
        """An item needs another open issue. In this run it waits for it; an open issue of the
        run's epic is admitted when the launch allowed it; otherwise the item is a deferred
        obligation that reopens when that issue lands."""
        other = self._lookup_issue(m)
        if other is None or other.state != "open" or m == n:
            return
        edges = {k: set(v) for k, v in self.plan.deps.items()}
        edges.setdefault(n, set()).add(m)
        in_epic = m in self.plan.parent or m in self.plan.closed_work or m in self.plan.work
        try:
            if m in self.plan.work:
                graph.topological_order(set(self.plan.work), edges)
                self.plan.deps[n] = edges[n]
                self._decide(st, {"id": f"depends-{item}", "choice": f"{item} waits for #{m}, in this run",
                                  "rationale": f"it needs #{m}: \"{quote}\""})
                self.store.event("dependency_added", issue=n, on=m, item=item, admitted=False)
                return
            if self.admit and in_epic and not other.tracking:
                data = self.gh.get_issue(m)
                issue = Issue.from_api(data)
                self.plan.issues[m] = issue
                self.plan.specs[m] = issue_parser.parse(issue, graph.existing_session_dirs(self.repo_root))
                graph.topological_order(set(self.plan.work) | {m}, edges)
                self.plan.work.insert(0, m)
                self.plan.deps[n] = edges[n]
                self.plan.deps.setdefault(m, set())
                self._decide(st, {"id": f"depends-{item}", "choice": f"#{m} joined the run; {item} waits for it",
                                  "rationale": f"it needs #{m}: \"{quote}\" (the launch allowed prerequisites from the epic)"})
                self.store.event("prerequisite_added", issue=n, on=m, item=item)
                return
        except graph.CycleError:
            self.store.event("dependency_cycle", issue=n, on=m, item=item)
        self._obligate(st, {"item": item, "kind": "deferred", "detail": f"#{m}", "issue": m})
        self._decide(st, {"id": f"depends-{item}", "choice": f"{item} is deferred to #{m}",
                          "rationale": f"it needs #{m} (\"{quote}\"), which this run does not build"})
        self.store.event("dependency_deferred", issue=n, on=m, item=item)

    # ------------------------------------------------------------------ build
    def _step_build(self, n: int) -> None:
        """Every round starts from current main: main is merged in first. On a conflict the merge
        stays in progress for the builder to resolve, and is concluded or aborted within this step."""
        st = self.store.issue(n)
        wt = self.ws.issue_worktree(n, st.branch)
        if str(wt) != st.worktree:
            st.worktree = str(wt)
            self.store.put(st)
        if not self._restore_branch(n):
            return
        self._recover_worktree(n, wt)
        self._release_legacy(n, wt)
        self.ws.fetch()
        if self.ws.uncommitted(wt) and not self.ws.is_ancestor(wt, self.ws.base_ref(), "HEAD"):
            sha = self._commit_work(n, wt, f"Checkpoint #{n} before merging main")
            self.store.event("checkpoint_before_update", issue=n, sha=sha)
        if not st.base_sha:
            self._set_phase(n, Phase.BUILD, base_sha=self.ws.git("merge-base", "HEAD", self.ws.base_ref(), cwd=wt))
        sync = self.ws.update(wt)
        try:
            self._build_round(n, wt, sync)
        finally:
            if self.ws.in_progress(wt):
                self.ws.abort_in_progress(wt)

    def _release_legacy(self, n: int, wt: Path) -> None:
        st = self.store.issue(n)
        pending = [r for r in st.requests if r.get("kind") == "legacy_unlock" and r.get("status") == "pending"]
        for r in pending:
            on_branch = [f for f in r.get("paths", []) if (wt / f).exists()]
            self.ws.commit_all(wt, f"Release the earlier engine's checks for #{n}", "acceptance-checks", n,
                               unlocks=on_branch or None)
            r["status"] = "approved"
            r["reason"] = "the builder takes over tests an earlier engine locked"
            self.store.event("legacy_checks_released", issue=n, files=on_branch)
        if pending:
            self.store.put(st)

    def _build_round(self, n: int, wt: Path, sync: UpdateResult) -> None:
        st = self.store.issue(n)
        feedback = list(st.feedback) + self._open_feedback(st)
        files = sync.files if sync.status == "conflict" else []
        expected: dict[str, str] = {}
        restore: dict[str, tuple] = {}
        sources: dict[str, str] = {}
        if st.conflict_pending and not files:
            st.conflict_pending = False
            self.store.put(st)
        if sync.status == "merged":
            self.store.event("updated_from_main", issue=n, phase=Phase.BUILD.value, frm=sync.before,
                             to=self.ws.head(wt), main=sync.main)
            self._relock(n, wt, self._relock_candidates(n, wt, sync.before), {})
        elif files:
            st.conflict_paths = sorted(set(st.conflict_paths) | set(files))
            st.grants = st.grants + [{"path": f, "source": "conflict", "protected": False} for f in files
                                     if not any(g["path"] == f for g in st.grants)]
            st.conflict_pending = True
            self.store.event("conflict", issue=n, phase=Phase.BUILD.value, files=files)
            self.store.put(st)
            self._declare(n, st)
            locked = [f for f in files if f in st.locked]
            if locked and not self._resolve_locked_conflict(n, wt, locked, sync.main):
                return self._back_to_build(n, wt, "check_conflict_unresolved", locked,
                                           f"The other vendor could not resolve main's conflict in the locked tests "
                                           f"{locked}; the next round merges main again.")
            expected = self._relock_candidates(n, wt, sync.before)
            merged = {f: self.ws.file_state(wt, f) for f in {**st.locked, **expected}}
            restore = {f: s for f, s in merged.items() if s is not None}
            sources = {f: "other-vendor" if f in locked else "main" for f in expected}
            feedback.append(conflict_feedback([f for f in files if f not in locked], locked))
        with self.ws.agent_call(wt) as call:
            result = self.agents.build(self.op, self._req(n, feedback), st.plan, wt, feedback)
        self._absorb_agent_commits(n, wt, call, merge_head=sync.main if files else None)
        unresolved = []
        if files:
            st = self.store.issue(n)
            st.conflict_pending = False
            self.store.put(st)
            unresolved = (files if self.ws.in_progress(wt) != "merge"
                          else [f for f in files if has_conflict_markers(wt / f)])
            if unresolved and result.status == "done":
                return self._back_to_build(n, wt, "conflict_unresolved", unresolved,
                                           f"Conflict markers are still in {unresolved}, so main's merge was aborted. "
                                           f"The next round merges main again: resolve every marker.")
            if unresolved:
                self.ws.abort_in_progress(wt)
                expected, restore = {}, {}
        # A locked test the builder edited without approval is reverted; its proposed content is
        # kept with a `test_change` request if it made one, for the other vendor to decide.
        st = self.store.issue(n)
        proposals = self._locked_edits(st, wt, restore)
        requests = self._new_requests(n, st, result.requests, proposals)
        subject = (f"Merge main and build #{n}" if files and not unresolved else f"Build #{n}")
        sha = self._commit_work(n, wt, f"{subject} (round {len([e for e in st.requests]) + st.calls})", expected, restore)
        if files and not unresolved:
            self._relock(n, wt, expected, sources)
        st = self.store.issue(n)
        self._absorb_build(st, result)
        self.store.put(st)
        self.store.event("built", issue=n, sha=sha, status=result.status, note=result.note[:600],
                         requests=[r["id"] for r in requests])
        if requests:
            self._decide_requests(n, wt)
            st = self.store.issue(n)
        if result.status != "done":
            decided = [r for r in st.requests if r["id"] in {q["id"] for q in requests}]
            if any(r["status"] in ("approved", "ruled_for") for r in decided):
                return self._set_phase(n, Phase.BUILD, feedback=self._request_feedback(decided))
            return self._round_failed(n, [f"blocked: {result.note[:400]}" + (
                "" if requests else " — a blocked answer needs a typed request the other vendor can decide")])
        self._set_phase(n, Phase.VERIFY, head_sha=self.ws.head(wt), feedback=self._request_feedback(
            [r for r in st.requests if r["id"] in {q["id"] for q in requests}]))

    def _absorb_build(self, st: IssueState, result) -> None:
        """The builder's tests, commands and dispositions. Before the first examination they are its
        own; after it, commands for locked items change only through an approved request."""
        agent = self._agent_items(st)
        st.tests = sorted(set(st.tests) | {t for t in result.tests if t})
        current = {c["criterion"]: c for c in st.commands if c.get("author") == "builder"}
        probes = [c for c in st.commands if c.get("author") == "examiner"]
        for c in result.commands:
            if c.criterion not in agent or not c.command:
                continue
            entry = asdict(c) | {"author": "builder",
                                 "timeout_s": min(c.timeout_s or self.caps.check_timeout_s, self.caps.max_check_timeout_s)}
            if st.examined_sha and c.criterion in current and current[c.criterion]["command"] != c.command:
                st.requests.append({"id": f"R{st.number}-{len(st.requests) + 1}", "kind": "command_change",
                                    "item": c.criterion, "command": entry, "status": "pending",
                                    "detail": f"change the locked command for {c.criterion}"})
                continue
            current[c.criterion] = entry
        st.commands = list(current.values()) + probes
        for test_id, why in (result.dispositions or {}).items():
            st.dispositions.setdefault(test_id, why)
        for d in result.decisions or []:
            self._decide(st, d)

    def _locked_edits(self, st: IssueState, wt: Path, restore: dict) -> dict[str, str | None]:
        """Locked tests the builder changed: their proposed content (None: deleted)."""
        out = {}
        for rel, d in st.locked.items():
            p = wt / rel
            if rel in restore:
                continue
            if not p.is_file():
                out[rel] = None
            elif verify.digest(p) != d:
                out[rel] = p.read_text(errors="replace")
        return out

    def _new_requests(self, n: int, st: IssueState, requests, proposals: dict[str, str | None]) -> list[dict]:
        added = []
        for r in requests:
            entry = asdict(r)
            entry["id"] = f"R{n}-{len(st.requests) + 1}"
            entry["status"] = "pending"
            if r.kind == "test_change":
                entry["content"] = {p: proposals.get(p) for p in (r.paths or list(proposals))}
            st.requests.append(entry)
            added.append(entry)
        unrequested = [p for p in proposals if not any(p in (q.get("content") or {}) for q in added)]
        if unrequested:
            st.reverted = sorted(unrequested)
        self.store.put(st)
        return added

    def _request_feedback(self, decided: list[dict]) -> list[str]:
        out = []
        for r in decided:
            verdict = {"approved": "approved", "ruled_for": "ruled in your favour"}.get(r["status"], "refused")
            out.append(f"Your {r['kind']} request {r['id']} ({r.get('detail', '')[:200]}) was {verdict}: {r.get('reason', '')[:400]}")
        return out

    def _decide_requests(self, n: int, wt: Path) -> None:
        """The other vendor decides the builder's typed requests; disputes go to the arbiter. The
        engine enforces its own rules first: no safety surface in a repair run, `owner` only for
        a capability the host lacks."""
        st = self.store.issue(n)
        pending = [r for r in st.requests if r.get("status") == "pending" and r.get("kind") != "legacy_unlock"]
        if not pending:
            return
        for r in pending:
            refusal = self._engine_refusal(st, r)
            if refusal:
                r["status"], r["reason"] = "refused", refusal
        disputes = [r for r in pending if r["status"] == "pending" and r["kind"] == "dispute"]
        others = [r for r in pending if r["status"] == "pending" and r["kind"] != "dispute"]
        self.store.put(st)
        if others:
            with self.ws.disposable(wt) as scratch:
                decisions = self.agents.decide(self.other, self._req(n), scratch, others)
            by_id = {d.request: d for d in decisions}
            for r in others:
                d = by_id.get(r["id"])
                if d is None:
                    r["status"], r["reason"] = "refused", "no decision was given; ask again with evidence"
                    continue
                r["status"], r["reason"] = ("approved" if d.approve else "refused"), d.reason
                if d.approve:
                    self._apply_request(n, st, wt, r, d.dispositions)
        for r in disputes:
            f = next((x for x in st.findings if x["id"] == r.get("finding")), None)
            if f is None:
                r["status"], r["reason"] = "refused", "no such open finding"
                continue
            ruling = self.agents.arbitrate(self.other, self._req(n), {
                "kind": "finding", "finding": f, "item_text": self._item_text(n).get(f.get("item") or ""),
                "invariants": list(self.invariants), "argument": r.get("detail"), "lacks": self.lacks,
                "history": [x for x in st.findings if x.get("item") == f.get("item")][-5:]})
            if ruling.upheld:
                r["status"], r["reason"] = "refused", f"the arbiter upheld the finding: {ruling.reason}"
            else:
                r["status"], r["reason"] = "ruled_for", f"the arbiter ruled the item does not require it: {ruling.reason}"
                f["status"], f["blocking"], f["reason"] = "closed", False, f"ruled out by the arbiter: {ruling.reason}"
        self.store.put(st)
        self.store.event("requests_decided", issue=n, decided={r["id"]: r["status"] for r in pending})

    def _engine_refusal(self, st: IssueState, r: dict) -> str | None:
        paths = r.get("paths") or []
        if self.repair and any(is_safety_surface(p) for p in paths):
            return "a fault-repair run may never change the loop's safety surface"
        if r["kind"] == "reclassify":
            if r.get("capability") not in self.lacks:
                return f"`owner` is only for a capability this host lacks ({', '.join(self.lacks)})"
            if r.get("item") not in self._agent_items(st):
                return "only an agent item can be reclassified"
        if r["kind"] == "test_change" and not r.get("content"):
            return "a test change needs the proposed content: edit the locked test in your worktree and name it"
        if r["kind"] == "depends" and not r.get("depends_on"):
            return "name the issue it depends on"
        return None

    def _apply_request(self, n: int, st: IssueState, wt: Path, r: dict, dispositions: dict[str, str]) -> None:
        kind = r["kind"]
        if kind in ("paths", "protected_change"):
            for p in r.get("paths") or []:
                st.grants.append({"path": p.rstrip("/"), "source": f"approved {r['id']}",
                                  "protected": kind == "protected_change" or is_protected(p)})
            self._declare(n, st)
        elif kind == "command_change" and r.get("command"):
            st.commands = [c for c in st.commands if not (c["criterion"] == r["item"] and c.get("author") == "builder")]
            st.commands.append(r["command"])
        elif kind == "reclassify":
            st.plan["items"] = [{**i, "proof": "owner", "capability": r.get("capability"),
                                 "agent_part": r.get("detail")} if i["id"] == r["item"] else i for i in st.plan["items"]]
            self._obligate(st, {"item": r["item"], "kind": "capability", "detail": r.get("capability"),
                                "agent_part": r.get("detail")})
        elif kind == "depends":
            self._depend(n, st, r.get("item") or "", int(r["depends_on"]), r.get("depends_quote") or "")
        elif kind == "test_change":
            content = r.get("content") or {}
            for p, text in content.items():
                target = wt / p
                if text is None:
                    target.unlink(missing_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(text)
            removed = [p for p, t in content.items() if t is None]
            sha = self.ws.commit_all(wt, f"Change locked tests for #{n} (approved {r['id']})", "acceptance-checks", n,
                                     unlocks=removed or None,
                                     trailers={"Loop-Approved": f"{r['id']} by {self.other}"})
            for p, text in content.items():
                if text is None:
                    st.locked.pop(p, None)
                    st.tests = [t for t in st.tests if t != p]
                    st.probes = [t for t in st.probes if t != p]
                elif p in st.locked:
                    st.locked[p] = verify.digest(wt / p)
            self.store.event("locked_tests_changed", issue=n, request=r["id"], sha=sha, files=sorted(content))
        st.dispositions.update(dispositions or {})
        self._decide(st, {"id": r["id"], "choice": f"{kind}: {r.get('detail', '')[:200]}",
                          "rationale": f"approved by {self.other}: {r.get('reason', '')[:300]}"})

    def _open_feedback(self, st: IssueState) -> list[str]:
        out = []
        for f in st.findings:
            if f.get("status") == "open":
                where = f"item {f['item']} (\"{f.get('quote')}\")" if f.get("item") else f"invariant: {f.get('invariant')}"
                repro = f.get("reproduction") or (f"bash {f['probe']}" if f.get("probe") else "")
                out.append(f"Open finding {f['id']} on {where}: {f['title']}. Observed: {f['observed']}. "
                           f"Expected: {f['expected']}. Reproduce: {repro}. It closes when that passes, or dispute it "
                           f"with a `dispute` request if the item as written does not require it.")
        for i, v in st.verdicts.items():
            if v.get("verdict") == "unmet":
                out.append(f"The examiner judges {i} unmet (\"{v.get('quote')}\"): {v.get('note', '')[:400]}")
        return out

    def _back_to_build(self, n: int, wt: Path, kind: str, files: list[str], note: str) -> None:
        self.ws.abort_in_progress(wt)
        st = self.store.issue(n)
        st.conflict_pending = False
        self.store.put(st)
        self.store.event(kind, issue=n, files=files)
        self._set_phase(n, Phase.BUILD, feedback=[note])

    def _conflict(self, n: int, wt: Path, files: list[str], phase: str) -> None:
        """Bringing the branch up to date with main hit conflicts: work for the builder, not a
        fault, and no round is charged (main moving is nobody's design fault)."""
        if self.ws.in_progress(wt) or self.ws.git("status", "--porcelain", cwd=wt):
            raise GitError(f"the worktree of #{n} is not clean after aborting the conflicted update")
        st = self.store.issue(n)
        st.conflict_pending = True
        st.conflict_paths = sorted(set(st.conflict_paths) | set(files))
        st.grants = st.grants + [{"path": f, "source": "conflict", "protected": False} for f in files
                                 if not any(g["path"] == f for g in st.grants)]
        self.store.put(st)
        self._declare(n, st)
        self.store.event("conflict", issue=n, phase=phase, files=files)
        self._set_phase(n, Phase.BUILD, feedback=[
            f"Main moved on and conflicts with this branch in: {', '.join(files)}. The next round starts with main's "
            f"merge in progress; resolve the conflicts in those files."])

    def _relock_candidates(self, n: int, wt: Path, before: str) -> dict[str, str]:
        st = self.store.issue(n)
        if not st.locked:
            return {}
        cwds = sorted({c.get("cwd", ".") for c in st.commands})
        current = verify.lock(wt, sorted(st.locked), cwds)
        candidates, refused = {}, []
        for f, d in current.items():
            pre = self._digest_at(wt, before, f)
            if pre == d:
                continue
            if pre != st.locked.get(f):
                refused.append(f)
                continue
            candidates[f] = d
        if refused:
            self.store.event("checks_not_relocked", issue=n, files=sorted(refused),
                             reason="changed on the branch before main's merge")
        return candidates

    def _digest_at(self, wt: Path, ref: str, file: str) -> str | None:
        data = self.ws.show_bytes(wt, ref, file)
        if data is None:
            return None
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / Path(file).name
            p.write_bytes(data)
            return verify.digest(p)

    def _relock(self, n: int, wt: Path, digests: dict[str, str], sources: dict[str, str]) -> None:
        kept = {f: d for f, d in digests.items() if (wt / f).is_file() and verify.digest(wt / f) == d}
        if not kept:
            return
        st = self.store.issue(n)
        st.locked = {**st.locked, **kept}
        self.store.put(st)
        by_source: dict[str, list[str]] = {}
        for f in sorted(kept):
            by_source.setdefault(sources.get(f, "main"), []).append(f)
        for source, files in sorted(by_source.items()):
            self.store.event("checks_relocked", issue=n, files=files, source=source)

    def _resolve_locked_conflict(self, n: int, wt: Path, lane: list[str], merge_head: str) -> bool:
        """Conflicts in locked tests go to the other vendor, never the builder. Its edits outside
        `lane`, staged or not, are undone from the index entries and bytes taken before it ran."""
        snapshot = {f: self.ws.file_state(wt, f) for f in self.ws.uncommitted(wt)}
        index = self.ws.index_entries(wt)
        feedback = [f"Main moved on, and merging it into this branch conflicts in the locked tests {', '.join(lane)}. "
                    f"The merge is in progress: resolve the conflict markers in those files, keeping the requirements "
                    f"of both sides (main's side tests work already merged). Change nothing else; do not run git "
                    f"merge, commit or abort."]
        with self.ws.agent_call(wt) as call:
            self.agents.resolve_locked(self.other, self._req(n), wt, lane, feedback)
        self._absorb_agent_commits(n, wt, call, merge_head=merge_head)
        restored = []
        index_now = self.ws.index_entries(wt)
        changed_in_index = {f for f in set(index) | set(index_now) if index.get(f) != index_now.get(f)}
        for f in sorted(set(self.ws.uncommitted(wt)) | set(snapshot) | changed_in_index):
            if any(scheduler.overlaps(f, c) for c in lane):
                continue
            now = self.ws.file_state(wt, f)
            was = snapshot[f] if f in snapshot else self.ws.file_state_at(wt, "HEAD", f)
            if now == was and f not in changed_in_index:
                continue
            if now != was:
                self.ws.write_file_state(wt, f, was)
            self.ws.restore_index_entry(wt, f, index.get(f, []))
            restored.append(f)
        if restored:
            self.store.event("resolver_out_of_lane", issue=n, discarded=restored)
        return self.ws.in_progress(wt) == "merge" and not any(has_conflict_markers(wt / f) for f in lane)

    def _commit_work(self, n: int, wt: Path, subject: str, expected: dict[str, str] | None = None,
                     restore: dict[str, tuple] | None = None) -> str | None:
        """Commit the builder's work, minus any edit to a locked test (its proposal is kept with
        its request). Mid-merge, `expected` holds the locked digests main's merge brought and
        `restore` their file states: HEAD lacks main's side, so those files are restored from them."""
        st = self.store.issue(n)
        restore = restore or {}

        def mode_changed(rel: str) -> bool:
            ref = restore[rel] if rel in restore else self.ws.file_state_at(wt, "HEAD", rel)
            now = self.ws.file_state(wt, rel)
            return ref is not None and (now is None or now[0] != ref[0] or now[2:] != ref[2:])

        touched = [rel for rel, d in {**st.locked, **(expected or {})}.items()
                   if not (wt / rel).is_file() or verify.digest(wt / rel) != d or mode_changed(rel)]
        if touched:
            for rel in touched:
                if rel in restore:
                    self.ws.write_file_state(wt, rel, restore[rel])
            from_head = [rel for rel in touched if rel not in restore]
            if from_head:
                self.ws.git("checkout", "HEAD", "--", *from_head, cwd=wt, check=False)
            self.store.event("locked_changes_reverted", issue=n, files=touched)
            st.reverted = sorted(set(st.reverted) | set(touched))
            self.store.put(st)
        return self.ws.commit_all(wt, subject, "implementation", n)

    # ------------------------------------------------------------------ verify
    def _step_verify(self, n: int) -> None:
        st = self.store.issue(n)
        wt = Path(st.worktree)
        head = self.ws.head(wt)
        problems: list[str] = []
        if st.reverted:
            problems.append(f"your edits to the locked tests {st.reverted} were reverted; make them pass unchanged, or "
                            f"propose the change with a `test_change` request")
            st.reverted = []
            self.store.put(st)
        if not st.commands and self._agent_items(st) - self._review_items(st):
            problems.append("no commands prove the test/command items; return one command per item")
        locked_tests = sorted(set(st.tests) | set(st.probes))
        unselected = verify.unselected(wt, [t for t in locked_tests if (wt / t).is_file()],
                                       st.manifest or st.last_ran, st.dispositions) if st.examined_sha else []
        ok, evidence, vproblems, ran = verify.verify(wt, self._specs(st), head, self.store.issue_dir(n), st.locked,
                                                     locked_tests, st.manifest or None, self.caps.check_timeout_s,
                                                     extra_env=self.check_env)
        problems += vproblems
        if unselected:
            problems.append(f"tests in locked files that no command selects: {unselected[:6]} — select each one in a "
                            f"command, or give it a disposition (owner-run, or excluded: <reason>)")
        closed = self._close_findings(n, st, wt, evidence)
        st = self.store.issue(n)
        still = [f for f in st.findings if f.get("status") == "open"]
        base = self.ws.git("merge-base", "HEAD", self.ws.base_ref(), cwd=wt)
        changed = self.ws.changed_files(wt, base)
        problems += gate.zone_problems(changed, st.grants, locked_tests, self.repair)
        problems += [f"open finding {f['id']} still reproduces: {f['title']}" for f in still]
        self.store.event("verified", issue=n, head=head, ok=ok and not problems, problems=problems, closed=closed)
        st.evidence, st.base_sha = evidence, base
        st.last_ran = {"*": sorted(ran)} if ok else st.last_ran
        self.store.put(st)
        if not problems:
            nxt = Phase.LAND if head == st.certified_sha else Phase.EXAMINE
            return self._set_phase(n, nxt, verified_sha=head, head_sha=head)
        env = environment_problem(evidence)
        if env:
            return self._wait(n, WAIT_ENVIRONMENT, f"the host cannot run this issue's checks: {env}", resume=Phase.VERIFY)
        self._round_failed(n, problems, [f["id"] for f in still])

    def _close_findings(self, n: int, st: IssueState, wt: Path, evidence: list[dict]) -> list[str]:
        """An open finding closes only when its reproduction passes on the new head (a probe-based
        one when its probe passes)."""
        closed = []
        passed_probe = {c["command"] for c in st.commands if c.get("author") == "examiner"} & {
            e["command"] for e in evidence if e.get("passed")}
        for f in st.findings:
            if f.get("status") != "open":
                continue
            if f.get("probe"):
                cmd = next((c["command"] for c in st.commands if c.get("author") == "examiner"
                            and f["probe"] in (c.get("command") or "")), None)
                if cmd and cmd in passed_probe:
                    f["status"], f["reason"] = "closed", "its probe passes"
                    closed.append(f["id"])
                continue
            if f.get("reproduction"):
                still = self._reproduces(wt, f.get("reproduction"), f.get("cwd") or ".", None)
                if still is False:
                    f["status"], f["reason"] = "closed", "its reproduction passes"
                    closed.append(f["id"])
        if closed:
            self.store.put(st)
        return closed

    def _reproduces(self, wt: Path, command: str | None, cwd: str, probe: tuple[str, str] | None) -> bool | None:
        """Run a reproduction (and an optional probe file) in a throwaway copy of the head: True
        when it fails (the finding holds), False when it passes, None when it cannot run."""
        if not command:
            return None
        with self.ws.disposable(wt) as scratch:
            if probe:
                target = scratch / probe[0]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(probe[1])
            spec = CheckSpec(criterion="repro", command=command, cwd=cwd)
            ev, _ = verify.run_check(scratch, spec, self.ws.head(wt), self.store.issue_dir(0) / "repro",
                                     self.caps.check_timeout_s, extra_env=self.check_env)
        if ev.exit_code is None and "timed out" not in (ev.output_tail or ""):
            return None
        return not ev.passed

    def _round_failed(self, n: int, problems: list[str], open_ids: list[str] | None = None,
                      unmet: list[str] | None = None) -> None:
        """The progress rule: a round is productive when what fails changes. Two unproductive
        rounds bring a replan on the branch, two more end the issue `failed`."""
        st = self.store.issue(n)
        sig = gate.signature(problems, open_ids or [], unmet or [])
        st.unproductive = st.unproductive + 1 if sig == st.signature else 0
        st.signature = sig
        self.store.put(st)
        self.store.event("round_failed", issue=n, unproductive=st.unproductive, problems=problems[:8])
        if st.unproductive >= self.caps.unproductive_fail:
            return self._fail(n, "no_progress", "the same failure repeated after a replan: " + "; ".join(problems)[:600])
        if st.unproductive >= self.caps.unproductive_replan and st.replans < self.caps.replans:
            st.replans += 1
            self.store.put(st)
            self.store.event("replan", issue=n, count=st.replans)
            return self._set_phase(n, Phase.PLAN, feedback=[
                "Two rounds changed nothing. Replan on your branch: the same failure keeps coming back. "
                "Keep what works; change the approach, the zones or the proof kinds (classification changes go through "
                "a request). The failures were: " + "; ".join(problems)[:1500]])
        self._set_phase(n, Phase.BUILD, feedback=problems)

    # ------------------------------------------------------------------ examine
    def _step_examine(self, n: int) -> None:
        st = self.store.issue(n)
        wt = Path(st.worktree)
        head = self.ws.head(wt)
        if head != st.verified_sha:
            self.store.event("head_changed_before_examination", issue=n, verified=st.verified_sha, head=head)
            return self._set_phase(n, Phase.VERIFY)
        since = st.examined_sha
        memory = [f for f in st.findings if f.get("status") in ("open", "closed", "follow_up")]
        res = self.agents.examine(self.other, self._req(n), st.plan, wt, st.base_sha, head, st.evidence, memory, [], since)
        st = self.store.issue(n)
        item_text = self._item_text(n)
        rnd = len({f.get("round") for f in st.findings}) + 1
        # probes: linted, run on the exact head, adopted when they pass or reproduce a blocking finding
        probe_results: dict[str, bool] = {}
        rejected = []
        for p in res.probes:
            problem = self._probe_problem(p)
            if problem:
                rejected.append({"file": p.file, "reason": problem})
                continue
            probe_results[p.file] = self._reproduces(wt, p.command, p.cwd, (p.file, p.content)) is False
        new: list[Finding] = []
        for i, f in enumerate(res.findings):
            f.id = f"E{n}-{rnd}-{i + 1}"
            f.round = rnd
            probe = next((p for p in res.probes if f.probe and p.file == f.probe), None)
            if probe and probe.file in probe_results:
                reproduced = not probe_results[probe.file]
            else:
                reproduced = self._reproduces(wt, f.reproduction, f.cwd or ".", None)
            new.append(gate.classify(f, item_text, self.invariants, reproduced, self._agent_items(st),
                                     self._owner_items(st)))
        accepted, unmet, missing = gate.review_verdicts(res.verdicts, item_text, self._review_items(st))
        for i, v in accepted.items():
            st.verdicts[i] = {**v, "head": head}
        st.findings += [asdict(f) for f in new]
        adopt = [p for p in res.probes if probe_results.get(p.file) is True
                 or any(f.blocking and f.probe == p.file for f in new)]
        first = st.examined_sha is None
        st.examined_sha = head
        self.store.put(st)
        new_head = self._lock_and_adopt(n, wt, adopt, first)
        st = self.store.issue(n)
        blocking = [f for f in new if f.blocking] + [Finding(**{k: v for k, v in f.items() if k in Finding.__dataclass_fields__})
                                                     for f in st.findings if f.get("status") == "open"
                                                     and f.get("round") != rnd]
        self.store.event("examined", issue=n, head=head, findings={f.id: f.status for f in new},
                         unmet=unmet, missing=missing, certify=res.certify, adopted=[p.file for p in adopt],
                         rejected=rejected)
        problems = []
        if unmet:
            problems += [f"{i} judged unmet by the examiner" for i in unmet]
        if missing:
            problems.append(f"no verdict on the review items {missing}; the next examination must give one")
        if blocking:
            problems += [f"blocking finding {f.id}: {f.title}" for f in blocking]
        if not res.certify and not problems:
            problems.append(f"the examiner withheld its certificate: {res.summary[:400]}")
        if problems:
            bundled = [f for f in new if f.status == "follow_up"]
            if bundled:
                problems += [f"also worth fixing (not blocking): {f.title}" for f in bundled]
            return self._round_failed(n, problems, [f.id for f in blocking], unmet + missing)
        # certified: the certificate covers the examined head plus the examiner's own adopted probes
        self._set_phase(n, Phase.VERIFY, certified_sha=new_head, feedback=[])

    def _probe_problem(self, p) -> str | None:
        if not p.file or not p.command or not p.content:
            return "a probe needs a file, its content and the command that runs it"
        if Path(p.file).is_absolute() or ".." in Path(p.file).parts:
            return "a probe file must be a repo-relative path"
        if is_protected(p.file) or (self.repair and is_safety_surface(p.file)):
            return "a probe may not be written on a protected path"
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / p.file
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(p.content)
            bad = verify.unconditional_failures(Path(tmp), [p.file])
        return f"it fails unconditionally: {bad[0]}" if bad else None

    def _lock_and_adopt(self, n: int, wt: Path, probes, first: bool) -> str:
        """At the first examination the builder's tests, their configuration and the selection
        manifest lock, pass or fail; adopted probes lock with them (failing ones included, so a
        blocking finding stays open until its probe passes)."""
        st = self.store.issue(n)
        for p in probes:
            target = wt / p.file
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(p.content)
        files = sorted(set(st.tests) | {p.file for p in probes})
        existing = [t for t in st.tests if (wt / t).is_file()] if first else []
        if not probes and not existing:
            return self.ws.head(wt)
        sha = self.ws.commit_all(wt, f"Lock the tests for #{n}" + (" and adopt the examiner's probes" if probes else ""),
                                 "acceptance-checks", n, locks=existing or None,
                                 trailers={"Loop-Probe-Author": self.other} if probes else None)
        cwds = sorted({c.get("cwd", ".") for c in st.commands} | {p.cwd for p in probes})
        st.locked = {**st.locked, **verify.lock(wt, [f for f in files if (wt / f).is_file()], cwds)}
        st.probes = sorted(set(st.probes) | {p.file for p in probes})
        st.commands = st.commands + [asdict(CheckSpec(criterion=p.criterion, command=p.command, cwd=p.cwd,
                                                      author="examiner")) for p in probes]
        if first and not st.manifest:
            st.manifest = {k: list(v) for k, v in st.last_ran.items()}
        head = self.ws.head(wt)
        st.verified_sha = head if not probes else st.verified_sha
        self.store.put(st)
        self.store.event("tests_locked", issue=n, sha=sha, locked=sorted(st.locked), probes=[p.file for p in probes])
        return head

    # ------------------------------------------------------------------ land
    def _step_land(self, n: int) -> None:
        try:
            st = self.store.issue(n)
            wt = Path(st.worktree)
            issue = self.plan.issues[n]
            if st.certified_sha != st.verified_sha:
                return self._set_phase(n, Phase.VERIFY)
            existing = self.gh.find_pr(st.branch)
            if existing and (existing.get("merged") or existing.get("merged_at")):
                merged_head = (existing.get("head") or {}).get("sha") or st.certified_sha
                relation, unreviewed = self._delivery(st, merged_head)
                if relation == "same":
                    self.store.event("merge_found_on_resume", issue=n, pr=existing["number"])
                    return self._set_phase(n, Phase.MERGED, pr=existing["number"])
                if relation == "later":
                    self.store.event("merged_externally", issue=n, pr=existing["number"], head=merged_head,
                                     certified=st.certified_sha, unreviewed=unreviewed)
                    if unreviewed != []:
                        st.verdicts = {}
                    return self._set_phase(n, Phase.MERGED, pr=existing["number"], verdicts=st.verdicts)
                self.store.event("stale_pr_ignored", issue=n, pr=existing["number"], head=merged_head)
            if not self._requirements_current(n):
                self.store.event("requirements_changed", issue=n, previous_phase=Phase.LAND.value)
                st = self.store.issue(n)
                self._owner_edit(st)
                st.body_hash = self.plan.specs[n].body_hash
                self.store.put(st)
                return self._set_phase(n, Phase.PENDING)
            self.ws.fetch()
            if self.ws.nothing_to_land(wt):
                self.store.event("nothing_to_land", issue=n, head=st.certified_sha)
                return self._set_phase(n, Phase.MERGED)
            # Main may have moved since the certificate. Merging it makes a new head, which is
            # verified and certified again (a focused delta examination) before it may land.
            sync = self.ws.update(wt)
            if sync.status == "conflict":
                self.ws.abort_in_progress(wt)
                return self._conflict(n, wt, sync.files, Phase.LAND.value)
            if sync.status == "merged":
                self.store.event("updated_from_main", issue=n, phase=Phase.LAND.value, frm=sync.before,
                                 to=self.ws.head(wt), main=sync.main)
                self._relock(n, wt, self._relock_candidates(n, wt, sync.before), {})
                return self._set_phase(n, Phase.VERIFY)
            try:
                self.ws.push(wt)
            except MergeConflict as e:
                return self._conflict(n, wt, e.files, Phase.LAND.value)
            head = self.ws.head(wt)
            if head != st.certified_sha:
                self.store.event("head_changed_after_certificate", issue=n, certified=st.certified_sha, head=head)
                return self._set_phase(n, Phase.VERIFY)
            body = report.render_pr_body(n, issue.title, st, self.op, self.other)
            pr = self.gh.find_pr(st.branch)
            if pr is None or pr.get("state") != "open":
                pr = self.gh.create_pr(st.branch, self.cfg.base_branch, issue.title, body)
            else:
                self.gh.update_pr(pr["number"], body)
            st.pr = pr["number"]
            self.store.put(st)
            self._upsert_comment(st.pr, report.EVIDENCE_MARKER, report.render_evidence(n, st.evidence, head, st.verdicts))
            conclusion, run_id = self._wait_required(head)
            if conclusion != "success" and head not in st.ci_rerun_heads:
                st.ci_rerun_heads.append(head)
                self.store.put(st)
                rerun = self._safe(self.gh.rerun_failed, head)
                self.store.event("ci_rerun", issue=n, head=head, conclusion=conclusion, started=bool(rerun))
                if rerun:
                    conclusion, run_id = self._wait_required(head, after=run_id)
            if conclusion != "success":
                return self._ci_failed(n, head, conclusion)
            try:
                self.gh.merge_pr(st.pr, head)
            except GitHubError as e:
                again = self._safe(self.gh.find_pr, st.branch) or {}
                if (again.get("merged") or again.get("merged_at")) and (again.get("head") or {}).get("sha", head) == head:
                    self.store.event("merged", issue=n, pr=st.pr, head=head, note="the merge answer was lost")
                    return self._set_phase(n, Phase.MERGED)
                st = self.store.issue(n)
                st.merge_refusals += 1
                self.store.put(st)
                self.store.event("merge_refused", issue=n, error=str(e)[:300], count=st.merge_refusals)
                if st.merge_refusals >= self.caps.merge_refusals:
                    return self._wait(n, WAIT_GITHUB, f"GitHub refused the merge {st.merge_refusals} times: {str(e)[:300]}",
                                      resume=Phase.LAND)
                return self._set_phase(n, Phase.VERIFY)
            self.store.event("merged", issue=n, pr=st.pr, head=head)
            self._set_phase(n, Phase.MERGED)
        finally:
            self.claims.release(MERGE_QUEUE, self.owner)

    def _ci_failed(self, n: int, head: str, conclusion: str | None) -> None:
        if conclusion in CI_NO_VERDICT:
            st = self.store.issue(n)
            st.ci_rerun_heads = [h for h in st.ci_rerun_heads if h != head]
            self.store.put(st)
            return self._wait(n, WAIT_CI, f"the required check gave no verdict on {head[:7]} ({conclusion})",
                              resume=Phase.LAND)
        log = self._safe(self.gh.failed_log, head) or "(no log available)"
        self.store.event("ci_failed", issue=n, head=head, conclusion=conclusion)
        self._round_failed(n, [f"The required CI check is '{conclusion}' on {head[:7]}, also after one re-run. Find and "
                               f"fix the cause; never weaken or skip a check to get green. Tail of the failed log:\n"
                               f"{log[-3000:]}"])

    def _wait_required(self, sha: str, after: int | None = None) -> tuple[str, int | None]:
        waited = 0
        while True:
            run = self.gh.required_check_run(sha, self.cfg.required_check)
            fresh = run is not None and (after is None or run["id"] != after)
            if fresh and run["status"] == "completed" and run["conclusion"] not in (None, "pending"):
                return run["conclusion"], run["id"]
            if waited >= self.caps.ci_timeout_s:
                return ("pending" if fresh else "missing"), (run or {}).get("id")
            self.sleep(self.caps.ci_poll_s)
            waited += self.caps.ci_poll_s

    # ------------------------------------------------------------------ accept
    def _step_accept(self, n: int) -> None:
        with self._accept_lock:
            self._accept(n)

    def _accept(self, n: int) -> None:
        st = self.store.issue(n)
        edited = ["the issue was edited after its work was merged; deliver the edited version"]
        if not self._requirements_current(n):
            return self._owner_round(n, edited)
        coord = self.ws.coord()
        head = self.ws.head(coord)
        ok, evidence, problems, _ = verify.verify(coord, self._specs(st), head, self.store.issue_dir(n), st.locked,
                                                  sorted(set(st.tests) | set(st.probes)), st.manifest or None,
                                                  self.caps.check_timeout_s, extra_env=self.check_env)
        self.store.event("post_merge_verify", issue=n, head=head, ok=ok, problems=problems)
        if not ok:
            env = environment_problem(evidence)
            if env:
                return self._wait(n, WAIT_ENVIRONMENT, f"the host cannot run this issue's checks: {env}",
                                  resume=Phase.MERGED)
            return self._fix_forward(n, ["verification failed on main after the merge: " + "; ".join(problems)[:600]])
        regressions = self._regressions(n, coord, head)
        if regressions:
            return self._fix_forward(n, regressions)
        verdicts = {i: v for i, v in st.verdicts.items() if v.get("verdict") == "met"}
        evidence_comment = (self._upsert_comment(st.pr, report.EVIDENCE_MARKER,
                                                 report.render_evidence(n, evidence, head, verdicts)) if st.pr else None)
        link = (evidence_comment or {}).get("html_url", "")
        proven = {e["criterion"] for e in evidence if e["passed"]} | set(verdicts)
        issue = self.gh.get_issue(n)
        if issue_parser.body_hash(issue.get("body") or "") != st.body_hash:
            return self._owner_round(n, edited)
        owed = self._owner_items(st)
        unproven = [i.id for i in issue_parser.ledger(issue.get("body") or "") if i.id not in proven and i.id not in owed]
        if unproven:
            return self._fix_forward(n, [f"ledger items without evidence on main: {unproven}"])
        ticked = issue_parser.tick(issue.get("body") or "", {cid: link for cid in proven})
        if ticked != (issue.get("body") or ""):
            self._safe(self.gh.edit_issue, n, body=ticked)
        st = self.store.issue(n)
        st.evidence = evidence
        st.human_tasks = [self._obligation_text(o) for o in st.obligations]
        self._file_followup(n, st)
        self._publish_deferred(n, st)
        self.store.put(st)
        self.store.put_section("accepted_checks", str(n), {
            "checks": [c for c in st.commands], "check_files": sorted(set(st.tests) | set(st.probes)),
            "manifest": st.manifest})
        if st.worktree:
            self.ws.remove(Path(st.worktree))
        if st.obligations:
            return self._set_phase(n, Phase.DELIVERED)
        self._safe(self.gh.edit_issue, n, state="closed", state_reason="completed")
        self._set_phase(n, Phase.DONE)
        self._close_trackers(n)

    def _obligation_text(self, o: dict) -> str:
        if o["kind"] == "deferred":
            return f"{o['item']}: waits for {o['detail']}; it reopens by itself when that issue lands"
        part = f" (agents proved: {o['agent_part']})" if o.get("agent_part") and o["agent_part"] != "none" else ""
        return f"{o['item']}: needs {o['detail']}, which this host lacks{part}"

    def _file_followup(self, n: int, st: IssueState) -> None:
        """Reproduced findings that tie to no item or invariant: one follow-up issue per PR."""
        follow = [f for f in st.findings if f.get("status") == "follow_up"]
        if not follow or st.followup:
            return
        lines = [f"- **{f['title']}** — observed: {f.get('observed')}; expected: {f.get('expected')}; reproduce: "
                 f"`{f.get('reproduction') or f.get('probe')}`" for f in follow]
        body = (f"Follow-up to #{n}" + (f" (PR #{st.pr})" if st.pr else "") + ". The other vendor's examination "
                f"reproduced these findings, which no ledger item or safety invariant requires, so they did not block "
                f"the merge:\n\n" + "\n".join(lines) + "\n")
        created = self._safe(self.gh.create_issue, f"Follow-up to #{n}: {len(follow)} non-blocking finding(s)", body,
                             [FOLLOWUP_LABEL[0]])
        if created:
            st.followup = created.get("number")
            self.store.event("followup_filed", issue=n, followup=st.followup, findings=[f["id"] for f in follow])

    def _publish_deferred(self, n: int, st: IssueState) -> None:
        deferred = [o for o in st.obligations if o["kind"] == "deferred"]
        if not deferred:
            return
        self._safe(self.gh.add_labels, n, [DEFERRED_LABEL[0]])
        body = (f"{report.DEFERRED_MARKER}\n**implement loop**: delivered without these items, each waiting for another "
                f"issue. Each reopens by itself (under the supervisor) once that issue is delivered or done:\n\n"
                + "\n".join(f"- {o['item']}: waits for {o['detail']}" for o in deferred) + "\n")
        self._upsert_comment(n, report.DEFERRED_MARKER, body)

    def _owner_round(self, n: int, feedback: list[str]) -> None:
        self._requirements_current(n)
        st = self.store.issue(n)
        self._new_round(st, feedback, owner_edit=True)
        st.body_hash = self.plan.specs[n].body_hash
        self.store.put(st)
        self._set_phase(n, Phase.PENDING)

    def _fix_forward(self, n: int, feedback: list[str]) -> None:
        """A merged change broke `main`: one fix-forward round, then a revert PR through the same
        gates; `main` is never left red."""
        st = self.store.issue(n)
        if st.fix_forwards >= self.caps.fix_forwards:
            return self._revert(n, feedback)
        st.fix_forwards += 1
        self._new_round(st, feedback, owner_edit=False)
        st.phase = Phase.PLANNED if st.plan else Phase.PENDING
        self.store.put(st)
        self.store.event("fix_forward", issue=n, round=st.round)
        self._sync(n)

    def _revert(self, n: int, feedback: list[str]) -> None:
        st = self.store.issue(n)
        merge_sha = None
        pr = self._safe(self.gh.find_pr, st.branch) if st.branch else None
        if pr:
            merge_sha = pr.get("merge_commit_sha")
        if not merge_sha or st.reverts >= self.caps.reverts:
            return self._fail(n, "main_broken", "main fails after the merge and the fix-forward; the revert could not be "
                                                "made: " + "; ".join(feedback)[:500])
        st.reverts += 1
        branch = f"{st.branch}-revert"
        wt = self.ws.issue_worktree(n, branch)
        self.ws.fetch()
        self.ws.git("reset", "--hard", "--quiet", self.ws.base_ref(), cwd=wt)
        self.ws.git("revert", "--no-edit", merge_sha, cwd=wt)
        self.ws.push(wt)
        head = self.ws.head(wt)
        title = f"Revert #{n}: it broke main"
        body = (f"The implement loop reverts PR #{st.pr} for #{n}: after its merge, `main` fails and one fix-forward "
                f"did not repair it.\n\n" + "\n".join(f"- {f}" for f in feedback)[:3000])
        rpr = self.gh.create_pr(branch, self.cfg.base_branch, title, body)
        conclusion, _ = self._wait_required(head)
        if conclusion != "success":
            self.ws.remove(wt)
            return self._fail(n, "main_broken", f"the revert PR #{rpr['number']} did not pass the required check "
                                                f"({conclusion})")
        self.gh.merge_pr(rpr["number"], head)
        self.ws.remove(wt)
        self.store.event("reverted", issue=n, pr=rpr["number"], of=st.pr)
        st = self.store.issue(n)
        self._new_round(st, feedback + [f"Your earlier delivery was reverted in PR #{rpr['number']} because it broke "
                                        f"main; deliver it again without breaking it."], owner_edit=False)
        st.phase = Phase.PLANNED if st.plan else Phase.PENDING
        self.store.put(st)
        self._sync(n)

    def _regressions(self, n: int, coord: Path, head: str) -> list[str]:
        """Re-run the commands of the run's earlier issues on `main` after a merge."""
        out = []
        fields = CheckSpec.__dataclass_fields__
        for key, entry in sorted(self.store.state.get("accepted_checks", {}).items()):
            m = int(key)
            checks = [CheckSpec(**{k: v for k, v in c.items() if k in fields}) for c in entry["checks"]
                      if c.get("kind", "command") == "command"]
            if m == n or not checks:
                continue
            ok, evidence, problems, _ = verify.verify(coord, checks, head, self.store.issue_dir(m) / "regression", {},
                                                      entry.get("check_files", []), entry.get("manifest") or None,
                                                      self.caps.check_timeout_s, extra_env=self.check_env,
                                                      check_tamper=False)
            self.store.event("regression_check", issue=n, of=m, head=head, ok=ok, problems=problems)
            if not ok and not environment_problem(evidence):
                out.append(f"after #{n} merged, #{m}'s checks fail on main: " + "; ".join(problems)[:400])
        return out

    def _reconcile_delivered(self) -> None:
        """A delivered issue whose owner has since ticked every remaining box, and whose deferred
        items' issues have landed, is done (the deferred ones reopen under the supervisor)."""
        for n in self.plan.work:
            st = self.store.issue(n)
            if st.phase != Phase.DELIVERED:
                continue
            body = (self._safe(self.gh.get_issue, n) or {}).get("body") or ""
            items = issue_parser.ledger(body)
            if items and all(i.checked for i in items):
                self._safe(self.gh.edit_issue, n, state="closed", state_reason="completed")
                self.store.event("owner_evidence_complete", issue=n)
                self._set_phase(n, Phase.DONE, human_tasks=[])
                self._close_trackers(n)

    def _close_trackers(self, n: int) -> None:
        parent = self.plan.parent.get(n)
        while parent is not None:
            children = self.plan.tracking.get(parent, [])
            phases = self._phases()
            done = all((c in self.plan.closed_work) or phases.get(c) == Phase.DONE or
                       (c in self.plan.tracking and self.plan.issues[c].state == "closed") for c in children)
            body = (self._safe(self.gh.get_issue, parent) or {}).get("body") or ""
            if not done or any(not item.checked for item in issue_parser.ledger(body)):
                return
            self._safe(self.gh.edit_issue, parent, state="closed", state_reason="completed")
            self.plan.issues[parent].state = "closed"
            self.store.event("tracker_closed", issue=parent)
            parent = self.plan.parent.get(parent)

    # ------------------------------------------------------------------ end
    def _summary(self, stopped: bool) -> dict:
        phases = self._phases()
        counts: dict[str, int] = {}
        for ph in phases.values():
            counts[ph.value] = counts.get(ph.value, 0) + 1
        return {"stopped": stopped, "phases": counts,
                "waiting": {n: f"[{(self.store.issue(n).wait or {}).get('kind')}] {(self.store.issue(n).wait or {}).get('detail')}"
                            for n, ph in phases.items() if ph == Phase.WAITING},
                "failed": {n: f"[{(self.store.issue(n).fail or {}).get('cause')}] {(self.store.issue(n).fail or {}).get('detail')}"
                           for n, ph in phases.items() if ph == Phase.FAILED},
                "owner_obligations": {n: self.store.issue(n).human_tasks for n, ph in phases.items()
                                      if ph == Phase.DELIVERED},
                "added": [m for m in self.plan.work if any(e.get("kind") == "prerequisite_added" for e in [])]}

    def _post_run_summary(self) -> None:
        states = {n: self.store.issue(n) for n in self.plan.work}
        self._upsert_comment(self.plan.root, report.RUN_MARKER, report.render_run_summary(self.plan.root, states))


def has_conflict_markers(path: Path) -> bool:
    return path.is_file() and bool(CONFLICT_MARKER.search(path.read_text(errors="replace")))


def conflict_feedback(files: list[str], locked: list[str]) -> str:
    text = ("Main moved on, and merging it into this branch conflicts. The merge is in progress in your worktree."
            if files or locked else "")
    if files:
        text += (f" Resolve the conflict markers in {', '.join(files)}, keeping the intent of both sides: main's side "
                 f"is work already merged, this branch's side is this issue's work.")
    if locked:
        text += (f" The conflicts in the locked tests {', '.join(locked)} were resolved by the other vendor; do not "
                 f"edit them.")
    return text + " Do not run git merge, commit or abort: the engine concludes the merge."


def environment_problem(evidence: list[dict]) -> str | None:
    for ev in evidence:
        m = ENVIRONMENT_FAILURE.search(ev.get("output_tail") or "")
        if m:
            line = next((l for l in (ev.get("output_tail") or "").splitlines() if m.group(0) in l), m.group(0))
            return f"{ev.get('criterion')}: {line.strip()[:300]}"
    return None


def fault_fingerprint(exc: BaseException) -> str:
    frames = [f for f in traceback.extract_tb(exc.__traceback__) if "implement_loop" in (f.filename or "")]
    where = f"{Path(frames[-1].filename).name}:{frames[-1].name}" if frames else "unknown"
    return hashlib.sha256(f"{type(exc).__name__}@{where}".encode()).hexdigest()[:10]


def engine_frames(exc: BaseException) -> str:
    frames = [f for f in traceback.extract_tb(exc.__traceback__) if "implement_loop" in (f.filename or "")]
    return "\n".join(f"{Path(f.filename).name}:{f.lineno} in {f.name}" for f in frames) or "(no engine frame)"


def redact(text: str, repo_root: Path) -> str:
    home = str(Path.home())
    return text.replace(str(repo_root), "<repo>").replace(home, "~")
