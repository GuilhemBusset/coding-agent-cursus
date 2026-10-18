"""Data shapes shared by the engine modules."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum


class Phase(str, Enum):
    PENDING = "pending"          # waiting for prerequisites, or not started
    PLAN = "plan"                # the builder plans, the engine lints, the examiner triages
    PLANNED = "planned"          # planned; waiting for a writer slot (file ownership)
    BUILD = "build"              # the builder writes code and its tests in its worktree
    VERIFY = "verify"            # engine runs the trusted verifier
    EXAMINE = "examine"          # the other vendor examines, probes and certifies the exact head
    LAND = "land"                # push, PR, required check on the exact head, merge
    MERGED = "merged"            # merged; post-merge verification pending
    DELIVERED = "delivered"      # merged; every agent item proven; typed obligations remain
    DONE = "done"                # every ledger item has evidence; issue closed
    WAITING = "waiting"          # not terminal: resumes by itself once its condition clears
    FAILED = "failed"            # explicit non-delivery: a ceiling ran out or state cannot be trusted


# State written by earlier engines (ADR 0008, ADR 0011) is read with the new names; parked
# issues are migrated by the engine at the start of a run (`Engine._migrate`).
LEGACY_PHASES = {"accepted": "delivered", "needs_human": "parked", "design": "plan", "designed": "planned",
                 "checks": "build", "implement": "build", "review": "examine"}
LEGACY_PARKED = "parked"
TERMINAL = frozenset({Phase.DONE, Phase.DELIVERED, Phase.FAILED})
SATISFIES_DEPENDENTS = frozenset({Phase.DELIVERED, Phase.DONE})
WRITING_PHASES = frozenset({Phase.BUILD, Phase.VERIFY, Phase.EXAMINE, Phase.LAND})

# What an issue in WAITING waits for. In-run conditions are polled by the running engine;
# the others end the run for that issue and are resumed by the supervisor (`cli supervise`).
WAIT_MERGE_QUEUE = "merge_queue"     # another run is landing: in-run poll
WAIT_CLAIM = "claim"                 # another run owns this issue: in-run poll
WAIT_PREREQUISITE = "prerequisite"   # a prerequisite in this run is not delivered yet: scheduler
WAIT_CI = "ci"                       # the required check gave no verdict in time
WAIT_OUTAGE = "outage"               # a vendor CLI could not reach its service
WAIT_GITHUB = "github"               # GitHub kept failing after retries
WAIT_ENVIRONMENT = "environment"     # the host cannot run the checks; the doctor's recipes may fix it
WAIT_ENGINE = "engine"               # an engine fault was filed; resumes on a new engine version
WAIT_RUN_CEILING = "run_ceiling"     # the run's call ceiling stopped new calls
IN_RUN_WAITS = frozenset({WAIT_MERGE_QUEUE, WAIT_CLAIM})

# Proof kinds a plan gives each ledger item (ADR 0012).
PROOF_KINDS = ("test", "command", "review", "owner", "deferred")
AGENT_PROOFS = frozenset({"test", "command", "review"})


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
    """A command that proves one ledger item. Written by the builder (or a probe by the
    examiner), executed by the engine's trusted verifier."""
    criterion: str                  # ledger item id
    kind: str = "command"           # "command" | "artifact" | "manual" (the last two: legacy designs)
    command: str | None = None
    cwd: str = "."
    description: str = ""
    timeout_s: int | None = None
    author: str = "builder"         # "builder" | "examiner" (an adopted probe)


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
    verifier: str = "implement-loop/1.0"


@dataclass
class Finding:
    """One problem the examiner reports. It blocks only when the engine can tie it to the
    issue (a quote of the item, or a named safety invariant) and, unless it is a verdict on a
    review item, when its reproduction fails on the exact head (ADR 0012)."""
    id: str
    title: str
    item: str | None = None          # the ledger item it says is violated
    quote: str | None = None         # >= 3 words of that item's text
    invariant: str | None = None     # or a safety invariant from loop.toml
    observed: str = ""               # the behavioural witness: what happens
    expected: str = ""               # and what the item (or invariant) requires
    reproduction: str | None = None  # a command that fails while the finding holds
    cwd: str = "."
    probe: str | None = None         # or the probe file whose test fails while it holds
    file: str | None = None
    line: int | None = None
    severity: int = 2                # 0..3, informative only: never a gate
    # engine bookkeeping
    status: str = "new"              # new | open | closed | follow_up | advisory | rejected
    blocking: bool = False
    reason: str = ""                 # why it was classified as it was
    round: int = 0


