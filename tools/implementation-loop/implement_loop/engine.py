"""The per-issue state machine and the scheduling loop.

Each issue moves through: pending -> design -> designed -> checks -> implement -> verify ->
review -> land -> merged -> accepted -> done. The only ways back are a failed verification
(to implement, at most `implement_attempts` times) and a reproduced review defect (to
implement, at most `fix_rounds` times). A cap, an impossible task, a missing review or a
dispute over a criterion ends the issue in `needs_human`; the run carries on around it.

Steps run on a thread pool, so one issue can be in review while another implements and a
third designs. Landing is serialized through a repo-wide merge-queue claim.
"""

from __future__ import annotations

import time
import traceback
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from . import graph, issue_parser, report, scheduler, verify
from .agents import Agents, Design, DesignRequest, Objection, Proposal
from .config import Config
from .github import GitHub, GitHubError
from .graph import Plan
from .model import CheckSpec, Finding, Issue, IssueState, Phase, SATISFIES_DEPENDENTS, TERMINAL, WRITING_PHASES
from .state import RepoClaims, RunStore
from .workspace import GitError, Workspace

LABELS = {
    "loop:design": ("C5DEF5", "implement loop: designing"),
    "loop:building": ("FBCA04", "implement loop: checks, implementation or verification"),
    "loop:review": ("D4C5F9", "implement loop: in review"),
    "loop:landing": ("0E8A16", "implement loop: PR open, merging"),
    "loop:merged": ("BFDADC", "implement loop: merged, verifying on main"),
    "loop:awaiting-human": ("F9D0C4", "implement loop: automated evidence done; a person must provide the rest"),
    "loop:needs-human": ("B60205", "implement loop: stopped; needs a decision or a fix"),
}
PHASE_LABEL = {
    Phase.DESIGN: "loop:design", Phase.DESIGNED: "loop:design",
    Phase.CHECKS: "loop:building", Phase.IMPLEMENT: "loop:building", Phase.VERIFY: "loop:building",
    Phase.REVIEW: "loop:review", Phase.LAND: "loop:landing", Phase.MERGED: "loop:merged",
    Phase.ACCEPTED: "loop:awaiting-human", Phase.NEEDS_HUMAN: "loop:needs-human",
}
EXPLORE_QUESTIONS = (
    "The issue graph and acceptance criteria: what must be true when this run is done?",
    "Existing material and conventions these issues must follow (ADRs, AGENTS.md, guides).",
    "Build, check and CI tooling: how is work validated in this repo today?",
    "External references the issues cite: what do they establish that the work depends on?",
)
MERGE_QUEUE = "merge-queue"


