"""Which issues may move now.

An issue may start once every prerequisite in the run is accepted (merged and re-verified on
`main`). Writing phases run in parallel only for issues whose declared files do not overlap,
and at most one in-flight issue may hold any shared file.
"""

from __future__ import annotations

from .config import SHARED_FILES, SHARED_PREFIXES
from .graph import Plan
from .model import SATISFIES_DEPENDENTS, Phase


def overlaps(a: str, b: str) -> bool:
    """Two declared paths overlap if equal or one is a directory containing the other."""
    a, b = a.rstrip("/"), b.rstrip("/")
    return a == b or b.startswith(a + "/") or a.startswith(b + "/")


def is_shared(path: str) -> bool:
    """Repo-root shared files (a session's own README is not shared) and shared directories."""
    return path in SHARED_FILES or path.startswith(SHARED_PREFIXES)


def prerequisites_met(plan: Plan, phases: dict[int, Phase], n: int) -> bool:
    return all(phases.get(d) in SATISFIES_DEPENDENTS for d in plan.deps.get(n, set()))


def conflicts(paths: list[str], held: list[list[str]]) -> bool:
    shared = any(is_shared(p) for p in paths)
    for other in held:
        if shared and any(is_shared(p) for p in other):
            return True
        if any(overlaps(p, q) for p in paths for q in other):
            return True
    return False


def can_start_writing(plan: Plan, n: int, in_flight: list[int], max_writers: int) -> bool:
    """May issue `n` enter its first writing phase alongside the issues already writing?"""
    if len(in_flight) >= max_writers:
        return False
    mine = plan.specs[n].declared_paths
    held = [plan.specs[m].declared_paths for m in in_flight if m != n]
    # An issue that declares no paths cannot prove it is disjoint, so it writes alone.
    if not mine and in_flight:
        return False
    if any(not h for h in held):
        return False
    return not conflicts(mine, held)
