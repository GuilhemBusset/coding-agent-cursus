"""The per-issue state machine and the scheduling loop.

Each issue moves through: pending -> design -> designed -> checks -> implement -> verify ->
review -> land -> merged -> delivered | done. A run never waits for a person (ADR 0011): every
obstacle becomes a recorded decision, a bounded recovery step, or a parked issue, and the run
carries on around it.

- A failed verification goes back to implement, at most `implement_attempts` times; a
  reproduced review defect at most `fix_rounds` times; a red `required` check is re-run once,
  then goes back to implement at most `ci_fixes` times.
- A locked check the implementer shows to be wrong is reproduced by the other vendor and, if it
  is, amended by its author and locked again, at most `check_amendments` times.
- When those run out, or the implementer reports the design impossible, the design is redone
  once with the failure notes (`redesigns`), keeping the work already written.
- After a merge, a failed verification on `main` or a broken earlier issue opens one fix-forward
  round (`fix_forwards`).
- What is left parks the issue with a diagnosis; issues that depend on it park with it.

Steps run on a thread pool, so one issue can be in review while another implements and a
third designs. Landing is serialized through a repo-wide merge-queue claim.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import traceback
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import asdict, replace
from pathlib import Path
from typing import Callable

from . import VERSION, graph, issue_parser, report, scheduler, verify
from .agents import Agents, Design, DesignRequest, ImplementResult, Objection, Proposal
from .config import Config
from .github import GitHub, GitHubError
from .graph import Plan
from .model import (PARK_BLOCKED, PARK_ENGINE_ERROR, PARK_ENVIRONMENT, PARK_EXHAUSTED, PARK_TRANSIENT, CheckSpec,
                    Finding, Issue, IssueState, Phase, SATISFIES_DEPENDENTS, WRITING_PHASES)
from .state import FaultOutbox, RepoClaims, RunStore
from .workspace import GitError, Workspace

LABELS = {
    "loop:design": ("C5DEF5", "implement loop: designing"),
    "loop:building": ("FBCA04", "implement loop: checks, implementation or verification"),
    "loop:review": ("D4C5F9", "implement loop: in review"),
    "loop:landing": ("0E8A16", "implement loop: PR open, merging"),
    "loop:merged": ("BFDADC", "implement loop: merged, verifying on main"),
    "loop:delivered": ("F9D0C4", "implement loop: merged; the owner must provide the remaining evidence"),
    "loop:parked": ("B60205", "implement loop: set aside; see the diagnosis on the issue"),
}
LEGACY_LABELS = ("loop:awaiting-human", "loop:needs-human")
ENGINE_BUG_LABEL = ("loop:engine-bug", "5319E7", "implement loop: a fault in the loop's own engine")
PHASE_LABEL = {
    Phase.DESIGN: "loop:design", Phase.DESIGNED: "loop:design",
    Phase.CHECKS: "loop:building", Phase.IMPLEMENT: "loop:building", Phase.VERIFY: "loop:building",
    Phase.REVIEW: "loop:review", Phase.LAND: "loop:landing", Phase.MERGED: "loop:merged",
    Phase.DELIVERED: "loop:delivered", Phase.PARKED: "loop:parked",
}
EXPLORE_QUESTIONS = (
    "The issue graph and acceptance criteria: what must be true when this run is done?",
    "Existing material and conventions these issues must follow (ADRs, AGENTS.md, guides).",
    "Build, check and CI tooling: how is work validated in this repo today?",
    "External references the issues cite: what do they establish that the work depends on?",
)
MERGE_QUEUE = "merge-queue"
MERGE_REFUSALS = 3   # GitHub refusing the same merge this many times parks the issue until the next run
# Output that means the host cannot run a check, whatever the implementation does.
ENVIRONMENT_FAILURE = re.compile(
    r"error while loading shared libraries|Host system is missing dependencies|Executable doesn't exist at"
    r"|No module named pytest|\b(uv|node|npx|npm|python3?): (command )?not found", re.IGNORECASE)
# A required check that never reached a verdict is an outage, not a failure of the change.
CI_NO_VERDICT = (None, "missing", "pending", "stale", "cancelled", "startup_failure")


class Engine:
    def __init__(self, plan: Plan, store: RunStore, gh: GitHub, ws: Workspace, agents: Agents, cfg: Config,
                 repo_root: Path, log: Callable[[str], None] = print, sleep: Callable[[float], None] = time.sleep,
                 environment: dict | None = None, invoked_at: float | None = None):
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
        self._accept_lock = threading.Lock()  # post-merge verification uses the one coord worktree
        self.invoked_at = invoked_at if invoked_at is not None else time.time()

    # ------------------------------------------------------------------ public
    def run(self) -> dict:
        with self.store.lock():
            # a stop asked of an earlier run: running again means go. One asked after this
            # invocation started (say while the environment was being prepared) still stops it.
            if self.store.clear_stop(older_than=self.invoked_at):
                self.store.event("stale_stop_cleared")
            self.store.event("run_started", root=self.plan.root, mode=self.plan.mode, work=self.plan.work,
                             operator=self.op, other=self.other, version=VERSION, environment=self.env_fingerprint)
            self._ensure_labels()
            self._reconcile()
            self._context()
            stopped = self._loop()
            if not stopped:
                self._park_blocked()
            self._reconcile_delivered()
            self._flush_faults()
            summary = self._summary(stopped)
            self._post_run_summary()
            self.store.event("run_finished", **summary)
            return summary

    # ------------------------------------------------------------------ setup
    def _ensure_labels(self) -> None:
        for name, (color, desc) in LABELS.items():
            self._safe(self.gh.ensure_label, name, color, desc)

    def _reconcile(self) -> None:
        for n in self.plan.work:
            st = self.store.issue(n)
            spec = self.plan.specs[n]
            if st.body_hash and st.body_hash != spec.body_hash:
                if st.phase in (Phase.MERGED, Phase.DELIVERED, Phase.DONE):
                    self._new_round(st, ["the issue was edited after its work was merged; deliver the edited version",
                                         *edited_feedback(st)[1:]], owner_edit=True)
                elif st.phase != Phase.PENDING or st.design:
                    self.store.event("requirements_changed", issue=n, previous_phase=st.phase.value)
                    restart(st, feedback=edited_feedback(st), owner_edit=True)
                    st.phase = Phase.PENDING
            elif st.phase == Phase.DONE:
                # it is in the open work, so someone reopened it: something is missing
                self._new_round(st, ["the issue was reopened after it was closed; find what is missing and deliver it",
                                     *edited_feedback(st)[1:]], owner_edit=True)
            elif st.phase == Phase.PARKED:
                self._maybe_resume(st)
            st.body_hash = spec.body_hash
            st.branch = st.branch or spec.branch or f"loop/issue-{n}"
            if st.design:
                spec.declared_paths = design_paths(st.design.get("files", []), st.design.get("check_files", []), spec.declared_paths)
            self.store.put(st)

    def _maybe_resume(self, st: IssueState) -> None:
        """A parked issue resumes when what parked it may have changed (ADR 0011): never an
        unchanged failure retried without new evidence."""
        kind = st.park_kind
        resume = (st.retry or kind in (PARK_BLOCKED, PARK_TRANSIENT)
                  or (kind == PARK_ENVIRONMENT and self.env_fingerprint is not None and st.parked_env != self.env_fingerprint)
                  or (kind == PARK_ENGINE_ERROR and st.parked_version != VERSION))
        if not resume:
            return
        phase = Phase(st.resume_phase or Phase.PENDING.value)
        if kind == PARK_EXHAUSTED or phase == Phase.PARKED:
            # an explicit retry: one more full set of recovery steps, starting from a new design
            restart(st, feedback=[f"an earlier attempt was set aside: {st.reason}"], owner_edit=True)
            phase = Phase.PENDING
        self.store.event("resumed", issue=st.number, park_kind=kind, phase=phase.value, retry=st.retry)
        st.phase = phase
        st.park_kind = st.resume_phase = st.reason = None
        st.retry = False

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
                        exc = fut.exception()
                        if exc is not None and type(exc).__name__ == "AgentStopped":
                            self.store.event("step_interrupted", issue=n, phase=self.store.issue(n).phase.value)
                        elif exc is not None and type(exc).__name__ == "AgentFailure":
                            # an agent CLI kept failing after its retries: an outage, retried next run
                            self.store.event("agent_unavailable", issue=n, error=str(exc)[:500])
                            self._park(n, PARK_TRANSIENT, f"an agent was unavailable: {str(exc)[:300]}")
                        elif exc is not None:
                            self._engine_fault(n, exc)
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
                    return stopped
                wait(list(running.values()), return_when=FIRST_COMPLETED)

    def _phases(self) -> dict[int, Phase]:
        return {n: self.store.issue(n).phase for n in self.plan.work}

    def _dispatch(self, pool: ThreadPoolExecutor, running: dict[int, Future]) -> None:
        phases = self._phases()
        writers = [n for n, ph in phases.items() if ph in WRITING_PHASES]
        landing = any(phases[n] == Phase.LAND for n in running)
        steps = {Phase.DESIGN: self._step_design, Phase.CHECKS: self._step_checks, Phase.IMPLEMENT: self._step_implement,
                 Phase.VERIFY: self._step_verify, Phase.REVIEW: self._step_review, Phase.MERGED: self._step_accept}
        for n in self.plan.work:
            if n in running:
                continue
            ph = phases[n]
            if ph == Phase.PENDING:
                if scheduler.prerequisites_met(self.plan, phases, n):
                    self._set_phase(n, Phase.DESIGN)
                    running[n] = pool.submit(self._step_design, n)
            elif ph == Phase.DESIGNED:
                if scheduler.can_start_writing(self.plan, n, writers, self.caps.max_parallel_writers):
                    writers.append(n)
                    self._set_phase(n, Phase.CHECKS)
                    running[n] = pool.submit(self._step_checks, n)
            elif ph == Phase.LAND:
                if not landing and self.claims.acquire(MERGE_QUEUE, self.owner):
                    landing = True
                    running[n] = pool.submit(self._step_land, n)
            elif ph in steps:
                running[n] = pool.submit(steps[ph], n)

    # ------------------------------------------------------------------ helpers
    def _req(self, n: int, lens: str = "", feedback: list[str] | None = None) -> DesignRequest:
        return DesignRequest(issue=self.plan.issues[n], spec=self.plan.specs[n],
                             context=self.store.state.get("context") or "", lens=lens, feedback=feedback or [])

    def _design(self, st: IssueState) -> Design:
        fields = Design.__dataclass_fields__
        d = {k: v for k, v in st.design.items() if k in fields}  # the stored design also carries review notes
        d["checks"] = [CheckSpec(**c) for c in d["checks"]]
        return Design(**d)

    def _checks(self, st: IssueState) -> list[CheckSpec]:
        return [CheckSpec(**c) for c in st.checks]

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

    def _park(self, n: int, kind: str, reason: str, resume: Phase | None = None) -> None:
        """Set an issue aside with a diagnosis. The run carries on; what may resume it on a
        later run depends on `kind` (see `_maybe_resume`)."""
        st = self.store.issue(n)
        st.park_kind, st.reason = kind, reason
        st.resume_phase = (resume or st.phase).value
        st.parked_env = self.env_fingerprint if kind == PARK_ENVIRONMENT else None
        st.parked_version = VERSION if kind == PARK_ENGINE_ERROR else None
        st.retry = False
        self.store.put(st)
        self.store.event("parked", issue=n, park_kind=kind, reason=reason[:800], resume=st.resume_phase)
        self.log(f"#{n} parked ({kind}): {reason}")
        self._set_phase(n, Phase.PARKED)

    def _redesign_or_park(self, n: int, feedback: list[str]) -> None:
        """The last recovery step before parking: design again with the failure notes, keeping
        the branch and the work already written."""
        st = self.store.issue(n)
        if st.redesigns >= self.caps.redesigns:
            return self._park(n, PARK_EXHAUSTED, "; ".join(feedback)[:800])
        st.redesigns += 1
        notes = [f"The previous design failed; this is redesign {st.redesigns}. Keep what works in the branch.", *feedback]
        if st.design and st.design.get("decisions"):
            notes.append("Previous decisions: " + json.dumps(st.design["decisions"])[:1500])
        restart(st, feedback=notes)
        self.store.put(st)
        self.store.event("redesign", issue=n, count=st.redesigns, reason=feedback[0][:400] if feedback else "")
        self._set_phase(n, Phase.PENDING)

    def _new_round(self, st: IssueState, feedback: list[str], owner_edit: bool) -> None:
        """Deliver an already-merged issue again (it was edited, reopened, or broke something on
        `main`): a new branch from `main`, a new design, the old evidence discarded."""
        n = st.number
        if st.worktree:
            self.ws.remove(Path(st.worktree))
        st.round += 1
        st.branch = f"{self.plan.specs[n].branch or f'loop/issue-{n}'}-r{st.round}"
        st.worktree = st.pr = st.checks_sha = st.head_sha = st.base_sha = None
        st.human_tasks = []
        restart(st, feedback=feedback, owner_edit=owner_edit)
        st.superseded = []   # earlier rounds' checks are on main now: durable, not superseded
        st.phase = Phase.PENDING
        self.store.event("new_round", issue=n, round=st.round, reason=feedback[0][:400], owner_edit=owner_edit)

    def _fix_forward(self, n: int, feedback: list[str]) -> None:
        st = self.store.issue(n)
        if st.fix_forwards >= self.caps.fix_forwards:
            return self._park(n, PARK_EXHAUSTED, "; ".join(feedback)[:800])
        st.fix_forwards += 1
        previous = st.phase
        self._new_round(st, feedback, owner_edit=False)
        st.phase = previous
        self.store.put(st)
        self._set_phase(n, Phase.PENDING)

    def _engine_fault(self, n: int, exc: BaseException) -> None:
        """An engine bug: journal it, queue one GitHub issue per distinct fault, park the item."""
        # The full traceback and message stay in the local event log. What is published (the
        # repository is public) is allowlisted: the exception type and the engine's own frames.
        detail = redact("".join(traceback.format_exception(exc))[-2500:], self.repo_root)
        fingerprint = fault_fingerprint(exc)
        phase = self.store.issue(n).phase.value
        self.store.event("step_crashed", issue=n, error=redact(repr(exc), self.repo_root)[:500], traceback=detail,
                         fingerprint=fingerprint)
        title = f"implement loop: {type(exc).__name__} in the engine ({fingerprint})"
        body = (f"{report.FAULT_MARKER.format(fingerprint)}\nThe implement loop's engine raised `{type(exc).__name__}` "
                f"in phase `{phase}` while working on #{n} (run for #{self.plan.root}, engine {VERSION}). The issue "
                f"was parked and the run carried on. The message and full traceback are in the local run log "
                f"(`events.jsonl`, event `step_crashed`, fingerprint `{fingerprint}`).\n\nEngine frames:\n\n"
                f"```\n{engine_frames(exc)}\n```\n")
        self.faults.record(fingerprint, title, body, issue=n, run=self.plan.root)
        self._park(n, PARK_ENGINE_ERROR, f"engine error {type(exc).__name__} in phase {phase} (fault {fingerprint}; "
                                         f"details in the local run log)")

    def _flush_faults(self) -> None:
        """File queued engine faults. A failure to file stays a local event: it never re-enters
        the fault path."""
        self._safe(self.gh.ensure_label, *ENGINE_BUG_LABEL)
        for fingerprint, entry in self.faults.pending():
            try:
                # an earlier attempt may have created the issue and lost the response: look first
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
        """Re-read the issue: is it still the version the design and checks were built from?"""
        data = self.gh.get_issue(n)
        st = self.store.issue(n)
        if issue_parser.body_hash(data.get("body") or "") == st.body_hash:
            return True
        issue = Issue.from_api(data)
        self.plan.issues[n] = issue
        self.plan.specs[n] = issue_parser.parse(issue, graph.existing_session_dirs(self.repo_root))
        return False

    def _merge_base(self, wt: Path) -> str:
        """Where this branch meets the current base branch; moves forward when main is merged in."""
        return self.ws.git("merge-base", "HEAD", self.ws.base_ref(), cwd=wt)

    def _absorb_agent_commits(self, n: int, wt: Path, before: str, refs_before: dict[str, str]) -> None:
        """Only the engine creates history. If an agent committed anyway, keep its changes but
        undo the commits, so they are committed, verified and reviewed like everything else.
        Tags and branches an agent created are deleted (run branches are the engine's)."""
        head = self.ws.head(wt)
        if head != before:
            self.ws.git("reset", "--soft", "--quiet", before, cwd=wt)
            self.store.event("agent_commits_absorbed", issue=n, from_head=head, to=before)
        run_branches = {f"refs/heads/{self.store.issue(m).branch}" for m in self.plan.work}
        created = [r for r in self.ws.refs() if r not in refs_before and r not in run_branches]
        for ref in created:
            self.ws.git("update-ref", "-d", ref, check=False)
        if created:
            self.store.event("agent_refs_deleted", issue=n, refs=created)

    def _delivery(self, st: IssueState, merged_head: str) -> tuple[str, list[str] | None]:
        """How a merged PR found on the issue's branch relates to this delivery: "same" (the
        reviewed head), "later" (the reviewed head plus more commits; with the reviewed paths
        those commits touched, or None if they cannot be seen), or "stale" (an older PR of a
        reused branch name)."""
        reviewed, repo = st.reviewed_sha, self.ws.repo   # the worktree may be gone already
        if not reviewed or merged_head == reviewed:
            return "same", []
        self.ws.git("fetch", "--quiet", self.ws.remote, merged_head, cwd=repo, check=False)
        if not self.ws.has_commit(repo, merged_head):
            return "later", None
        if not self.ws.is_ancestor(repo, reviewed, merged_head):
            return "stale", None
        # the delivered tree against the reviewed one, merge resolutions included
        touched = self.ws.git("diff", "--name-only", reviewed, merged_head, cwd=repo)
        allowed = self.plan.specs[st.number].declared_paths
        return "later", sorted({f for f in touched.splitlines() if f and any(scheduler.overlaps(f, a) for a in allowed)})

    def _verify(self, root: Path, st: IssueState, head: str, work_dir: Path, check_tamper: bool = True):
        design = self._design(st)
        return verify.verify(root, self._checks(st), head, work_dir, st.locked, design.check_files,
                             st.expected_tests.get("*", []), self.caps.check_timeout_s,
                             extra_env=self.check_env, check_tamper=check_tamper)

    # ------------------------------------------------------------------ steps
    def _step_design(self, n: int) -> None:
        st = self.store.issue(n)
        issue, spec = self.plan.issues[n], self.plan.specs[n]
        feedback = list(st.feedback)
        req = self._req(n, feedback=feedback)
        st.design_rounds += 1
        if issue.size == "S":
            proposals = [self.agents.propose(self.op, self._req(n, "smallest correct implementation", feedback), "A")]
        else:
            proposals = [self.agents.propose(self.op, self._req(n, "smallest correct implementation", feedback), "A"),
                         self.agents.propose(self.other, self._req(n, "verification first: how each criterion is proven", feedback), "B")]
        objections: list[Objection] = self.agents.audit(self.other, req, proposals)
        diverged = len({tuple(sorted(p.decisions.items())) for p in proposals}) > 1
        if diverged or any(o.blocking for o in objections):
            objections += self.agents.critique(self.op, req, proposals, objections)
        design, problems = repair_design(self.agents.judge(self.op, req, proposals, objections), spec)
        if problems:
            design, problems = repair_design(self.agents.judge(self.op, self._req(n, feedback=feedback + problems),
                                                               proposals, objections), spec)
        self.store.event("design", issue=n, rounds=st.design_rounds, diverged=diverged,
                         blocking=[o.text for o in objections if o.blocking], problems=problems,
                         decisions=len(design.decision_log))
        if problems:
            self.store.put(st)
            return self._redesign_or_park(n, [f"the judge could not produce a usable design: {'; '.join(problems)}"])
        st.design = asdict(design)
        st.checks = [asdict(c) for c in design.checks]
        self.store.put(st)
        missed = [p for p in spec.declared_paths if "." in p.split("/")[-1]
                  and not any(scheduler.overlaps(p, f) for f in design.files + design.check_files)]
        if missed:
            self.store.event("design_may_miss_paths", issue=n, paths=missed)
        spec.declared_paths = design_paths(design.files, design.check_files, spec.declared_paths)
        self._set_phase(n, Phase.DESIGNED)

    def _step_checks(self, n: int) -> None:
        st = self.store.issue(n)
        design = self._design(st)
        wt = self.ws.issue_worktree(n, st.branch)
        checkish = list(design.check_files) + list(st.locked) + list(st.superseded)
        leftover = [f for f in self.ws.uncommitted(wt) if not any(scheduler.overlaps(f, c) for c in checkish)]
        if leftover:
            # work an interrupted implementer left behind: keep it, so the check author's lane is
            # judged against a clean tree and nothing of it is discarded below. Pending edits to
            # check files stay in the tree: only an acceptance-checks commit may carry them.
            self.ws.commit_paths(wt, leftover, f"Checkpoint #{n} before writing checks", "implementation", n)
            self.store.event("checkpoint_before_checks", issue=n, files=leftover)
        base = self.ws.git("merge-base", "HEAD", self.ws.base_ref(), cwd=wt)
        amending = bool(st.amend)
        # an amendment may rewrite only the check whose defect was reproduced
        lane = [st.amend_file] if amending and st.amend_file else design.check_files
        # Checks an earlier, unmerged design locked and this one no longer uses are retired, in the
        # engine and in the CI guard alike, so old and new suites never contradict each other.
        retired = [f for f in st.superseded if f not in design.check_files and (wt / f).is_file()
                   and not self.ws.exists_at(wt, self.ws.base_ref(), f)]
        for f in retired:
            (wt / f).unlink()
        if design.check_files:
            before, refs_before = self.ws.head(wt), self.ws.refs()
            self.agents.write_checks(self.other, self._req(n), replace(design, check_files=lane), wt,
                                     feedback=st.amend or None)
            self._absorb_agent_commits(n, wt, before, refs_before)
            outside = [f for f in self.ws.uncommitted(wt)
                       if f not in retired and not any(scheduler.overlaps(f, c) for c in lane)]
            if outside:
                for f in outside:
                    self.ws.git("reset", "-q", "--", f, cwd=wt, check=False)   # staged changes too
                    self.ws.git("checkout", "--", f, cwd=wt, check=False)
                    self.ws.git("clean", "-fdq", "--", f, cwd=wt, check=False)
                self.store.event("check_author_out_of_lane", issue=n, discarded=outside)
        subject = "Amend acceptance checks" if amending else "Add acceptance checks"
        sha = self.ws.commit_all(wt, f"{subject} for #{n}", "acceptance-checks", n, unlocks=retired)
        written = [f for f in design.check_files if (wt / f).exists()]
        if design.check_files and not written:
            return self._redesign_or_park(n, [f"the check author wrote none of the check files {design.check_files}"])
        cwds = sorted({c.cwd for c in design.checks if c.kind == "command"})
        locked = verify.lock(wt, design.check_files, cwds)
        expected = verify.expected_tests(wt, design.check_files)
        self.store.event("checks_locked", issue=n, sha=sha, locked=sorted(locked), expected_tests=expected,
                         amended=amending, retired=retired)
        feedback = ([f"The locked checks were amended after an independent agent reproduced the defect you reported: "
                     f"{st.amend[0][:600]}"] if amending else st.feedback)
        self._set_phase(n, Phase.IMPLEMENT, worktree=str(wt), base_sha=base, checks_sha=sha or st.checks_sha,
                        locked=locked, expected_tests={"*": expected}, superseded=[], amend=[], amend_file=None,
                        feedback=feedback)

    def _step_implement(self, n: int) -> None:
        st = self.store.issue(n)
        wt = Path(st.worktree)
        before, refs_before = self.ws.head(wt), self.ws.refs()
        result = self.agents.implement(self.op, self._req(n), self._design(st), wt, st.feedback)
        self._absorb_agent_commits(n, wt, before, refs_before)
        if result.status == "done":
            sha = self._commit_work(n, wt, f"Implement #{n} (attempt {st.attempts + 1})")
            self.store.event("implemented", issue=n, sha=sha, attempt=st.attempts + 1)
            self._set_phase(n, Phase.VERIFY, head_sha=self.ws.head(wt))
            return
        # Whatever the implementer wrote is kept: the next attempt or design starts from it.
        sha = self._commit_work(n, wt, f"Checkpoint #{n} (attempt {st.attempts + 1})")
        self.store.event("implementer_stopped", issue=n, status=result.status, note=result.note[:800], checkpoint=sha)
        if result.status == "check_defect":
            return self._check_defect(n, wt, result)
        self._redesign_or_park(n, [f"the implementer reported the design impossible: {result.note}"])

    def _commit_work(self, n: int, wt: Path, subject: str) -> str | None:
        """Commit the implementer's work, minus any edit to a locked check: once committed, such
        an edit would fail the CI guard for good, since run branches are never rewritten."""
        st = self.store.issue(n)
        check_files = (st.design or {}).get("check_files", [])
        # Only the checks themselves: a changed test configuration (say pyproject.toml's pytest
        # table) is not part of the checks commit, so verification reports it instead, and the
        # implementer's other edits to that file are kept.
        touched = [rel for rel, d in st.locked.items() if any(scheduler.overlaps(rel, c) for c in check_files)
                   and (not (wt / rel).is_file() or verify.digest(wt / rel) != d)]
        if touched:
            self.ws.git("checkout", "HEAD", "--", *touched, cwd=wt, check=False)
            self.store.event("locked_changes_reverted", issue=n, files=touched)
            st.reverted = touched
            self.store.put(st)
        return self.ws.commit_all(wt, subject, "implementation", n)

    def _check_defect(self, n: int, wt: Path, result: ImplementResult) -> None:
        """The implementer says a locked check is wrong. The other vendor tries to reproduce it;
        a reproduced defect is amended by the check's author, anything else is feedback."""
        st = self.store.issue(n)
        claim = f"{result.defect_file}: {result.note}. Reproduction: {result.defect_reproduction}"
        if result.defect_file not in st.locked:
            st.attempts += 1
            self.store.put(st)
            feedback = [f"{result.defect_file} is not one of the locked checks ({sorted(st.locked)}); name the check "
                        f"file that is wrong, or make the checks pass. Your report was: {result.note}"]
            if st.attempts >= self.caps.implement_attempts:
                return self._redesign_or_park(n, feedback)
            return self._set_phase(n, Phase.IMPLEMENT, feedback=feedback)
        if st.check_amendments >= self.caps.check_amendments:
            return self._redesign_or_park(n, [f"a locked check is still disputed after {st.check_amendments} "
                                              f"amendment(s): {claim}"])
        finding = Finding(id=f"C{n}-{st.check_amendments + 1}", reviewer="implementer", priority=0, confidence=1.0,
                          title=f"the locked check is defective: {result.note}", file=result.defect_file,
                          reproduction=result.defect_reproduction)
        reproduced = self.agents.verify_finding(self.other, self._req(n), wt, finding)
        self.store.event("check_defect_claimed", issue=n, file=result.defect_file, reproduced=reproduced)
        if reproduced:
            st.check_amendments += 1
            self.store.put(st)
            return self._set_phase(n, Phase.CHECKS, amend=[claim], amend_file=result.defect_file)
        st.attempts += 1
        self.store.put(st)
        verdict = "could not be reproduced" if reproduced is False else "could not be confirmed"
        feedback = [f"Your report that {result.defect_file} is defective {verdict} by an independent agent. "
                    f"Make the locked checks pass without changing them. Your report was: {result.note}"]
        if st.attempts >= self.caps.implement_attempts:
            return self._redesign_or_park(n, feedback)
        self._set_phase(n, Phase.IMPLEMENT, feedback=feedback)

    def _step_verify(self, n: int) -> None:
        st = self.store.issue(n)
        wt = Path(st.worktree)
        head = self.ws.head(wt)
        ok, evidence, problems = self._verify(wt, st, head, self.store.issue_dir(n))
        st.base_sha = self._merge_base(wt)
        allowed = self.plan.specs[n].declared_paths
        undeclared = [f for f in self.ws.changed_files(wt, st.base_sha) if not any(scheduler.overlaps(f, a) for a in allowed)]
        if undeclared:
            ok = False
            problems.append(f"changed files outside the declared paths: {undeclared[:8]}")
        self.store.event("verified", issue=n, head=head, ok=ok, problems=problems)
        if ok:
            self._set_phase(n, Phase.REVIEW, evidence=evidence, head_sha=head, verified_sha=head,
                            base_sha=st.base_sha, feedback=[], blockers=[], reverted=[])
            return
        if st.reverted:
            problems.insert(0, f"your edits to the locked checks {st.reverted} were reverted; make them pass unchanged")
            st.reverted = []
        env = environment_problem(evidence)
        if env:
            self.store.put(st)
            return self._park(n, PARK_ENVIRONMENT, f"the host cannot run this issue's checks: {env}", resume=Phase.VERIFY)
        st.attempts += 1
        st.blockers.append(" | ".join(sorted(p.split(":")[0] + ":" + p.split(":", 1)[-1][:80] for p in problems)))
        st.evidence, st.head_sha = evidence, head
        self.store.put(st)
        limit = self.caps.same_blocker_limit
        if st.attempts >= self.caps.implement_attempts:
            return self._redesign_or_park(n, [f"verification failed {st.attempts} times: " + "; ".join(problems)[:600]])
        if len(st.blockers) >= limit and len(set(st.blockers[-limit:])) == 1:
            return self._redesign_or_park(n, ["the same verification failure repeated: " + st.blockers[-1][:600]])
        self._set_phase(n, Phase.IMPLEMENT, feedback=problems)

    def _review_roles(self, n: int) -> list[tuple[str, str]]:
        roles = [("cross", self.other), ("acceptance", self.op)]
        if any(p.endswith((".html", ".htm")) for p in self.plan.specs[n].declared_paths):
            roles.append(("visual", self.op))
        return roles

    def _step_review(self, n: int) -> None:
        st = self.store.issue(n)
        wt = Path(st.worktree)
        design, req = self._design(st), self._req(n)
        head = self.ws.head(wt)
        if head != st.verified_sha:
            self.store.event("head_changed_before_review", issue=n, verified=st.verified_sha, head=head)
            return self._set_phase(n, Phase.VERIFY)

        def one(role_vendor):
            role, vendor = role_vendor
            for _ in range(2):  # a reviewer outage gets one retry
                result = self.agents.review(vendor, role, req, design, wt, st.base_sha, head, st.evidence)
                if result is not None:
                    return role, result
            return role, None

        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(one, self._review_roles(n)))
        missing = [role for role, r in results if r is None]
        if missing:
            return self._park(n, PARK_TRANSIENT, f"review missing after a retry: {', '.join(missing)}")
        findings: list[Finding] = [f for _, r in results for f in r.findings]
        coverage = {}
        for role, r in results:
            if role == "cross":
                coverage.update(r.coverage)
        candidates = [f for f in findings if (f.file or f.reproduction) and
                      (f.claims_acceptance_failure or (f.priority <= 1 and f.confidence >= 0.8)
                       or (f.priority <= 2 and f.confidence >= 0.9 and f.reproduction))]
        verdicts = [(f, self.agents.verify_finding(self.op, req, wt, f)) for f in candidates]
        verified = [f for f, v in verdicts if v]
        unresolved = [f.id for f, v in verdicts if v is None]
        # could not be verified either way: never treated as disproved, so it is published as advisory
        advisory = [asdict(f) | {"unresolved": f.id in unresolved} for f in findings if f not in verified]
        self.store.event("reviewed", issue=n, head=head, findings=len(findings), verified=[f.id for f in verified],
                         unresolved=unresolved)
        if verified:
            st.fix_rounds += 1
            self.store.put(st)
            feedback = [f"[{f.reviewer} P{f.priority}] {f.title} ({f.file}:{f.line}). Reproduce: {f.reproduction}" for f in verified]
            if st.fix_rounds > self.caps.fix_rounds:
                return self._redesign_or_park(n, ["reproduced defects remain after the fix rounds: "
                                                  + "; ".join(f.title for f in verified)])
            return self._set_phase(n, Phase.IMPLEMENT, feedback=feedback)
        artifact = [{"criterion": c.criterion, "kind": "artifact", "command": None, "cwd": "", "head_sha": head,
                     "exit_code": None, "passed": bool(coverage.get(c.criterion)), "duration_s": 0,
                     "output_tail": "", "output_sha256": "", "note": f"judged by the {self.other} reviewer"}
                    for c in self._checks(st) if c.kind == "artifact"]
        unmet = [a["criterion"] for a in artifact if not a["passed"]]
        if unmet:
            st.fix_rounds += 1
            self.store.put(st)
            if st.fix_rounds > self.caps.fix_rounds:
                return self._redesign_or_park(n, [f"reviewers still judge these criteria unmet: {unmet}"])
            return self._set_phase(n, Phase.IMPLEMENT, feedback=[f"reviewers judge criterion {c} unmet" for c in unmet])
        st = self.store.issue(n)
        st.evidence = [e for e in st.evidence if e["kind"] != "artifact"] + artifact
        st.design = {**st.design, "advisory": advisory}
        self.store.put(st)
        self._set_phase(n, Phase.LAND, reviewed_sha=head, rereview=False)

    def _step_land(self, n: int) -> None:
        try:
            st = self.store.issue(n)
            wt = Path(st.worktree)
            issue = self.plan.issues[n]
            if st.reviewed_sha != st.verified_sha:
                return self._set_phase(n, Phase.VERIFY)
            existing = self.gh.find_pr(st.branch)
            if existing and (existing.get("merged") or existing.get("merged_at")):
                merged_head = (existing.get("head") or {}).get("sha") or st.reviewed_sha
                relation, unreviewed = self._delivery(st, merged_head)
                if relation == "same":   # merged before a crash, but the merge was never recorded
                    self.store.event("merge_found_on_resume", issue=n, pr=existing["number"])
                    return self._set_phase(n, Phase.MERGED, pr=existing["number"])
                if relation == "later":
                    # merged by someone else after more commits: verification on main decides, and
                    # reviewer judgements stand only if no reviewed path changed since the review
                    self.store.event("merged_externally", issue=n, pr=existing["number"], head=merged_head,
                                     reviewed=st.reviewed_sha, unreviewed=unreviewed)
                    evidence = st.evidence if unreviewed == [] else [e for e in st.evidence if e["kind"] != "artifact"]
                    return self._set_phase(n, Phase.MERGED, pr=existing["number"], evidence=evidence)
                # an older PR of a reused branch name, from before this delivery: not ours
                self.store.event("stale_pr_ignored", issue=n, pr=existing["number"], head=merged_head)
            if not self._requirements_current(n):
                self.store.event("requirements_changed", issue=n, previous_phase=Phase.LAND.value)
                st = self.store.issue(n)
                restart(st, feedback=edited_feedback(st), owner_edit=True)
                st.body_hash = self.plan.specs[n].body_hash
                self.store.put(st)
                return self._set_phase(n, Phase.PENDING)
            self.ws.fetch()
            if self.ws.nothing_to_land(wt):
                self.store.event("nothing_to_land", issue=n, head=st.reviewed_sha)
                return self._set_phase(n, Phase.MERGED)
            self.ws.push(wt)
            head = self.ws.head(wt)
            if head != st.reviewed_sha:
                self.store.event("head_changed_after_review", issue=n, reviewed=st.reviewed_sha, head=head)
                return self._set_phase(n, Phase.VERIFY, rereview=True)
            body = report.render_pr_body(n, issue.title, st.design, (st.design or {}).get("advisory", []), self.op, self.other)
            pr = self.gh.find_pr(st.branch)
            if pr is None or pr.get("state") != "open":
                pr = self.gh.create_pr(st.branch, self.cfg.base_branch, issue.title, body)
            else:
                self.gh.update_pr(pr["number"], body)
            st.pr = pr["number"]
            self.store.put(st)
            self._upsert_comment(st.pr, report.EVIDENCE_MARKER, report.render_evidence(n, st.evidence, head))
            conclusion, run_id = self._wait_required(head)
            if conclusion != "success" and head not in st.ci_rerun_heads:
                st.ci_rerun_heads.append(head)
                self.store.put(st)
                rerun = self._safe(self.gh.rerun_failed, head)
                self.store.event("ci_rerun", issue=n, head=head, conclusion=conclusion, started=bool(rerun))
                if rerun:   # wait for the re-run's own verdict, not the failure it replaces
                    conclusion, run_id = self._wait_required(head, after=run_id)
            if conclusion != "success":
                return self._ci_failed(n, head, conclusion)
            try:
                self.gh.merge_pr(st.pr, head)
            except GitHubError as e:
                st = self.store.issue(n)
                st.merge_refusals += 1
                self.store.put(st)
                self.store.event("merge_refused", issue=n, error=str(e)[:300], count=st.merge_refusals)
                if st.merge_refusals >= MERGE_REFUSALS:
                    return self._park(n, PARK_TRANSIENT, f"GitHub refused the merge {st.merge_refusals} times: {str(e)[:300]}")
                return self._set_phase(n, Phase.VERIFY, rereview=True)
            self.store.event("merged", issue=n, pr=st.pr, head=head)
            self._set_phase(n, Phase.MERGED)
        finally:
            self.claims.release(MERGE_QUEUE, self.owner)

    def _ci_failed(self, n: int, head: str, conclusion: str | None) -> None:
        if conclusion in CI_NO_VERDICT:
            st = self.store.issue(n)
            st.ci_rerun_heads = [h for h in st.ci_rerun_heads if h != head]   # resuming may re-run it once more
            self.store.put(st)
            return self._park(n, PARK_TRANSIENT, f"the required check gave no verdict on {head[:7]} ({conclusion})",
                              resume=Phase.LAND)
        st = self.store.issue(n)
        st.ci_fixes += 1
        self.store.put(st)
        log = self._safe(self.gh.failed_log, head) or "(no log available)"
        self.store.event("ci_failed", issue=n, head=head, conclusion=conclusion, fix=st.ci_fixes)
        feedback = [f"The required CI check is '{conclusion}' on {head[:7]}, also after one re-run. Find and fix the "
                    f"cause; never weaken or skip a check to get green. Tail of the failed log:\n{log[-3000:]}"]
        if st.ci_fixes > self.caps.ci_fixes:
            return self._park(n, PARK_EXHAUSTED, feedback[0][:800])
        self._set_phase(n, Phase.IMPLEMENT, feedback=feedback)

    def _wait_required(self, sha: str, after: int | None = None) -> tuple[str, int | None]:
        """The `required` check's verdict on `sha`, and its check run id. With `after`, a run with
        that id is a verdict already seen: keep waiting for the next one."""
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
        ok, evidence, problems = self._verify(coord, st, head, self.store.issue_dir(n))
        self.store.event("post_merge_verify", issue=n, head=head, ok=ok, problems=problems)
        if not ok:
            env = environment_problem(evidence)
            if env:
                return self._park(n, PARK_ENVIRONMENT, f"the host cannot run this issue's checks: {env}", resume=Phase.MERGED)
            return self._fix_forward(n, ["verification failed on main after the merge: " + "; ".join(problems)[:600]])
        regressions = self._regressions(n, coord, head)
        if regressions:
            return self._fix_forward(n, regressions)
        artifact = [e for e in st.evidence if e["kind"] == "artifact" and e["passed"]]
        evidence_comment = self._upsert_comment(st.pr, report.EVIDENCE_MARKER, report.render_evidence(n, evidence, head, artifact)) if st.pr else None
        link = (evidence_comment or {}).get("html_url", "")
        proven = {e["criterion"] for e in evidence if e["passed"]} | {e["criterion"] for e in artifact}
        manual = [c for c in self._checks(st) if c.kind == "manual"]
        issue = self.gh.get_issue(n)
        if issue_parser.body_hash(issue.get("body") or "") != st.body_hash:
            # edited while post-merge verification ran: this body is not what the evidence proves
            return self._owner_round(n, edited)
        unproven = [i.id for i in issue_parser.ledger(issue.get("body") or "")
                    if i.id not in proven and i.id not in {c.criterion for c in manual}]
        if unproven:
            return self._fix_forward(n, [f"ledger items without evidence on main: {unproven}"])
        ticked = issue_parser.tick(issue.get("body") or "", {cid: link for cid in proven})
        if ticked != (issue.get("body") or ""):
            self._safe(self.gh.edit_issue, n, body=ticked)
        st = self.store.issue(n)
        st.evidence = evidence + artifact
        st.human_tasks = [f"{c.criterion}: {c.description}" for c in manual]
        self.store.put(st)
        # later merges re-run these on main, in this invocation and any later one (decision 8)
        self.store.put_section("accepted_checks", str(n), {
            "checks": [c for c in st.checks if c.get("kind") == "command"],
            "check_files": (st.design or {}).get("check_files", []), "expected": st.expected_tests.get("*", [])})
        if st.worktree:
            self.ws.remove(Path(st.worktree))
        if manual:
            return self._set_phase(n, Phase.DELIVERED)
        self._safe(self.gh.edit_issue, n, state="closed", state_reason="completed")
        self._set_phase(n, Phase.DONE)
        self._close_trackers(n)

    def _owner_round(self, n: int, feedback: list[str]) -> None:
        self._requirements_current(n)   # refresh the plan from the edited body
        st = self.store.issue(n)
        previous = st.phase
        self._new_round(st, feedback + edited_feedback(st)[1:], owner_edit=True)
        st.body_hash = self.plan.specs[n].body_hash
        st.phase = previous
        self.store.put(st)
        self._set_phase(n, Phase.PENDING)

    def _regressions(self, n: int, coord: Path, head: str) -> list[str]:
        """Re-run the command checks of the run's earlier issues on `main` after a merge: a later
        issue once broke an earlier one's evidence unseen (ADR 0011, decision 8)."""
        out = []
        for key, entry in sorted(self.store.state.get("accepted_checks", {}).items()):
            m = int(key)
            checks = [CheckSpec(**c) for c in entry["checks"]]
            if m == n or not checks:
                continue
            ok, evidence, problems = verify.verify(coord, checks, head, self.store.issue_dir(m) / "regression", {},
                                                   entry["check_files"], entry["expected"], self.caps.check_timeout_s,
                                                   extra_env=self.check_env, check_tamper=False)
            self.store.event("regression_check", issue=n, of=m, head=head, ok=ok, problems=problems)
            if not ok and not environment_problem(evidence):
                out.append(f"after #{n} merged, #{m}'s checks fail on main: " + "; ".join(problems)[:400])
        return out

    def _reconcile_delivered(self) -> None:
        """A delivered issue whose owner has since ticked every remaining box is done."""
        for n in self.plan.work:
            if self.store.issue(n).phase != Phase.DELIVERED:
                continue
            body = (self._safe(self.gh.get_issue, n) or {}).get("body") or ""
            items = issue_parser.ledger(body)
            if items and all(i.checked for i in items):
                self._safe(self.gh.edit_issue, n, state="closed", state_reason="completed")
                self.store.event("owner_evidence_complete", issue=n)
                self._set_phase(n, Phase.DONE, human_tasks=[])
                self._close_trackers(n)

    def _park_blocked(self) -> None:
        """Issues waiting on a parked prerequisite are parked too, so the report says why."""
        changed = True
        while changed:
            changed = False
            phases = self._phases()
            for n in self.plan.work:
                parked = [d for d in sorted(self.plan.deps.get(n, ())) if phases.get(d) == Phase.PARKED]
                if phases[n] == Phase.PENDING and parked:
                    self._park(n, PARK_BLOCKED, f"waiting for #{parked[0]}, which is parked", resume=Phase.PENDING)
                    changed = True

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
                "parked": {n: f"[{self.store.issue(n).park_kind}] {self.store.issue(n).reason}"
                           for n, ph in phases.items() if ph == Phase.PARKED},
                "owner_obligations": {n: self.store.issue(n).human_tasks for n, ph in phases.items()
                                      if ph == Phase.DELIVERED}}

    def _post_run_summary(self) -> None:
        states = {n: self.store.issue(n) for n in self.plan.work}
        self._upsert_comment(self.plan.root, report.RUN_MARKER, report.render_run_summary(self.plan.root, states))