@dataclass
class IssueState:
    number: int
    phase: Phase = Phase.PENDING
    branch: str | None = None
    worktree: str | None = None
    base_sha: str | None = None
    head_sha: str | None = None
    verified_sha: str | None = None
    examined_sha: str | None = None      # the last head the examiner saw
    certified_sha: str | None = None     # the head the examiner certified: the only one that may land
    pr: int | None = None
    body_hash: str | None = None
    round: int = 1                       # work rounds: a new one after a post-merge edit or a fix-forward
    # The plan (ADR 0012): per-item readings and proof kinds, zones, decisions.
    plan: dict | None = None
    commands: list[dict] = field(default_factory=list)       # CheckSpec per item (builder's, then probes)
    tests: list[str] = field(default_factory=list)           # the builder's test files
    probes: list[str] = field(default_factory=list)          # adopted probe files (the examiner's)
    locked: dict[str, str] = field(default_factory=dict)     # path -> digest, from the first examination
    manifest: dict[str, list[str]] = field(default_factory=dict)  # criterion -> test ids that must run and pass
    dispositions: dict[str, str] = field(default_factory=dict)    # unselected test id -> owner-run | excluded: why
    grants: list[dict] = field(default_factory=list)         # {path, source, protected}
    findings: list[dict] = field(default_factory=list)       # Finding records, the examiner's memory
    verdicts: dict[str, dict] = field(default_factory=dict)  # item -> {verdict, quote, head, note}
    requests: list[dict] = field(default_factory=list)       # typed builder requests and their outcomes
    obligations: list[dict] = field(default_factory=list)    # {item, kind: capability|deferred, detail}
    decisions: list[dict] = field(default_factory=list)      # published in the PR's Decisions section
    feedback: list[str] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    last_ran: dict[str, list[str]] = field(default_factory=dict)  # criterion -> passed test ids, last verify
    reverted: list[str] = field(default_factory=list)        # locked files the builder edited, reverted
    dropped: list[str] = field(default_factory=list)         # builder commands not kept, and why
    conflict_paths: list[str] = field(default_factory=list)
    conflict_pending: bool = False
    # Budgets (ADR 0012): persistent across runs; only an owner's edit resets them.
    calls: int = 0                       # answered agent calls charged to this issue
    infra: int = 0                       # attempts that timed out or crashed
    ceiling_bonus: int = 0               # a fresh ceiling granted once by a new engine version
    unproductive: int = 0                # consecutive rounds that changed nothing
    replans: int = 0
    signature: str = ""                  # what failed last round, for the progress rule
    fix_forwards: int = 0
    reverts: int = 0
    merge_refusals: int = 0
    ci_rerun_heads: list[str] = field(default_factory=list)
    followup: int | None = None          # the follow-up issue filed for non-blocking findings
    extra_deps: list[int] = field(default_factory=list)      # prerequisites found mid-run, kept across runs
    exam_feedback: list[str] = field(default_factory=list)   # what the next examination must supply
    exam_retries: int = 0                # examinations re-asked for missing verdicts or probes
    # Waiting and failure.
    wait: dict | None = None             # {kind, resume, detail, since, vendor?, version?, env?}
    fail: dict | None = None             # {cause, detail, version, resumed}
    human_tasks: list[str] = field(default_factory=list)     # owner obligations, as text (reports)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["phase"] = self.phase.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "IssueState":
        d = dict(d)
        phase = d.get("phase", "pending")
        if phase == "needs_human":
            d.setdefault("park_kind", "exhausted")
        phase = LEGACY_PHASES.get(phase, phase)
        legacy = {}
        if phase == LEGACY_PARKED:
            legacy = {"park_kind": d.get("park_kind"), "resume_phase": d.get("resume_phase"),
                      "reason": d.get("reason"), "parked_version": d.get("parked_version")}
            phase = Phase.PENDING.value
        if d.get("design") and not d.get("plan"):
            legacy["design"] = d["design"]
            legacy["locked"] = d.get("locked") or {}
        d["phase"] = Phase(LEGACY_PHASES.get(phase, phase))
        known = {f for f in cls.__dataclass_fields__}
        st = cls(**{k: v for k, v in d.items() if k in known})
        if legacy:
            st.wait = {"kind": "legacy", **legacy}
        return st
