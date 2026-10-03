"""Data shapes shared by the engine modules."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum


class Phase(str, Enum):
    PENDING = "pending"          # waiting for prerequisites, or not started
    DESIGN = "design"            # proposals, audit, judge
    DESIGNED = "designed"        # design done; waiting for a writer slot (file ownership)
    CHECKS = "checks"           # other vendor writes acceptance checks; engine locks them
    IMPLEMENT = "implement"      # implementer edits its worktree
    VERIFY = "verify"            # engine runs the trusted verifier
    REVIEW = "review"            # reviewers in parallel, findings re-verified
    LAND = "land"                # push, PR, required check on the exact head, merge
    MERGED = "merged"            # merged; post-merge verification pending
    ACCEPTED = "accepted"        # automated ledger passes on main; human items may remain
    DONE = "done"                # every ledger item has evidence; issue closed
    NEEDS_HUMAN = "needs_human"  # a cap, an impossible task, or a dispute; the run goes on around it


TERMINAL = frozenset({Phase.DONE, Phase.NEEDS_HUMAN})
SATISFIES_DEPENDENTS = frozenset({Phase.ACCEPTED, Phase.DONE})
WRITING_PHASES = frozenset({Phase.CHECKS, Phase.IMPLEMENT, Phase.VERIFY, Phase.REVIEW, Phase.LAND})


@dataclass
class Issue:
    number: int
    title: str
    state: str
    body: str
    labels: list[str]
    db_id: int
    url: str = ""
    sub_issue_total: int = 0
    blocked_by_total: int = 0

    @property
    def is_open(self) -> bool:
        return self.state == "open"

    @property
    def size(self) -> str:
        for label in self.labels:
            if label.startswith("size:"):
                return label.split(":", 1)[1]
        return "M"

    @property
    def kind(self) -> str:
        for label in self.labels:
            if label.startswith("kind:"):
                return label.split(":", 1)[1]
        return ""

    @classmethod
    def from_api(cls, data: dict) -> "Issue":
        return cls(
            number=data["number"],
            title=data.get("title", ""),
            state=data.get("state", "open"),
            body=data.get("body") or "",
            labels=[l["name"] if isinstance(l, dict) else l for l in data.get("labels", [])],
            db_id=data.get("id", 0),
            url=data.get("html_url", ""),
            sub_issue_total=(data.get("sub_issues_summary") or {}).get("total", 0),
            blocked_by_total=(data.get("issue_dependencies_summary") or {}).get("total_blocked_by", 0),
        )


@dataclass
class LedgerItem:
    id: str          # D1.. for Deliverables, A1.. for Acceptance criteria
    section: str     # "deliverable" | "acceptance"
    text: str
    checked: bool


@dataclass
class IssueSpec:
    number: int
    ledger: list[LedgerItem]
    branch: str | None
    declared_paths: list[str]
    reference_paths: list[str]
    body_hash: str


@dataclass
class CheckSpec:
    """How one ledger item is proven. Written by the judge, executed by the engine."""
    criterion: str                  # ledger item id
    kind: str                       # "command" | "artifact" | "manual"
    command: str | None = None
    cwd: str = "."
    description: str = ""
    timeout_s: int | None = None


@dataclass
class Evidence:
    criterion: str
    kind: str
    command: str | None
    cwd: str
    head_sha: str
    exit_code: int | None
    passed: bool
    duration_s: float
    output_tail: str
    output_sha256: str
    tests: dict | None = None
    note: str = ""
    verifier: str = "implement-loop/0.1"


@dataclass
class Finding:
    id: str
    reviewer: str            # "cross" | "acceptance" | "visual"
    priority: int            # 0..3, Codex rubric
    confidence: float        # 0..1
    title: str
    file: str | None = None
    line: int | None = None
    reproduction: str | None = None
    criterion: str | None = None
    claims_acceptance_failure: bool = False


@dataclass
class IssueState:
    number: int
    phase: Phase = Phase.PENDING
    branch: str | None = None
    worktree: str | None = None
    base_sha: str | None = None
    checks_sha: str | None = None
    head_sha: str | None = None
    reviewed_sha: str | None = None
    pr: int | None = None
    attempts: int = 0
    design_rounds: int = 0
    fix_rounds: int = 0
    body_hash: str | None = None
    design: dict | None = None
    checks: list[dict] = field(default_factory=list)
    locked: dict[str, str] = field(default_factory=dict)
    expected_tests: dict[str, list[str]] = field(default_factory=dict)
    feedback: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    human_tasks: list[str] = field(default_factory=list)
    reason: str | None = None
    rereview: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        d["phase"] = self.phase.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "IssueState":
        d = dict(d)
        d["phase"] = Phase(d.get("phase", "pending"))
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})