def restart(st: IssueState, feedback: list[str] | None = None, owner_edit: bool = False) -> None:
    """Design again, keeping the branch and the work already written (ADR 0011, decision 3).
    The previous design's check files are remembered so the next one can retire those it drops.
    A new design gets its own implement attempts and fix rounds; the recovery budgets (redesigns,
    check amendments, CI fixes, fix-forwards, merge refusals) survive restarts and the engine's
    own redesigns, and only an owner's edit, which is new evidence, resets them."""
    if st.design:
        st.superseded = sorted(set(st.superseded) | set(st.design.get("check_files", [])))
    st.design, st.checks, st.locked, st.expected_tests = None, [], {}, {}
    st.attempts = st.fix_rounds = 0
    st.feedback, st.blockers, st.evidence, st.amend, st.amend_file = list(feedback or []), [], [], [], None
    st.verified_sha = st.reviewed_sha = None
    st.reason = st.park_kind = st.resume_phase = None
    if owner_edit:
        st.redesigns = st.check_amendments = st.ci_fixes = st.fix_forwards = st.merge_refusals = 0


def edited_feedback(st: IssueState) -> list[str]:
    """What a design for an edited issue starts from: the previous decisions, to keep where they
    still fit (ADR 0011, decision 3). Read before `restart` clears the design."""
    notes = ["The owner edited the issue; design for the edited version."]
    log = (st.design or {}).get("decision_log") or [{"id": k, "choice": v} for k, v in ((st.design or {}).get("decisions") or {}).items()]
    if log:
        notes.append("Decisions of the previous design, to keep where they still fit: " + json.dumps(log)[:1500])
    return notes


