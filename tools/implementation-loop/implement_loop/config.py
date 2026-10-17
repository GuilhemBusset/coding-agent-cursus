"""Caps, ceilings and repo-specific constants (ADR 0012)."""

from dataclasses import dataclass, field

# Files many issues tend to touch. Only one in-flight issue may own any of them at a time.
SHARED_FILES = frozenset({
    "README.md", "AGENTS.md", "CLAUDE.md", "CONTRIBUTING.md", ".gitignore",
    "setup/package.json", "setup/package-lock.json", "setup/README.md",
    "tools/html-pages/tests/component-helpers.mjs",
})
SHARED_PREFIXES = (".github/workflows/", ".githooks/")

# Top-level entries that mark a backticked token as repo-relative rather than session-relative.
REPO_TOP_LEVEL = (
    "sessions/", "tools/", "scripts/", "setup/", "docs/", ".github/", ".claude/", ".agents/",
    ".githooks/", "README.md", "AGENTS.md", "CLAUDE.md", "CONTRIBUTING.md", "LICENSE",
)

# Files that can change how tests run without touching a test file.
TEST_CONFIG_NAMES = frozenset({"conftest.py", "pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml"})

# Paths a builder changes only with the examiner's approval (a `protected_change` request),
# unless the issue's own text names them: the loop's machinery and the repository's gates.
PROTECTED_PREFIXES = ("tools/implementation-loop/", ".github/", ".githooks/")
PROTECTED_FILES = frozenset({"scripts/check-loop-guard.sh", "scripts/implement.sh", "scripts/ship.sh",
                             "setup/pr-only-main.json", "setup/homework-branches.json"})

# The safety surface: what a fault-repair run may never change, whatever any agent approves.
# A fault whose fix needs it stays filed for the owner (ADR 0012).
SAFETY_SURFACE_FILES = frozenset({
    "tools/implementation-loop/implement_loop/verify.py",
    "tools/implementation-loop/implement_loop/loop_pytest.py",
    "tools/implementation-loop/implement_loop/gate.py",
    "tools/implementation-loop/implement_loop/live.py",
    "tools/implementation-loop/implement_loop/config.py",
    "tools/implementation-loop/implement_loop/supervisor.py",
    "tools/implementation-loop/loop.toml",
    "scripts/check-loop-guard.sh",
})
SAFETY_SURFACE_PREFIXES = (".github/", ".githooks/", "setup/pr-only-main.json", "setup/homework-branches.json")


def is_protected(path: str) -> bool:
    return path in PROTECTED_FILES or path.startswith(PROTECTED_PREFIXES)


def is_safety_surface(path: str) -> bool:
    return path in SAFETY_SURFACE_FILES or path.startswith(SAFETY_SURFACE_PREFIXES)


# Per-issue ceilings on answered agent calls, by size label; infra issues get x1.5.
CEILINGS = {"S": 20, "M": 30, "L": 45}
INFRA_FACTOR = 1.5
INFRA_PREFIXES = ("tools/", "scripts/", ".github/", "setup/")


@dataclass(frozen=True)
class Caps:
    infra_budget: int = 10            # attempts that timed out or crashed, per issue
    unproductive_replan: int = 2      # consecutive unproductive rounds before a replan
    unproductive_fail: int = 4        # ... before the issue fails (two more after the replan)
    replans: int = 1
    fix_forwards: int = 1             # then a revert PR
    reverts: int = 1
    merge_refusals: int = 3
    run_ceiling_factor: float = 1.2
    max_parallel_writers: int = 3
    max_parallel_agents: int = 6
    check_timeout_s: int = 900
    max_check_timeout_s: int = 1800
    ci_timeout_s: int = 3600
    ci_poll_s: int = 20
    queue_poll_s: int = 30            # polling a merge queue or issue claim another run holds
    queue_wait_s: int = 6 * 3600      # after that, the issue waits for the supervisor instead


@dataclass(frozen=True)
class Config:
    repo: str
    caps: Caps = field(default_factory=Caps)
    base_branch: str = "main"
    remote: str = "origin"
    required_check: str = "required"
    api_version: str = "2022-11-28"
    label_prefix: str = "loop:"


def ceiling(size: str, infra: bool) -> int:
    base = CEILINGS.get(size, CEILINGS["M"])
    return int(base * INFRA_FACTOR) if infra else base
