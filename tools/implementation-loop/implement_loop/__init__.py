"""Engine of the `implement` loop: epic or issue in, evidence-backed merged PRs out.

The engine is plain, deterministic Python. It owns the issue graph, the run state, git,
GitHub, the checks and the merge queue. Agents (Claude Code or Codex, run headless) only
produce proposals, patches and findings through the `Agents` interface in `agents.py`.
"""

VERSION = "0.2.0"