def design_paths(files: list[str], check_files: list[str], parsed: list[str]) -> list[str]:
    """The design's file list is authoritative: the judge read the issue, while the parser only
    pattern-matched it (a bare `README.md` may mean the session's or the repo's)."""
    chosen = sorted(set(files) | set(check_files))
    return chosen or list(parsed)


def repair_design(design: Design, spec) -> tuple[Design, list[str]]:
    """Make a design usable without a person. Every ledger item keeps a check: one the judge
    left out, or a command check without a command, is proven by the reviewers instead, and
    the substitution is published as a decision. Returns the design and what is still unusable."""
    ledger = {item.id: item for item in spec.ledger}
    checks, log = [], list(design.decision_log)
    for c in design.checks:
        if c.kind not in ("command", "artifact", "manual") or (c.kind == "command" and not c.command):
            log.append({"id": f"engine-{c.criterion}", "choice": f"{c.criterion} is proven by reviewer judgement",
                        "rationale": "the design gave it no usable command"})
            c = replace(c, kind="artifact", command=None)
        checks.append(c)
    for item_id, item in ledger.items():
        if item_id not in {c.criterion for c in checks}:
            log.append({"id": f"engine-{item_id}", "choice": f"{item_id} is proven by reviewer judgement",
                        "rationale": "the design gave it no check"})
            checks.append(CheckSpec(criterion=item_id, kind="artifact", description=item.text))
    problems = [] if design.files else ["the design names no files to change"]
    return replace(design, checks=checks, decision_log=log), problems


