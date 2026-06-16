# ADR 0002 — The repository works identically under both Claude Code and Codex

- **Status:** Accepted
- **Date:** 2026-06-16
- **Deciders:** Guilhem Busset (instructor / repo owner)
- **Context:** [`docs/cursus-narrative.md`](../cursus-narrative.md), [`docs/cursus-key-technical-notions.md`](../cursus-key-technical-notions.md), [ADR 0001](0001-self-contained-per-session-subfolders.md)

## Context

The cursus teaches more than one harness on purpose. Session 1 sets up *both* the Claude Code and
Codex CLIs as the standard toolchain; Session 3's whole thesis is that "a coding agent" is a
spectrum of interchangeable harnesses (Claude Code CLI, Codex CLI, Gemini CLI, aider…) and that
**Agent = Model + Harness**, with headless mode (`claude -p`, `codex exec`) as the universal
primitive. Students will drive Codex in some labs and Claude Code in others.

That makes one property non-negotiable: every guarantee and workflow this repo provides must hold
under *either* agent. If the protected-`main` spine only worked inside Claude Code, it would
evaporate the instant a student drove Codex — which the course explicitly asks them to do — and the
repo would be quietly contradicting its own lesson that the harness is swappable.

Where the spine stands today, read straight off the tree:

- **Agent-independent** (fire for any agent, any git client, and humans):
  - `.githooks/pre-commit` — blocks commits while `HEAD` is on `main`/`master`.
  - `.githooks/pre-push` — blocks pushes targeting `main`/`master`.
  - `.github/workflows/pr-only.yml` — server-side audit that every commit on `main` arrived via a merged PR.
- **Claude Code-only** (fire only inside Claude Code):
  - `.claude/hooks/guard-main.sh` — PreToolUse Bash guard (the fast, in-loop block).
  - `.claude/settings.json` — the deny-list **and** the SessionStart hook that wires `core.hooksPath → .githooks`.
  - `.claude/commands/ship.md` — the `/ship` command, whose entire logic lives in this Claude-only file.
  - `CLAUDE.md` — repo conventions. Codex reads `AGENTS.md`, which does not yet exist.

Two gaps follow directly: the agent-independent git hooks are *activated* only by a Claude-only
SessionStart hook, and both the `/ship` workflow and the repo instructions exist only in
Claude-only form.

## Decision

**Treat Claude Code and Codex as co-equal, first-class harnesses. Every guarantee and workflow must
function under either; agent-specific configuration is a thin convenience layer over an
agent-independent source of truth.**

1. **Enforcement lives at agent-independent layers — git hooks and CI — never solely in one agent's
   harness.** The protected-`main` guarantees (no direct commit/push, PR-only, no
   `--no-verify`/`--force`) are *owned* by `.githooks/*` and `pr-only.yml`. These are the source of
   truth and hold even for an agent with zero special config, or a human at a bare terminal.

2. **Activation of those hooks must not depend on a single agent.** `core.hooksPath → .githooks` is
   wired today only by Claude Code's SessionStart. It must also be reachable without Claude Code: a
   one-time, agent-neutral setup (a checked-in `scripts/setup.sh`, documented identically for both
   agents) plus the equivalent Codex startup wiring where available. Until a session has wired the
   hooks, the CI audit (`pr-only.yml`) remains the agent-independent backstop.

3. **Repo instructions have one source of truth, read by both agents.** `AGENTS.md` — the
   vendor-neutral file Codex and a growing set of agents read — is canonical; `CLAUDE.md` imports it
   (`@AGENTS.md`) so the two cannot drift. Instruction *wording* is agent-neutral: "run `/ship`, or
   open a PR", not "run /ship in Claude Code" (the current pre-commit/pre-push messages and
   `CLAUDE.md` are phrased Claude-only and get neutralized).

4. **Per-agent niceties are thin wrappers over shared scripts.** Claude Code's PreToolUse guard and
   `/ship` command are *convenience*; Codex gets an equivalent (its own config/hook + custom
   prompt). The portable logic lives once in an agent-independent script (e.g. `scripts/ship.sh`,
   and `guard-main.sh` reused as a plain pre-tool check) that each agent's command merely invokes —
   so `/ship` behaves identically whichever harness runs it. If an agent lacks a given hook
   mechanism, the git + CI layer still holds: defense in depth, not a single point of dependency.

5. **Labs and CI never require a specific agent.** Where a lab drives an agent headless, both
   `claude -p` and `codex exec` are first-class; agent-specific *features* are taught as such, but a
   student must always be able to complete the repo's core workflow on either.

## Consequences

**Positive**
- The repo practices the course's own thesis: the harness is swappable, so the guarantees live below it.
- A student on either CLI gets identical protected-`main` behavior; no lock-in to one vendor.
- The strongest guarantees (git hooks + CI) hold even for a misconfigured agent or a bare human
  terminal — the agnostic layer is the floor, not the ceiling.

**Negative / costs (accepted)**
- Two convenience layers to maintain (Claude + Codex), plus the shared scripts they wrap.
- Exact feature parity is impossible: Claude's PreToolUse gives an *instant* in-loop block Codex may
  not mirror identically. We accept that the *shape/speed* of feedback can differ as long as the
  *guarantee* (git + CI) is identical.

**Neutral**
- Adding a future agent (Gemini CLI, aider, …) = one more thin wrapper pointing at the same scripts;
  the source of truth does not move.

## Alternatives considered

1. **Claude Code-only (status quo extended).** Rejected: directly contradicts Sessions 1 and 3,
   creates vendor lock-in, and silently drops every guarantee the moment a student uses Codex.
2. **Enforce inside each agent's harness, per agent.** Rejected: N copies of the rules that drift,
   and any vanilla agent or human bypasses them all. Enforcement must sit at git + CI.
3. **Drop all agent-specific config; rely only on git + CI.** Rejected: loses the fast in-loop
   feedback that is itself a Session-1 teaching moment (the PreToolUse block). We want both — the
   agnostic guarantee *and* per-agent convenience.

## How this stays true

A documented, durable convention reinforced by structure:
- The source of truth is already agent-independent (git hooks + CI); agent configs only ever *wrap* it.
- Instruction drift is structurally prevented by a single canonical `AGENTS.md` that `CLAUDE.md` imports.
- New-agent support is additive and points at the same shared scripts.

This ADR is the reference for "works with both."
