"""Caps and repo-specific constants. Correctness caps only: there is no budget cap by choice."""

from dataclasses import dataclass, field

# Files many issues tend to touch. Only one in-flight issue may own any of them at a time.
SHARED_FILES = frozenset({
    "README.md", "AGENTS.md", "CLAUDE.md", "CONTRIBUTING.md", ".gitignore",
    "pyproject.toml", "uv.lock", "mise.toml", "package.json", "package-lock.json",
})
SHARED_PREFIXES = (".github/workflows/", ".githooks/")

# Top-level entries that mark a backticked token as repo-relative rather than session-relative.
REPO_TOP_LEVEL = (
    "sessions/", "tools/", "scripts/", "setup/", "docs/", ".github/", ".claude/", ".agents/",
    ".githooks/", "README.md", "AGENTS.md", "CLAUDE.md", "CONTRIBUTING.md", "LICENSE",
)

# Files that can change how tests run without touching a test file.
TEST_CONFIG_NAMES = frozenset({"conftest.py", "pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml"})


@dataclass(frozen=True)
class Caps:
    design_rounds: int = 2
    implement_attempts: int = 3
    fix_rounds: int = 2
    same_blocker_limit: int = 3
    max_parallel_writers: int = 3
    max_parallel_agents: int = 6
    check_timeout_s: int = 900
    ci_timeout_s: int = 3600
    ci_poll_s: int = 20


@dataclass(frozen=True)
class Config:
    repo: str
    caps: Caps = field(default_factory=Caps)
    base_branch: str = "main"
    remote: str = "origin"
    required_check: str = "required"
    api_version: str = "2022-11-28"
    label_prefix: str = "loop:"