def environment_problem(evidence: list[dict]) -> str | None:
    """The first check output showing the host, not the change, is at fault."""
    for ev in evidence:
        m = ENVIRONMENT_FAILURE.search(ev.get("output_tail") or "")
        if m:
            line = next((l for l in (ev.get("output_tail") or "").splitlines() if m.group(0) in l), m.group(0))
            return f"{ev.get('criterion')}: {line.strip()[:300]}"
    return None


def fault_fingerprint(exc: BaseException) -> str:
    """Stable across runs: the exception type and the innermost engine frame, not the message."""
    frames = [f for f in traceback.extract_tb(exc.__traceback__) if "implement_loop" in (f.filename or "")]
    where = f"{Path(frames[-1].filename).name}:{frames[-1].name}" if frames else "unknown"
    return hashlib.sha256(f"{type(exc).__name__}@{where}".encode()).hexdigest()[:10]


def engine_frames(exc: BaseException) -> str:
    """Where in the engine it failed, without messages or values: safe to publish."""
    frames = [f for f in traceback.extract_tb(exc.__traceback__) if "implement_loop" in (f.filename or "")]
    return "\n".join(f"{Path(f.filename).name}:{f.lineno} in {f.name}" for f in frames) or "(no engine frame)"


def redact(text: str, repo_root: Path) -> str:
    """Local paths out of the local journal's copies too; public reports carry no message at all."""
    home = str(Path.home())
    return text.replace(str(repo_root), "<repo>").replace(home, "~")
