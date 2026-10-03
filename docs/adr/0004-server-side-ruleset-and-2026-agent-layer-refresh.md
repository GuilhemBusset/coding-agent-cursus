# ADR 0004 — Server-side PR-only ruleset, and the August 2026 agent-layer refresh

- **Status:** Accepted — partially superseded by [ADR 0005](0005-drop-per-agent-guard-layer.md) (per-agent guard layer removed) and [ADR 0007](0007-required-ci-gate-and-merge-forward-shipping.md) (repo checks now required)
- **Date:** 2026-08-18
- **Deciders:** Guilhem Busset (instructor / repo owner)
- **Context:** [ADR 0002](0002-agent-agnostic-claude-code-and-codex.md), [ADR 0003](0003-ship-as-shared-skill-and-codex-convenience-layer.md)

## Context

The agent layers shipped by ADR 0002/0003 (June 2026) were re-verified against current official
documentation (code.claude.com, developers.openai.com/codex, agentskills.io, GitHub docs) in
August 2026, because the repo is cloned by external students and should model idiomatic usage.

The architecture held up: agent-neutral scripts + thin per-agent wrappers is still the state of
the art, no cross-agent hooks/permissions standard has emerged (the Agentic AI Foundation now
stewards AGENTS.md, Agent Skills, and MCP, but convergence stops at the context-file and skill
layers), Claude Code still does not read `AGENTS.md` natively (the `CLAUDE.md` → `@AGENTS.md`
shim remains the documented bridge), and no shared skills directory exists (Codex discovers
`.agents/skills/`; Claude Code only `.claude/skills/`).

The audit also found concrete problems:

1. **Server-side prevention existed only as hand-made, unreproducible state.** The live repo
   turned out to carry a manually created ruleset ("Protect main") that no repo file mentioned:
   invisible to readers of the tree, absent from every fork, and impossible to audit or
   reproduce. The repo's own docs described the CI audit as the only server-side layer. GitHub
   **rulesets** (the successor to classic branch protection; free on public repos; JSON
   import/export; visible to anyone with read access) are the current idiom for "PR-only main" —
   and checking the definition in makes the guarantee reproducible.
2. **A Codex skill-policy bug.** `agents/openai.yaml` had `allow_implicit_invocation: false` at
   top level, where it is silently ignored — it must be nested under `policy:`. The
   side-effectful ship skill was therefore still eligible for implicit invocation.
3. **cwd-fragile hooks in both harnesses.** Hook commands used repo-relative paths but execute in
   the *session* cwd. With ADR 0001's per-session subfolders, a session launched inside a
   subfolder gets silently failing hooks — and Codex hooks are documented to **fail open**.
4. **Unused current mechanisms.** Codex now supports declarative execution-policy rules
   (Starlark `prefix_rule` files under `.codex/rules/`, trust-gated like the rest of the project
   layer) — the idiomatic first line for blocking shell commands. Codex hooks are also now on by
   default but **per-hash trust-gated** (`/hooks`), which student onboarding must mention.
5. **Skill-body drift.** The two `SKILL.md` copies (accepted by ADR 0003) had already drifted in
   wording, with nothing to catch it.

## Decision

**Add a server-side GitHub ruleset as the hard PR-only guarantee; fix and modernize the per-agent
convenience layers to August 2026 idiom; single-source the ship skill body with CI enforcing the
mirror.**

1. **Ruleset as the top enforcement layer.** `.github/rulesets/pr-only-main.json` targets
   `~DEFAULT_BRANCH`: require a PR (0 approvals — PRs are required, solo merges stay possible,
   preserving the ship flow), block force-pushes (`non_fast_forward`) and deletion, **empty
   bypass list** (admins bound too). Because rulesets are per-repo server state and are not
   inherited by forks, the JSON is checked in and applied idempotently by
   `scripts/apply-ruleset.sh` (`gh api`; there is no `gh ruleset create` yet). The CI audit
   `pr-only.yml` **stays**: it is the only server-side guard that travels with a fork, and it
   catches any window where the ruleset was disabled or bypassed.
