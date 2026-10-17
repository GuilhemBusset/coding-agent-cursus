"""What the engine asks of agents (ADR 0012), and a scripted fake for tests.

Two vendors, two keys. The **builder** (the operator's vendor) plans an issue, writes the code,
its tests, the registrations and the commands that prove each item. The **examiner** (the other
vendor) triages the plan, examines the result on the exact head, writes independent probes,
approves or refuses the builder's typed requests, and certifies the head that may land. A fresh
**arbiter** call from the examiner's vendor settles disputes. The engine (plain code) owns git,
the verifier, the gates and every merge.

Every call names the vendor that must answer. A `meter` (set by the engine) is told before and
after every attempt, so the engine can charge calls to the issue's ceilings.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .model import CheckSpec, Finding, Issue, IssueSpec


class AgentStopped(Exception):
    """The run was asked to stop while an agent was running."""


class AgentFailure(Exception):
    """An agent call failed after its retries. `kind` is "outage" (the vendor could not reach its
    service), "timeout" or "crash" (it ran and produced nothing usable)."""

    def __init__(self, message: str, kind: str = "crash", vendor: str = ""):
        super().__init__(message)
        self.kind, self.vendor = kind, vendor


class CeilingReached(Exception):
    """A call was refused before it started: the issue's (or the run's) call ceiling is spent."""

    def __init__(self, message: str, scope: str = "issue"):
        super().__init__(message)
        self.scope = scope


@dataclass
class IssueRequest:
    issue: Issue
    spec: IssueSpec
    context: str
    feedback: list[str] = field(default_factory=list)
    facts: dict = field(default_factory=dict)   # host lacks, invariants, branch notes, the plan's decisions


@dataclass
class ItemPlan:
    id: str
    reading: str
    quote: str
    proof: str                        # test | command | review | owner | deferred
    capability: str | None = None     # owner: the capability the host lacks
    agent_part: str | None = None     # owner: what agents still build and prove
    depends_on: int | None = None     # deferred: the open issue it needs
    depends_quote: str | None = None  # deferred: words of that issue's title or body


@dataclass
class PlanResult:
    items: list[ItemPlan]
    zones: list[str]
    decisions: list[dict]
    notes: str = ""


@dataclass
class Objection:
    kind: str                          # misreading | classification | dependency | scenario
    text: str
    item: str | None = None
    quote: str | None = None
    proof: str | None = None           # classification: the proof kind it argues for
    capability: str | None = None
    depends_on: int | None = None
    depends_quote: str | None = None


@dataclass
class Request:
    kind: str     # paths | protected_change | command_change | test_change | reclassify | depends | dispute
    detail: str
    paths: list[str] = field(default_factory=list)
    item: str | None = None
    finding: str | None = None
    capability: str | None = None
    depends_on: int | None = None
    depends_quote: str | None = None
    command: dict | None = None        # command_change: the new command for `item`
    id: str = ""


@dataclass
class BuildResult:
    status: str                        # done | blocked
    note: str = ""
    tests: list[str] = field(default_factory=list)
    commands: list[CheckSpec] = field(default_factory=list)
    dispositions: dict[str, str] = field(default_factory=dict)
    decisions: list[dict] = field(default_factory=list)
    requests: list[Request] = field(default_factory=list)


@dataclass
class Probe:
    file: str
    criterion: str
    command: str
    cwd: str = "."
    content: str = ""


@dataclass
class Decision:
    request: str
    approve: bool
    reason: str
    dispositions: dict[str, str] = field(default_factory=dict)


@dataclass
class ExamResult:
    verdicts: list[dict]               # {item, verdict: met | unmet, quote, note}
    findings: list[Finding]
    probes: list[Probe]
    decisions: list[Decision]
    certify: bool
    summary: str = ""


@dataclass
class Ruling:
    upheld: bool                       # the disputed claim stands (the finding blocks, the refusal holds)
    reason: str


class Meter(Protocol):
    def before(self, issue: int | None, role: str, vendor: str) -> None: ...
    def after(self, issue: int | None, role: str, vendor: str, outcome: str) -> None: ...


class Agents(Protocol):
    operator: str
    other: str
    meter: Meter | None

    def explore(self, vendor: str, question: str, briefing: str) -> str: ...
    def plan(self, vendor: str, req: IssueRequest, worktree: Path | None) -> PlanResult: ...
    def triage(self, vendor: str, req: IssueRequest, plan: dict) -> list[Objection]: ...
    def build(self, vendor: str, req: IssueRequest, plan: dict, worktree: Path, feedback: list[str]) -> BuildResult: ...
    def resolve_locked(self, vendor: str, req: IssueRequest, worktree: Path, files: list[str], feedback: list[str]) -> None:
        """Resolve main's conflict markers in locked tests (never the builder's vendor)."""
    def examine(self, vendor: str, req: IssueRequest, plan: dict, worktree: Path, base_sha: str, head_sha: str,
                evidence: list[dict], memory: list[dict], requests: list[dict], since: str | None) -> ExamResult: ...
    def decide(self, vendor: str, req: IssueRequest, worktree: Path, requests: list[dict]) -> list[Decision]: ...
    def arbitrate(self, vendor: str, req: IssueRequest, dispute: dict) -> Ruling: ...


# --------------------------------------------------------------------------- fake

@dataclass
class Script:
    """How the fake agents behave for one issue."""
    files: dict[str, str]                         # implementation: path -> correct content
    test_file: str = ""                           # defaults to checks/issue_<n>.sh
    wrong_attempts: int = 0                       # first N builds write wrong content
    owner_items: tuple[str, ...] = ()             # items needing a capability the host lacks
    bad_owner_items: tuple[str, ...] = ()         # items claimed as owner for a capability the host has
    review_items: tuple[str, ...] = ()            # items proven by the examiner's verdict
    unmet_review: int = 0                         # the first N examinations judge review items unmet
    findings: int = 0                             # the first N examinations report a blocking, reproduced defect
    unquoted_findings: int = 0                    # ... a reproduced defect tied to no item (a follow-up)
    probe: str = "pass"                           # the examiner's probe: pass | unconditional | none
    blocked_once: bool = False                    # the first build needs a path outside its zones
    extra_path: str = ""                          # ... this one
    tamper: bool = False                          # a build after locking edits the locked test
    deferred: tuple[tuple[str, int], ...] = ()    # (item, issue) the plan defers
    lines: dict[str, str] = field(default_factory=dict)   # shared list file -> the line this issue adds
    conflict_tamper: bool = False                 # resolving a conflict, also edits the locked test
    commits: bool = False                         # the builder commits its work (it should not)
    tags: bool = False
    branches: bool = False
    outages: int = 0                              # the first N examinations fail with an outage
    crashes: int = 0                              # the first N builds time out
    no_certify: int = 0                           # the first N examinations withhold the certificate
    impossible: bool = False                      # every build answers blocked, with no typed request
    advisory_findings: int = 0                    # the first N examinations report a finding with no reproduction
    test_change: bool = False                     # the second build amends its (locked) test, with a request


MARKERS = ("<<<<<<<", "=======", ">>>>>>>")


def resolve_union(text: str) -> str:
    """Resolve conflict markers by keeping both sides, each line once."""
    out, inside = [], False
    for line in text.splitlines():
        if line.startswith(MARKERS):
            inside = not line.startswith(">>>>>>>")
            continue
        if not (inside and line in out):
            out.append(line)
    return "\n".join(out) + "\n" if out else ""


def merging(worktree: Path) -> bool:
    return subprocess.run(["git", "rev-parse", "-q", "--verify", "MERGE_HEAD"], cwd=worktree,
                          capture_output=True).returncode == 0


class FakeAgents:
    """Deterministic agents. Tests and probes are shell scripts comparing file contents, so the
    engine's real git, verify and landing code runs end to end without any model."""

    def __init__(self, scripts: dict[int, Script], operator: str = "claude", other: str = "codex"):
        self.scripts = scripts
        self.operator, self.other = operator, other
        self.meter: Meter | None = None
        self.calls: list[tuple] = []
        self._built: dict[int, int] = {}
        self._examined: dict[int, int] = {}
        self._outages: dict[int, int] = {}
        self._crashes: dict[int, int] = {}

    # ------------------------------------------------------------------ helpers
    def _s(self, req: IssueRequest) -> Script:
        return self.scripts[req.issue.number]

    def test_file(self, n: int) -> str:
        return self.scripts[n].test_file or f"checks/issue_{n}.sh"

    def probe_file(self, n: int) -> str:
        return f"checks/probe_{n}.sh"

    def _metered(self, issue, role, vendor, fn, fail: str | None = None):
        if self.meter:
            self.meter.before(issue, role, vendor)
        if fail:
            if self.meter:
                self.meter.after(issue, role, vendor, fail)
            raise AgentFailure(f"{vendor} {role}: {fail}", kind=fail, vendor=vendor)
        result = fn()
        if self.meter:
            self.meter.after(issue, role, vendor, "answered")
        return result

    def _test_script(self, n: int) -> str:
        s = self.scripts[n]
        lines = ["#!/usr/bin/env bash", "set -euo pipefail", f"# acceptance test for issue {n}"]
        for path, content in sorted(s.files.items()):
            lines.append(f'test "$(cat {path})" = "{content}"')
        for path, line in sorted(s.lines.items()):
            lines.append(f"grep -qxF '{line}' {path}")
        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------ roles
    def explore(self, vendor, question, briefing):
        self.calls.append(("explore", vendor, question, briefing))
        return self._metered(None, "explore", vendor, lambda: f"[{vendor}] {question}: nothing surprising.")

    def plan(self, vendor, req, worktree):
        n = req.issue.number
        s = self._s(req)
        self.calls.append(("plan", vendor, n))
        items = []
        deferred = dict(s.deferred)
        for item in req.spec.ledger:
            words = " ".join(item.text.split()[:4])
            if item.id in s.owner_items:
                items.append(ItemPlan(item.id, "needs real hardware", words, "owner",
                                      capability="hardware:laptop", agent_part="time it on this host"))
            elif item.id in s.bad_owner_items:
                items.append(ItemPlan(item.id, "claimed as owner", words, "owner", capability="network:internet",
                                      agent_part="none"))
            elif item.id in deferred:
                items.append(ItemPlan(item.id, "needs another issue", words, "deferred",
                                      depends_on=deferred[item.id], depends_quote="Prerequisite widget"))
            elif item.id in s.review_items:
                items.append(ItemPlan(item.id, "judged by the examiner", words, "review"))
            else:
                items.append(ItemPlan(item.id, "proven by the test", words, "test"))
        zones = sorted(set(s.files) | set(s.lines) | {self.test_file(n)} | ({f"edge_{n}.txt"} if s.findings else set()))
        result = PlanResult(items=items, zones=zones,
                            decisions=[{"id": "approach", "choice": "the simplest variant", "rationale": "fake"}])
        return self._metered(n, "plan", vendor, lambda: result)

    def triage(self, vendor, req, plan):
        self.calls.append(("triage", vendor, req.issue.number))
        return self._metered(req.issue.number, "triage", vendor,
                             lambda: [Objection("misreading", "an unquoted wish for more provenance", item="D1")])

    def build(self, vendor, req, plan, worktree, feedback):
        n = req.issue.number
        s = self._s(req)
        k = self._built.get(n, 0)
        self.calls.append(("build", vendor, n, tuple(feedback)))
        crashes = self._crashes.get(n, 0)
        if crashes < s.crashes:
            self._crashes[n] = crashes + 1
            return self._metered(n, "build", vendor, None, fail="timeout")
        self._built[n] = k + 1

        def run():
            if s.impossible:
                return BuildResult("blocked", "the criteria contradict each other")
            resolving = merging(worktree)
            for path, line in s.lines.items():
                target = worktree / path
                target.parent.mkdir(parents=True, exist_ok=True)
                text = resolve_union(target.read_text()) if target.exists() else ""
                if line not in text.splitlines():
                    text += line + "\n"
                target.write_text(text)
            for path, content in s.files.items():
                target = worktree / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text((content if k >= s.wrong_attempts else "wrong") + "\n")
            test = worktree / self.test_file(n)
            if not test.exists() or not any("locked" in f for f in feedback):
                test.parent.mkdir(parents=True, exist_ok=True)
                test.write_text(self._test_script(n))
            if any("edge" in f for f in feedback):   # a blocking finding asked for the edge case
                (worktree / f"edge_{n}.txt").write_text("handled\n")
            if s.tamper and k >= 1:
                test.write_text("#!/usr/bin/env bash\nexit 0\n")
            if s.conflict_tamper and resolving:
                test.write_text("#!/usr/bin/env bash\nexit 0\n")
            requests = []
            if s.test_change and k == 1:
                test.write_text(self._test_script(n) + "# amended through an approved request\n")
                requests.append(Request("test_change", "the locked test misses a comment the item needs",
                                        paths=[self.test_file(n)]))
            if s.commits:
                subprocess.run(["git", "add", "-A"], cwd=worktree, check=True)
                subprocess.run(["git", "commit", "-qm", "agent commit"], cwd=worktree, check=True)
            if s.tags and k == 0:
                subprocess.run(["git", "tag", f"agent-probe-{n}"], cwd=worktree, check=True)
            if s.branches and k == 0:
                subprocess.run(["git", "branch", f"agent-branch-{n}"], cwd=worktree, check=True)
            if s.blocked_once and k == 0:
                return BuildResult("blocked", "the registry lives outside my zones",
                                   requests=[Request("paths", "register the suite", paths=[s.extra_path])])
            if s.extra_path and (worktree / s.extra_path).parent.exists() and k >= 1 and s.blocked_once:
                (worktree / s.extra_path).write_text(f"suite {n}\n")
            commands = [CheckSpec(criterion=i["id"], command=f"bash {self.test_file(n)}")
                        for i in plan["items"] if i["proof"] in ("test", "command")]
            return BuildResult("done", "built", tests=[self.test_file(n)], commands=commands, requests=requests)
        return self._metered(n, "build", vendor, run)

    def resolve_locked(self, vendor, req, worktree, files, feedback):
        n = req.issue.number
        self.calls.append(("resolve_locked", vendor, n, tuple(files)))

        def run():
            for f in files:
                p = worktree / f
                if p.is_file():
                    p.write_text(resolve_union(p.read_text()))
        return self._metered(n, "resolve_locked", vendor, run)

    def examine(self, vendor, req, plan, worktree, base_sha, head_sha, evidence, memory, requests, since):
        n = req.issue.number
        s = self._s(req)
        self.calls.append(("examine", vendor, n, since is not None))
        outages = self._outages.get(n, 0)
        if outages < s.outages:
            self._outages[n] = outages + 1
            return self._metered(n, "examine", vendor, None, fail="outage")
        k = self._examined.get(n, 0)
        self._examined[n] = k + 1

        def run():
            item = req.spec.ledger[0]
            quote = " ".join(item.text.split()[:4])
            findings, probes = [], []
            if k < s.findings:
                findings.append(Finding(id=f"F{n}-{k}", title="an edge case breaks the item", item=item.id, quote=quote,
                                        observed="edge_{n}.txt is missing", expected="the edge case is handled",
                                        reproduction=f"test -f edge_{n}.txt"))
            if k < s.unquoted_findings:
                findings.append(Finding(id=f"U{n}-{k}", title="a nicer error message", observed="terse",
                                        expected="friendlier", reproduction=f"test -f friendlier_{n}.txt"))
            if k < s.advisory_findings:
                findings.append(Finding(id=f"A{n}-{k}", title="the edge case may break the item", item=item.id,
                                        quote=quote, observed="unclear", expected="the edge case is handled"))
            if s.probe != "none" and since is None:
                body = ("#!/usr/bin/env bash\nexit 1\n" if s.probe == "unconditional"
                        else "#!/usr/bin/env bash\nset -e\n" + "".join(f"test -s {p}\n" for p in sorted(s.files)))
                tested = [i["id"] for i in plan["items"] if i["proof"] == "test"] or [item.id]
                for k2, crit in enumerate(tested):   # one independent probe per behavioural item
                    f = self.probe_file(n) if k2 == 0 else f"checks/probe_{n}_{crit}.sh"
                    probes.append(Probe(f, crit, f"bash {f}", content=body))
            verdicts = []
            judged = [p["id"] for p in plan["items"] if p["proof"] == "review"
                      or (p["proof"] == "owner" and (p.get("agent_part") or "none") != "none")]
            for i in judged:
                text = next(li.text for li in req.spec.ledger if li.id == i)
                verdict = "unmet" if k < s.unmet_review else "met"
                verdicts.append({"item": i, "verdict": verdict, "quote": " ".join(text.split()[:4]), "note": "fake"})
            decisions = [Decision(r["id"], True, "the path is the suite registry") for r in requests]
            return ExamResult(verdicts=verdicts, findings=findings, probes=probes, decisions=decisions,
                              certify=k >= s.no_certify, summary="fake examination")
        return self._metered(n, "examine", vendor, run)

    def decide(self, vendor, req, worktree, requests):
        n = req.issue.number
        self.calls.append(("decide", vendor, n, tuple(r["id"] for r in requests)))
        return self._metered(n, "decide", vendor, lambda: [Decision(r["id"], True, "fine") for r in requests])

    def arbitrate(self, vendor, req, dispute):
        n = req.issue.number
        self.calls.append(("arbitrate", vendor, n, dispute.get("kind")))
        return self._metered(n, "arbitrate", vendor, lambda: Ruling(True, "the item as written requires it"))