class Engine:
    def __init__(self, plan: Plan, store: RunStore, gh: GitHub, ws: Workspace, agents: Agents, cfg: Config,
                 repo_root: Path, log: Callable[[str], None] = print, sleep: Callable[[float], None] = time.sleep):
        self.plan, self.store, self.gh, self.ws, self.agents, self.cfg = plan, store, gh, ws, agents, cfg
        self.repo_root = repo_root
        self.log, self.sleep = log, sleep
        self.caps = cfg.caps
        self.claims = RepoClaims(repo_root)
        self.owner = f"run-{plan.root}"
        self.op, self.other = agents.operator, agents.other

    # ------------------------------------------------------------------ public
    def run(self) -> dict:
        with self.store.lock():
            self.store.event("run_started", root=self.plan.root, mode=self.plan.mode, work=self.plan.work,
                             operator=self.op, other=self.other)
            self._ensure_labels()
            self._reconcile()
            self._context()
            stopped = self._loop()
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
                if st.phase in (Phase.MERGED, Phase.ACCEPTED):
                    st.phase, st.reason = Phase.NEEDS_HUMAN, CHANGED_AFTER_MERGE
                    self.store.event("requirements_changed_after_merge", issue=n)
                elif st.phase != Phase.DONE:
                    self.store.event("requirements_changed", issue=n, previous_phase=st.phase.value)
                    invalidate(st)
            st.body_hash = spec.body_hash
            st.branch = st.branch or spec.branch or f"loop/issue-{n}"
            if st.design:
                spec.declared_paths = design_paths(st.design.get("files", []), st.design.get("check_files", []), spec.declared_paths)
            self.store.put(st)

    def _context(self) -> None:
        if self.store.state.get("context"):
            return
        briefing = report.render_plan(self.plan)
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
                        if exc is not None:
                            detail = "".join(traceback.format_exception(exc))[-1500:]
                            self.store.event("step_crashed", issue=n, error=repr(exc), traceback=detail)
                            self._needs_human(n, f"engine error: {exc!r}")
                if self.store.stop_requested():
                    if not stopped:
                        self.store.event("stop_requested")
                        stopped = True
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
            self._sync(n)
        return st

    def _needs_human(self, n: int, reason: str) -> None:
        self.log(f"#{n} needs a human: {reason}")
        self._set_phase(n, Phase.NEEDS_HUMAN, reason=reason)

    def _safe(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (GitHubError, OSError) as e:
            self.store.event("github_call_failed", call=getattr(fn, "__name__", str(fn)), error=str(e)[:300])
            return None

    def _sync(self, n: int) -> None:
        st = self.store.issue(n)
        wanted = PHASE_LABEL.get(st.phase)
        for label in LABELS:
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

    def _uncommitted(self, wt: Path) -> list[str]:
        return [line[3:] for line in self.ws.git("status", "--porcelain", "--untracked-files=all", cwd=wt).splitlines()]

    # ------------------------------------------------------------------ steps
    def _step_design(self, n: int) -> None:
        st = self.store.issue(n)
        issue, spec = self.plan.issues[n], self.plan.specs[n]
        req = self._req(n, feedback=st.feedback)
        st.design_rounds += 1
        if issue.size == "S":
            proposals = [self.agents.propose(self.op, self._req(n, "smallest correct implementation"), "A")]
        else:
            proposals = [self.agents.propose(self.op, self._req(n, "smallest correct implementation"), "A"),
                         self.agents.propose(self.other, self._req(n, "verification first: how each criterion is proven"), "B")]
        objections: list[Objection] = self.agents.audit(self.other, req, proposals)
        diverged = len({tuple(sorted(p.decisions.items())) for p in proposals}) > 1
        if (diverged or any(o.blocking for o in objections)) and st.design_rounds < self.caps.design_rounds:
            st.design_rounds += 1
            objections += self.agents.critique(self.op, req, proposals)
        design = self.agents.judge(self.op, req, proposals, objections)
        problems = validate_design(design, spec)
        if problems and st.design_rounds < self.caps.design_rounds:
            st.design_rounds += 1
            design = self.agents.judge(self.op, self._req(n, feedback=problems), proposals, objections)
            problems = validate_design(design, spec)
        self.store.event("design", issue=n, rounds=st.design_rounds, diverged=diverged,
                         blocking=[o.text for o in objections if o.blocking], problems=problems)
        st.design = asdict(design)
        st.checks = [asdict(c) for c in design.checks]
        self.store.put(st)
        if design.criterion_disputes:
            return self._needs_human(n, "a design dispute would change an acceptance criterion: " + "; ".join(design.criterion_disputes))
        if problems:
            return self._needs_human(n, "the design does not prove every criterion: " + "; ".join(problems))
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
        base = self.ws.git("merge-base", "HEAD", self.ws.base_ref(), cwd=wt)
        self.agents.write_checks(self.other, self._req(n), design, wt)
        outside = [f for f in self._uncommitted(wt) if not any(scheduler.overlaps(f, c) for c in design.check_files)]
        if outside:
            for f in outside:
                self.ws.git("checkout", "--", f, cwd=wt, check=False)
                self.ws.git("clean", "-fdq", "--", f, cwd=wt, check=False)
            self.store.event("check_author_out_of_lane", issue=n, discarded=outside)
        sha = self.ws.commit_all(wt, f"Add acceptance checks for #{n}", "acceptance-checks", n)
        needs_commands = any(c.kind == "command" for c in design.checks)
        if sha is None and needs_commands and not st.checks_sha:
            return self._needs_human(n, "no acceptance checks were written")
        cwds = sorted({c.cwd for c in design.checks if c.kind == "command"})
        locked = verify.lock(wt, design.check_files, cwds)
        expected = verify.expected_tests(wt, design.check_files)
        self.store.event("checks_locked", issue=n, sha=sha, locked=sorted(locked), expected_tests=expected)
        self._set_phase(n, Phase.IMPLEMENT, worktree=str(wt), base_sha=base, checks_sha=sha or st.checks_sha,
                        locked=locked, expected_tests={"*": expected})

    def _step_implement(self, n: int) -> None:
        st = self.store.issue(n)
        wt = Path(st.worktree)
        result = self.agents.implement(self.op, self._req(n), self._design(st), wt, st.feedback)
        if result.status == "impossible":
            return self._needs_human(n, f"the implementer reports the task cannot be done as specified: {result.note}")
        sha = self.ws.commit_all(wt, f"Implement #{n} (attempt {st.attempts + 1})", "implementation", n)
        self.store.event("implemented", issue=n, sha=sha, attempt=st.attempts + 1)
        self._set_phase(n, Phase.VERIFY, head_sha=self.ws.head(wt))

    def _step_verify(self, n: int) -> None:
        st = self.store.issue(n)
        wt = Path(st.worktree)
        design = self._design(st)
        head = self.ws.head(wt)
        ok, evidence, problems = verify.verify(wt, self._checks(st), head, self.store.issue_dir(n), st.locked,
                                               design.check_files, st.expected_tests.get("*", []),
                                               self.caps.check_timeout_s)
        st.base_sha = self._merge_base(wt)
        allowed = self.plan.specs[n].declared_paths
        undeclared = [f for f in self.ws.changed_files(wt, st.base_sha) if not any(scheduler.overlaps(f, a) for a in allowed)]
        if undeclared:
            ok = False
            problems.append(f"changed files outside the declared paths: {undeclared[:8]}")
        self.store.event("verified", issue=n, head=head, ok=ok, problems=problems)
        if ok:
            self._set_phase(n, Phase.REVIEW, evidence=evidence, head_sha=head, verified_sha=head,
                            base_sha=st.base_sha, feedback=[], blockers=[])
            return
        st.attempts += 1
        st.blockers.append(" | ".join(sorted(p.split(":")[0] + ":" + p.split(":", 1)[-1][:80] for p in problems)))
        st.evidence, st.head_sha = evidence, head
        self.store.put(st)
        limit = self.caps.same_blocker_limit
        if st.attempts >= self.caps.implement_attempts:
            return self._needs_human(n, f"verification failed {st.attempts} times: " + "; ".join(problems)[:600])
        if len(st.blockers) >= limit and len(set(st.blockers[-limit:])) == 1:
            return self._needs_human(n, "the same blocker repeated: " + st.blockers[-1][:600])
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
            return self._needs_human(n, f"review missing after a retry: {', '.join(missing)}")
        findings: list[Finding] = [f for _, r in results for f in r.findings]
        coverage = {}
        for role, r in results:
            if role == "cross":
                coverage.update(r.coverage)
        candidates = [f for f in findings if (f.file or f.reproduction) and
                      (f.claims_acceptance_failure or (f.priority <= 1 and f.confidence >= 0.8))]
        verified = [f for f in candidates if self.agents.verify_finding(self.op, req, wt, f)]
        advisory = [asdict(f) for f in findings if f not in verified]
        self.store.event("reviewed", issue=n, head=head, findings=len(findings), verified=[f.id for f in verified])
        if verified:
            st.fix_rounds += 1
            self.store.put(st)
            if st.fix_rounds > self.caps.fix_rounds:
                return self._needs_human(n, "verified defects remain after the fix rounds: " + "; ".join(f.title for f in verified))
            feedback = [f"[{f.reviewer} P{f.priority}] {f.title} ({f.file}:{f.line}). Reproduce: {f.reproduction}" for f in verified]
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
                return self._needs_human(n, f"reviewers judge these criteria unmet: {unmet}")
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
                # merged before a crash, but the merge was never recorded
                merged_head = (existing.get("head") or {}).get("sha")
                if merged_head and merged_head != st.reviewed_sha:
                    return self._needs_human(n, f"PR #{existing['number']} was merged at {merged_head[:7]}, not at the reviewed {str(st.reviewed_sha)[:7]}")
                self.store.event("merge_found_on_resume", issue=n, pr=existing["number"])
                return self._set_phase(n, Phase.MERGED, pr=existing["number"])
            if not self._requirements_current(n):
                self.store.event("requirements_changed", issue=n, previous_phase=Phase.LAND.value)
                st = self.store.issue(n)
                invalidate(st)
                st.body_hash = self.plan.specs[n].body_hash
                self.store.put(st)
                return self._set_phase(n, Phase.PENDING)
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
            conclusion = self._wait_required(head)
            if conclusion != "success":
                return self._needs_human(n, f"the required check is '{conclusion}' on {head[:7]}")
            try:
                self.gh.merge_pr(st.pr, head)
            except GitHubError as e:
                self.store.event("merge_refused", issue=n, error=str(e)[:300])
                return self._set_phase(n, Phase.VERIFY, rereview=True)
            self.store.event("merged", issue=n, pr=st.pr, head=head)
            self._set_phase(n, Phase.MERGED)
        finally:
            self.claims.release(MERGE_QUEUE, self.owner)

    def _wait_required(self, sha: str) -> str:
        waited = 0
        while True:
            state = self.gh.required_check(sha, self.cfg.required_check)
            if state not in (None, "pending"):
                return state
            if waited >= self.caps.ci_timeout_s:
                return state or "missing"
            self.sleep(self.caps.ci_poll_s)
            waited += self.caps.ci_poll_s

    def _step_accept(self, n: int) -> None:
        st = self.store.issue(n)
        if not self._requirements_current(n):
            self.store.event("requirements_changed_after_merge", issue=n)
            return self._needs_human(n, CHANGED_AFTER_MERGE)
        coord = self.ws.coord()
        design = self._design(st)
        head = self.ws.head(coord)
        ok, evidence, problems = verify.verify(coord, self._checks(st), head, self.store.issue_dir(n), st.locked,
                                               design.check_files, st.expected_tests.get("*", []),
                                               self.caps.check_timeout_s)
        self.store.event("post_merge_verify", issue=n, head=head, ok=ok, problems=problems)
        if not ok:
            return self._needs_human(n, "post-merge verification failed on main: " + "; ".join(problems)[:600])
        artifact = [e for e in st.evidence if e["kind"] == "artifact" and e["passed"]]
        evidence_comment = self._upsert_comment(st.pr, report.EVIDENCE_MARKER, report.render_evidence(n, evidence, head, artifact)) if st.pr else None
        link = (evidence_comment or {}).get("html_url", "")
        proven = {e["criterion"] for e in evidence if e["passed"]} | {e["criterion"] for e in artifact}
        manual = [c for c in self._checks(st) if c.kind == "manual"]
        issue = self.gh.get_issue(n)
        if issue_parser.body_hash(issue.get("body") or "") != st.body_hash:
            # edited while post-merge verification ran: this body is not what the evidence proves
            self.store.event("requirements_changed_after_merge", issue=n)
            return self._needs_human(n, CHANGED_AFTER_MERGE)
        unproven = [i.id for i in issue_parser.ledger(issue.get("body") or "")
                    if i.id not in proven and i.id not in {c.criterion for c in manual}]
        if unproven:
            return self._needs_human(n, f"ledger items without evidence on main: {unproven}")
        ticked = issue_parser.tick(issue.get("body") or "", {cid: link for cid in proven})
        if ticked != (issue.get("body") or ""):
            self._safe(self.gh.edit_issue, n, body=ticked)
        st = self.store.issue(n)
        st.evidence = evidence + artifact
        st.human_tasks = [f"{c.criterion}: {c.description}" for c in manual]
        self.store.put(st)
        if st.worktree:
            self.ws.remove(Path(st.worktree))
        if manual:
            return self._set_phase(n, Phase.ACCEPTED)
        self._safe(self.gh.edit_issue, n, state="closed", state_reason="completed")
        self._set_phase(n, Phase.DONE)
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
        blocked = [n for n, ph in phases.items() if ph == Phase.PENDING]
        return {"stopped": stopped, "phases": counts,
                "needs_human": {n: self.store.issue(n).reason for n, ph in phases.items() if ph == Phase.NEEDS_HUMAN},
                "blocked_by_needs_human": blocked}

    def _post_run_summary(self) -> None:
        phases = self._phases()
        reasons = {n: self.store.issue(n).reason or "" for n in phases}
        tasks = {n: self.store.issue(n).human_tasks for n in phases if self.store.issue(n).human_tasks}
        self._upsert_comment(self.plan.root, report.RUN_MARKER, report.render_run_summary(self.plan.root, phases, reasons, tasks))


CHANGED_AFTER_MERGE = ("the issue's criteria changed after its work was merged; its evidence proves the old "
                       "criteria, so re-run the issue to design and prove the new ones")


def invalidate(st: IssueState) -> None:
    """Requirements changed: the design, checks and evidence no longer prove anything."""
    st.phase, st.design, st.checks, st.locked, st.expected_tests = Phase.PENDING, None, [], {}, {}
    st.attempts = st.fix_rounds = st.design_rounds = 0
    st.feedback, st.blockers, st.evidence, st.reason = [], [], [], None
    st.verified_sha = st.reviewed_sha = None


def design_paths(files: list[str], check_files: list[str], parsed: list[str]) -> list[str]:
    """The design's file list is authoritative: the judge read the issue, while the parser only
    pattern-matched it (a bare `README.md` may mean the session's or the repo's)."""
    chosen = sorted(set(files) | set(check_files))
    return chosen or list(parsed)


def validate_design(design: Design, spec) -> list[str]:
    """Every ledger item must map to a check; command checks need a command and a check file."""
    problems = []
    mapped = {c.criterion for c in design.checks}
    missing = [item.id for item in spec.ledger if item.id not in mapped]
    if missing:
        problems.append(f"ledger items without a check: {missing}")
    for c in design.checks:
        if c.kind not in ("command", "artifact", "manual"):
            problems.append(f"{c.criterion}: unknown check kind {c.kind!r}")
        if c.kind == "command" and not c.command:
            problems.append(f"{c.criterion}: command check without a command")
    if any(c.kind == "command" for c in design.checks) and not design.check_files:
        problems.append("command checks but no check files to lock")
    if not design.files:
        problems.append("the design names no files to change")
    return problems