2. **Codex layer fixes.** `allow_implicit_invocation: false` moves under `policy:` in
   `agents/openai.yaml`. Hook commands in `.codex/config.toml` resolve the repo root via
   `git rev-parse --show-toplevel` before invoking the shared scripts; `statusMessage` becomes
   the documented TOML spelling `status_message`.
3. **Codex execution-policy rules.** `.codex/rules/protected-main.rules` forbids the common
   `git push origin main|master` spellings declaratively. Division of labor: rules catch common
   spellings, the PreToolUse hook catches arbitrary forms (`HEAD:main`, `--no-verify`), the
   ruleset + git hooks remain the guarantee — necessary because Codex hooks fail open.
4. **Claude Code layer fix.** `.claude/settings.json` hook commands use the documented
   `$CLAUDE_PROJECT_DIR` idiom instead of relative paths. Everything else (deny-list, hook
   events, skill frontmatter incl. `disable-model-invocation`, exit-code-2 deny) was confirmed
   current and stays. Plugins/marketplaces were considered and rejected: for a repo students
   clone directly, a checked-in `.claude/` directory is the recommended, more transparent shape.
5. **Single-sourced skill body, mirrored, CI-enforced.** `.agents/skills/ship/SKILL.md` is the
   source of truth; `.claude/skills/ship/SKILL.md` is a byte-identical copy (symlinks stay
   rejected per ADR 0003 / Windows checkouts). One body serves both harnesses: Claude-specific
   frontmatter (`disable-model-invocation`, `allowed-tools`) is ignored by Codex, whose
   no-implicit-invoke policy lives in `agents/openai.yaml`. A new `checks.yml` workflow fails
   any PR where the copies differ (plus shell-syntax/JSON/TOML sanity checks). It is advisory
   CI, not a required check in the ruleset.

## Consequences

**Positive**
- Direct pushes to `main` are now *impossible* server-side, not merely audited after the fact —
  and students can read the exact policy in the repo and reproduce it on a fork with one command.
- The Codex skill policy actually does what ADR 0003 intended; hooks work from per-session
  subfolders in both harnesses.
- Skill drift is now caught mechanically instead of by hope.

**Negative / costs (accepted)**
- The ruleset must be applied once per repo/fork by an admin (`scripts/apply-ruleset.sh`);
  until then, hooks + CI audit are the floor. Documented in README/CONTRIBUTING.
- Codex students have a two-step trust onboarding (trust project, then `/hooks`), repeated per
  hook change. This is Codex's security model, not ours to remove; it is documented.
- The per-agent layers are verified against August 2026 docs, not pinned; a schema change could
  again require a refresh. The ruleset + git + CI guarantee is unaffected either way.

**Neutral**
- If Claude Code ships native `.agents/skills/` / `AGENTS.md` support (anthropics/claude-code
  #31005 / #6235), the mirror copy and the `@AGENTS.md` shim can be deleted with zero migration.

## Alternatives considered

1. **Rely on classic branch protection.** Rejected: rulesets are the successor — layerable,
   read-visible to students, JSON-importable, with a stricter bypass model.
2. **Drop the CI audit now that the ruleset prevents.** Rejected: forks get no ruleset until
   applied; the audit travels with the repo for free and costs nothing when quiet.
3. **Symlink or build-step generation for the skill mirror.** Rejected again (ADR 0003): Windows
   checkouts materialize symlinks as plain files; a generated non-checked-in mirror would be
   invisible to a fresh clone's first session. A byte-identical checked-in copy + CI diff is
   simpler and robust.
4. **Ship recommended `approval_policy`/`sandbox_mode` (Codex) or `defaultMode` (Claude Code)
   from the project layer.** Rejected: silently changing a student's approval posture from a
   cloned repo is surprising; recommendations belong in the course material.
5. **Package the Claude layer as a plugin/marketplace.** Rejected for now: adds indirection for
   a repo that students clone directly; revisit if the setup should ever be installed *into*
   other repos rather than used inside this one.

## How this stays true

- The enforcement ladder is documented in `AGENTS.md` (ruleset → git hooks → CI audit →
  per-agent convenience) and each layer's file names its role.
- `checks.yml` mechanically enforces the skill mirror and config sanity on every PR.
- This ADR is the reference for "PR-only is enforced server-side" and for the August 2026
  verification date of the per-agent layers.
