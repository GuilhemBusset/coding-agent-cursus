"""What the engine asks of agents, and a scripted fake for tests.

Real implementations (headless `claude -p` and `codex exec`, one fresh process per call) come
in the next step. Every call names the vendor that must answer, so the engine, not the agent,
decides who proposes, who writes the checks, who implements and who reviews.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .model import CheckSpec, Finding, Issue, IssueSpec


@dataclass
class DesignRequest:
    issue: Issue
    spec: IssueSpec
    context: str
    lens: str = ""
    feedback: list[str] = field(default_factory=list)


@dataclass
class Proposal:
    author: str                       # anonymized label shown to other agents, e.g. "A"
    decisions: dict[str, str]         # decision id -> choice
    checks: list[CheckSpec]           # how each ledger item will be proven
    files: list[str]                  # paths the implementation will touch
    check_files: list[str]            # where the acceptance checks will live
    open_questions: list[str] = field(default_factory=list)


@dataclass
class Objection:
    text: str
    blocking: bool
    changes_criterion: bool = False   # the dispute would change what the issue asks for


@dataclass
class Design:
    decisions: dict[str, str]
    checks: list[CheckSpec]
    files: list[str]
    check_files: list[str]
    notes: str = ""
    criterion_disputes: list[str] = field(default_factory=list)


@dataclass
class ImplementResult:
    status: str                       # "done" | "impossible"
    note: str = ""


@dataclass
class ReviewResult:
    findings: list[Finding]
    coverage: dict[str, bool] = field(default_factory=dict)   # criterion id -> judged met


class Agents(Protocol):
    operator: str
    other: str

    def explore(self, vendor: str, question: str, briefing: str) -> str: ...
    def propose(self, vendor: str, req: DesignRequest, author: str) -> Proposal: ...
    def audit(self, vendor: str, req: DesignRequest, proposals: list[Proposal]) -> list[Objection]: ...
    def critique(self, vendor: str, req: DesignRequest, proposals: list[Proposal]) -> list[Objection]: ...
    def judge(self, vendor: str, req: DesignRequest, proposals: list[Proposal], objections: list[Objection]) -> Design: ...
    def write_checks(self, vendor: str, req: DesignRequest, design: Design, worktree: Path) -> None: ...
    def implement(self, vendor: str, req: DesignRequest, design: Design, worktree: Path, feedback: list[str]) -> ImplementResult: ...
    def review(self, vendor: str, role: str, req: DesignRequest, design: Design, worktree: Path,
               base_sha: str, head_sha: str, evidence: list[dict]) -> ReviewResult | None: ...
    def verify_finding(self, vendor: str, req: DesignRequest, worktree: Path, finding: Finding) -> bool: ...


# --------------------------------------------------------------------------- fake

@dataclass
class Script:
    """How the fake agents behave for one issue."""
    files: dict[str, str]                         # implementation: path -> correct content
    check_file: str = ""                          # defaults to checks/issue_<n>.sh
    wrong_attempts: int = 0                       # first N implementations write wrong content
    impossible: bool = False
    tamper: bool = False                          # first implementation also edits the locked check
    review_defects: int = 0                       # cross reviewer reports a reproducible defect N times
    reviewer_fails: int = 0                       # cross reviewer returns nothing N times
    disagree: bool = False                        # the two proposals differ
    criterion_dispute: bool = False
    manual_items: tuple[str, ...] = ()            # ledger ids that only a person can prove
    artifact_items: tuple[str, ...] = ()          # ledger ids proven by reviewer judgement


class FakeAgents:
    """Deterministic agents. The checks are shell scripts comparing file contents, so the
    engine's real git, verify and landing code runs end to end without any model."""

    def __init__(self, scripts: dict[int, Script], operator: str = "claude", other: str = "codex"):
        self.scripts = scripts
        self.operator, self.other = operator, other
        self.calls: list[tuple] = []
        self._implemented: dict[int, int] = {}
        self._reviewed: dict[int, int] = {}
        self._review_failures: dict[int, int] = {}

    def _s(self, req: DesignRequest) -> Script:
        return self.scripts[req.issue.number]

    def _check_file(self, n: int) -> str:
        return self.scripts[n].check_file or f"checks/issue_{n}.sh"

    def explore(self, vendor, question, briefing):
        self.calls.append(("explore", vendor, question))
        return f"[{vendor}] {question}: nothing surprising."

    def propose(self, vendor, req, author):
        n = req.issue.number
        s = self._s(req)
        self.calls.append(("propose", vendor, n))
        checks = []
        for item in req.spec.ledger:
            if item.id in s.manual_items:
                checks.append(CheckSpec(criterion=item.id, kind="manual", description=item.text))
            elif item.id in s.artifact_items:
                checks.append(CheckSpec(criterion=item.id, kind="artifact", description=item.text))
            else:
                checks.append(CheckSpec(criterion=item.id, kind="command", command=f"bash {self._check_file(n)}"))
        choice = "variant-b" if (s.disagree and author == "B") else "variant-a"
        return Proposal(author=author, decisions={"approach": choice}, checks=checks,
                        files=sorted(s.files), check_files=[self._check_file(n)])

    def audit(self, vendor, req, proposals):
        self.calls.append(("audit", vendor, req.issue.number))
        s = self._s(req)
        if s.criterion_dispute:
            return [Objection("the criterion itself is ambiguous", blocking=True, changes_criterion=True)]
        return []

    def critique(self, vendor, req, proposals):
        self.calls.append(("critique", vendor, req.issue.number))
        return [Objection("variant-b ignores the size limit", blocking=False)]

    def judge(self, vendor, req, proposals, objections):
        self.calls.append(("judge", vendor, req.issue.number))
        p = proposals[0]
        disputes = [o.text for o in objections if o.changes_criterion]
        return Design(decisions=dict(p.decisions), checks=p.checks, files=p.files, check_files=p.check_files,
                      notes="fake design", criterion_disputes=disputes)

    def write_checks(self, vendor, req, design, worktree):
        n = req.issue.number
        s = self._s(req)
        self.calls.append(("write_checks", vendor, n))
        lines = ["#!/usr/bin/env bash", "set -euo pipefail", f"# acceptance check for issue {n}"]
        for path, content in sorted(s.files.items()):
            lines.append(f'test "$(cat {path})" = "{content}"')
        target = worktree / self._check_file(n)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(lines) + "\n")

    def implement(self, vendor, req, design, worktree, feedback):
        n = req.issue.number
        s = self._s(req)
        k = self._implemented.get(n, 0)
        self._implemented[n] = k + 1
        self.calls.append(("implement", vendor, n, tuple(feedback)))
        if s.impossible:
            return ImplementResult("impossible", "the criteria contradict each other")
        for path, content in s.files.items():
            target = worktree / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text((content if k >= s.wrong_attempts else "wrong") + "\n")
        if s.tamper and k == 0:
            (worktree / self._check_file(n)).write_text("#!/usr/bin/env bash\nexit 0\n")
        if s.tamper and k == 1:
            # second attempt restores the check, as an honest implementer would after feedback
            self.write_checks(vendor, req, design, worktree)
        return ImplementResult("done")

    def review(self, vendor, role, req, design, worktree, base_sha, head_sha, evidence):
        n = req.issue.number
        s = self._s(req)
        self.calls.append(("review", vendor, role, n))
        if role == "cross":
            fails = self._review_failures.get(n, 0)
            if fails < s.reviewer_fails:
                self._review_failures[n] = fails + 1
                return None
            k = self._reviewed.get(n, 0)
            self._reviewed[n] = k + 1
            if k < s.review_defects:
                return ReviewResult([Finding(id=f"F{n}-{k}", reviewer=role, priority=1, confidence=0.9,
                                             title="edge case breaks the criterion", file=sorted(s.files)[0], line=1,
                                             reproduction="run the check with an empty input",
                                             criterion="A1", claims_acceptance_failure=True)])
        coverage = {i: True for i in s.artifact_items}
        advisory = [Finding(id=f"N{n}", reviewer=role, priority=3, confidence=0.4, title="naming nit")]
        return ReviewResult(advisory, coverage)

    def verify_finding(self, vendor, req, worktree, finding):
        self.calls.append(("verify_finding", vendor, req.issue.number, finding.id))
        return finding.claims_acceptance_failure
