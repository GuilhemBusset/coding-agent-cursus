# ADR 0003 — `/ship` is an Agent Skill, and Codex gets a first-class convenience layer

- **Status:** Accepted
- **Date:** 2026-06-20
- **Deciders:** Guilhem Busset (instructor / repo owner)
- **Context:** [ADR 0002](0002-agent-agnostic-claude-code-and-codex.md), [ADR 0001](0001-self-contained-per-session-subfolders.md), [`docs/cursus-narrative.md`](../cursus-narrative.md)

## Context

ADR 0002 declared Claude Code and Codex co-equal harnesses and called for "agent-specific
configuration [that] is a thin convenience layer over an agent-independent source of truth," with
Codex explicitly slated to get "its own config/hook + custom prompt." When 0002 was written, only
the agent-independent half had shipped (`AGENTS.md`, `scripts/setup.sh`, `scripts/ship.sh`,
`.githooks/*`, `pr-only.yml`). Two things had not, and the repo's own docs already promised them —
`CONTRIBUTING.md` says "run `/ship` (in Claude Code or Codex)", `AGENTS.md` claims to be "read by
every coding agent (Claude Code, Codex…)":

1. **No Codex convenience layer.** There was a `.claude/` but no `.codex/`. A Codex-only user got no
   `/ship` and — more importantly — no automatic activation of the protected-`main` git hooks
   (Claude Code wires `core.hooksPath` via its SessionStart hook; Codex did nothing, leaving the CI
   audit as the only backstop until `scripts/setup.sh` was run by hand).

2. **`/ship` lived only as a Claude slash command** (`.claude/commands/ship.md`).

Two developments since 0002 change the cheapest way to close these gaps:

- **Both harnesses converged on the Agent Skills open standard** ([agentskills.io](https://agentskills.io)):
  a skill is a `SKILL.md` (instruction doc) plus optional deterministic `scripts/`. Claude Code
  merged custom commands into skills (`.claude/commands/x.md` and `.claude/skills/x/SKILL.md` both
  yield `/x`); Codex **deprecated** `~/.codex/prompts` custom prompts in favour of skills precisely
  because prompts could not be shared through the repo.
- **Codex's hook schema mirrors Claude Code's** — `SessionStart` (`matcher = "startup"`) and
  `PreToolUse` (`matcher = "^Bash$"`), the same `tool_name` / `tool_input.command` JSON payload on
  stdin, and the same `exit 2` + stderr to deny — so one guard script can serve both.

This is the same primitive Session 2 of the cursus introduces as load-bearing — *SKILL.md +
deterministic scripts; judgment to the model, determinism to scripts that never call a model*. Our
`/ship` (a `ship.md` instruction doc over the deterministic `scripts/ship.sh`) already *is* that
shape; naming it a Skill makes the repo's own spine embody the primitive it teaches.

## Decision

**Re-express `/ship` as an Agent Skill in each harness's native location, both wrapping the one
shared `scripts/ship.sh`; and give Codex a `.codex/` convenience layer that points at the same
shared scripts Claude Code uses.**

1. **`/ship` becomes a skill, not a command.** `.claude/commands/ship.md` is removed in favour of
   `.claude/skills/ship/SKILL.md`. Because shipping has side effects, the model must not auto-invoke
   it: the Claude skill sets `disable-model-invocation: true`; the Codex skill sets
   `allow_implicit_invocation: false` (in `agents/openai.yaml`). Both remain explicitly invocable as
   `/ship`.

2. **Two thin wrappers, one shared script — not one shared file.** Claude Code discovers skills only
   under `.claude/skills/`; Codex scans the agent-neutral `.agents/skills/` (from cwd up to the repo
   root). A single natively-shared `SKILL.md` is therefore impossible, and a symlink between the two
   paths is rejected: this is a cross-OS teaching repo where a Windows checkout can materialise a
   symlink as a plain file, breaking ADR 0001's "check out any session and it just works." So the
   `SKILL.md` lives twice (`.claude/skills/ship/` and `.agents/skills/ship/`), each a thin driver
   over the **single** source of truth for the deterministic mechanics, `scripts/ship.sh`. This is
   exactly ADR 0002's "thin wrappers over shared scripts," and the prose duplication is the
   "two convenience layers to maintain" cost 0002 already accepted — now smaller, because the
   guarantee and the git mechanics are single-sourced.

3. **The PreToolUse guard is extracted to an agent-neutral path.** `.claude/hooks/guard-main.sh`
   moves to `scripts/guard-main.sh`. Both Claude Code (`.claude/settings.json`) and
   Codex (`.codex/config.toml`) invoke that one script as their `PreToolUse(Bash)` hook — no agent
   reaches into another's private directory, and the guard logic has a single owner.

4. **Codex gets `.codex/config.toml`.** It wires `SessionStart → bash scripts/setup.sh` (the analog
   of Claude Code's SessionStart, activating the git hooks) and `PreToolUse(Bash) →
   scripts/guard-main.sh`. Project `.codex/` layers load only when the project is
   trusted; until then, as for any unconfigured agent, the git hooks + CI audit remain the floor.

## Consequences

**Positive**
- The docs' promise ("`/ship` in Claude Code or Codex"; "read by every coding agent") is now true.
- A Codex-only user gets automatic hook activation and an in-loop guard, not just the CI backstop.
- The deterministic spine (`scripts/ship.sh`, `scripts/setup.sh`, `scripts/guard-main.sh`)
  is single-sourced; each agent's config and skill are thin wrappers, per ADR 0002.
- The repo practises the course's own thesis a second time: its meta-infrastructure is built from
  the Session-2 Skill primitive.

**Negative / costs (accepted)**
- The `ship` `SKILL.md` prose exists in two files and can drift. Mitigation: the deterministic core
  is single-sourced in `scripts/ship.sh`, and each `SKILL.md` cross-references its twin. A future
  drift-check could diff the two bodies.
- Codex's hook/skill behaviour is verified against current docs, not pinned; a Codex schema change
  could require an update. The git + CI guarantee is unaffected either way.

**Neutral**
- Adding a third harness = one more `SKILL.md` under its skill path + one config file pointing at the
  same `scripts/`. The source of truth does not move.

## Alternatives considered

1. **Keep `/ship` as a Claude command; add a separate Codex custom prompt.** Rejected: custom prompts
   are deprecated in Codex and cannot be shared via the repo; skills are the converged primitive.
2. **One shared `SKILL.md` via symlink across `.claude/skills/` and `.agents/skills/`.** Rejected:
   symlink fragility on Windows checkouts conflicts with ADR 0001's standalone-reproducibility.
3. **Skip the Codex layer; rely only on git + CI.** Rejected: it leaves ADR 0002's named gap open and
   the docs' Codex promise unfulfilled, and drops the fast in-loop feedback that is itself a teaching
   moment.

## How this stays true

- The deterministic logic stays single-sourced under `scripts/`; agent configs and skills only wrap it.
- Each harness's `/ship` skill points at the same `scripts/ship.sh`; each PreToolUse guard points at
  the same `scripts/guard-main.sh`.
- This ADR is the reference for "`/ship` is a skill" and "Codex has a convenience layer."
