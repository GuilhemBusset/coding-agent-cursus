"""Resolve what a run must do: the work items, their prerequisites and their order.

Epic mode: walk sub-issues recursively. Issues with sub-issues are tracking issues; leaves
are work items. Single-issue mode: the issue plus its open prerequisite closure. In both
modes, open prerequisites outside the starting tree are pulled in and flagged as external,
and the order comes from native blocked-by links, never from labels or titles.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from . import issue_parser
from .github import GitHub
from .model import Issue, IssueSpec


class CycleError(RuntimeError):
    def __init__(self, members: list[int]):
        super().__init__(f"dependency cycle among issues {sorted(members)}")
        self.members = sorted(members)


@dataclass
class Plan:
    root: int
    mode: str                                   # "epic" | "issue"
    issues: dict[int, Issue]
    specs: dict[int, IssueSpec]
    tracking: dict[int, list[int]]              # tracking issue -> direct children
    parent: dict[int, int]
    work: list[int]                             # open work items, topological order
    closed_work: list[int]
    external: set[int]
    deps: dict[int, set[int]]                   # open work item -> open prerequisites in this run
    satisfied: dict[int, set[int]]              # open work item -> prerequisites already closed
    waves: dict[int, int]
    warnings: list[str] = field(default_factory=list)

    def dependents(self, n: int) -> list[int]:
        return [m for m in self.work if n in self.deps.get(m, set())]


def existing_session_dirs(repo_root: Path) -> list[str]:
    sessions = repo_root / "sessions"
    if not sessions.is_dir():
        return []
    return sorted(f"sessions/{p.name}" for p in sessions.iterdir() if p.is_dir())


def build_plan(gh: GitHub, root: int, repo_root: Path) -> Plan:
    issues: dict[int, Issue] = {}

    def get(n: int, data: dict | None = None) -> Issue:
        if n not in issues:
            issues[n] = Issue.from_api(data if data is not None else gh.get_issue(n))
        return issues[n]

    root_issue = get(root)
    tracking: dict[int, list[int]] = {}
    parent: dict[int, int] = {}
    leaves: list[int] = []

    if root_issue.sub_issue_total > 0:
        mode = "epic"
        queue = deque([root])
        while queue:
            n = queue.popleft()
            children = [get(c["number"], c).number for c in gh.list_sub_issues(n)]
            tracking[n] = children
            for c in children:
                parent[c] = n
                if issues[c].sub_issue_total > 0:
                    queue.append(c)
                else:
                    leaves.append(c)
    else:
        mode = "issue"
        leaves = [root]

    open_work = [n for n in leaves if issues[n].is_open]
    closed_work = [n for n in leaves if not issues[n].is_open]
    in_tree = set(leaves)

    deps: dict[int, set[int]] = {}
    satisfied: dict[int, set[int]] = {}
    external: set[int] = set()
    warnings: list[str] = []

    pending = deque(open_work)
    scope = set(open_work)
    while pending:
        n = pending.popleft()
        deps[n], satisfied[n] = set(), set()
        if issues[n].blocked_by_total == 0:
            continue
        for d in gh.list_blocked_by(n):
            dep = get(d["number"], d)
            if not dep.is_open:
                satisfied[n].add(dep.number)
                continue
            if dep.sub_issue_total > 0:
                warnings.append(f"#{n} is blocked by tracking issue #{dep.number}; treating it as satisfied when its sub-issues are.")
            deps[n].add(dep.number)
            if dep.number not in scope:
                scope.add(dep.number)
                pending.append(dep.number)
                if dep.number not in in_tree:
                    external.add(dep.number)
                    warnings.append(f"#{dep.number} is an open prerequisite outside #{root}; it is pulled into this run.")

    order = topological_order(scope, deps)
    waves = compute_waves(order, deps)

    session_dirs = existing_session_dirs(repo_root)
    for n in order:
        session_dirs += [d for d in issue_parser.mentioned_session_dirs(issues[n].body) if d not in session_dirs]
    specs = {n: issue_parser.parse(issues[n], session_dirs) for n in order}
    warnings += _lint(order, specs, issues, repo_root)

    return Plan(root=root, mode=mode, issues=issues, specs=specs, tracking=tracking, parent=parent,
                work=order, closed_work=closed_work, external=external, deps={n: deps.get(n, set()) for n in order},
                satisfied={n: satisfied.get(n, set()) for n in order}, waves=waves, warnings=warnings)


def topological_order(nodes: set[int], deps: dict[int, set[int]]) -> list[int]:
    """Kahn's algorithm with the lowest issue number first among ready nodes, so order is stable."""
    indegree = {n: len(deps.get(n, set()) & nodes) for n in nodes}
    ready = sorted(n for n, d in indegree.items() if d == 0)
    order: list[int] = []
    while ready:
        n = ready.pop(0)
        order.append(n)
        for m in sorted(nodes):
            if n in deps.get(m, set()):
                indegree[m] -= 1
                if indegree[m] == 0:
                    ready.append(m)
                    ready.sort()
    if len(order) != len(nodes):
        raise CycleError([n for n in nodes if n not in order])
    return order


def compute_waves(order: list[int], deps: dict[int, set[int]]) -> dict[int, int]:
    waves: dict[int, int] = {}
    for n in order:
        prereqs = [waves[d] for d in deps.get(n, set()) if d in waves]
        waves[n] = 1 + max(prereqs) if prereqs else 0
    return waves


def _lint(order: list[int], specs: dict[int, IssueSpec], issues: dict[int, Issue], repo_root: Path) -> list[str]:
    warnings = []
    branches: dict[str, int] = {}
    for n in order:
        spec = specs[n]
        if not spec.ledger:
            warnings.append(f"#{n} has no Deliverables or Acceptance criteria checkboxes; nothing to prove it done.")
        if not spec.branch:
            warnings.append(f"#{n} has no 'Suggested branch'; the engine will use loop/issue-{n}.")
        elif spec.branch in branches:
            warnings.append(f"#{n} and #{branches[spec.branch]} suggest the same branch {spec.branch}.")
        else:
            branches[spec.branch] = n
        for ref in spec.reference_paths:
            if not (repo_root / ref).exists():
                warnings.append(f"#{n} references {ref}, which does not exist; the issue may be stale.")
    return warnings
