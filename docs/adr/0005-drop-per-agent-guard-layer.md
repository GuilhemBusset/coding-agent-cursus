# ADR 0005 — Drop the per-agent protected-`main` guard layer

- **Status:** Accepted
- **Date:** 2026-10-03
- **Deciders:** Guilhem Busset (instructor / repo owner)
- **Context:** [ADR 0002](0002-agent-agnostic-claude-code-and-codex.md), [ADR 0003](0003-ship-as-shared-skill-and-codex-convenience-layer.md), [ADR 0004](0004-server-side-ruleset-and-2026-agent-layer-refresh.md)
- **Supersedes in part:** ADR 0002 (the guard half of decision 4; the rejection of alternative 3),
  ADR 0003 (decisions 3 and 4), ADR 0004 (the Codex hook fixes in decision 2; decisions 3 and 4)

## Context

ADR 0002 put the protected-`main` guarantee at agent-independent layers (git hooks + CI) and
kept a per-agent *convenience* layer on top. It explicitly rejected "drop all agent-specific
config; rely only on git + CI" because the instant in-loop PreToolUse block was fast feedback
and a Session-1 teaching moment. ADR 0003 extended that layer to Codex, and ADR 0004 refreshed
it and added the server-side GitHub ruleset.

The ruleset is now applied and verified on the canonical repo (`enforcement: active`, empty
bypass list, `current_user_can_bypass: never`). That changes the premise of the per-agent layer:

1. **The guarantee is absolute server-side.** The per-agent guards re-implemented, in two
   harness-specific dialects, a rule GitHub already enforces for every agent and every human.
2. **The layer was expensive for what it added.** It required three mechanisms: a Claude Code
   PreToolUse hook plus deny-list, a Codex PreToolUse hook plus execution-policy rules, and a
   140-line `shlex`-based shared guard script. It also needed CI sanity checks for both config
   files and a two-step Codex trust onboarding (`/hooks`, re-approved after every hook change).
   And it had to be re-verified whenever either harness changed its schema; ADR 0004 was exactly
   such a refresh.
3. **It was partial by construction.** Codex hooks fail open, and deny-list and `prefix_rule`
   patterns only match common spellings. It was never a guarantee, only an early warning.
4. **The teaching point is stronger without it.** The repo's thesis is that the harness is
   swappable, so the guarantees live below it. Having no harness-level enforcement shows that
   more clearly than enforcing the same rule in three places.

## Decision

**Remove the per-agent guard layer entirely. Enforcement of protected `main` lives only at
agent-independent layers.**

Removed:
- `.claude/settings.json`: the SessionStart hook (`scripts/setup.sh`), the `PreToolUse(Bash)`
  hook (`scripts/guard-main.sh`), and the push / `--no-verify` deny-list.
- `.codex/config.toml` (SessionStart and `PreToolUse` hooks) and
  `.codex/rules/protected-main.rules`.
- `scripts/guard-main.sh`.
- The `checks.yml` steps that validated the two removed config files.

Kept, unchanged:
- The GitHub ruleset (`.github/rulesets/pr-only-main.json` + `scripts/apply-ruleset.sh`), which
  is the guarantee.
- `.githooks/pre-commit` and `.githooks/pre-push`, activated by hand once per clone with
  `scripts/setup.sh`.
- The `pr-only.yml` CI audit, the server-side backstop that travels with forks.
- The `/ship` skills in both harnesses and `agents/openai.yaml`. They are workflow convenience,
  not enforcement.
- The `CLAUDE.md` → `@AGENTS.md` shim.

## Consequences

**Positive**
- One enforcement story for every agent and every human. Nothing needs re-verifying when Claude
  Code or Codex change their hook or permission schemas.
- Students no longer go through Codex's `/hooks` trust onboarding for this repo.
- Less code: the guard script and both config files are gone, and the `AGENTS.md` enforcement
  section is shorter.

**Negative / costs (accepted)**
- **No instant in-loop block.** An agent that runs `git push origin main` now learns from the
  pre-push hook (if activated) or from GitHub's rejection, not before the command runs. The
  command still fails and nothing lands; the feedback arrives one step later, not weaker.
- **Git-hook activation is no longer automatic** for Claude Code and Codex users. A clone that
  never ran `scripts/setup.sh` has no local hooks, so a commit on `main` is not blocked locally
  and only the server rejects the push. On a fork where `scripts/apply-ruleset.sh` was never
  run, a direct push to `main` succeeds and only the CI audit flags it, after the fact. README
  and CONTRIBUTING tell every clone to run `scripts/setup.sh`.
- **`--no-verify` is no longer intercepted for agents.** It remains forbidden by convention
  (`AGENTS.md`). Wherever the ruleset is applied, skipping hooks still cannot get a commit onto
  `main`.
- **The Session-1 "PreToolUse block" demo (ADR 0002) no longer exists in this repo.** The course
  docs now use the ruleset as the live boundary-control example. Hooks as a harness mechanism can
  still be taught on a lab repo.

**Neutral**
- ADR 0001's "guardrail spine" list still names `.claude/hooks/guard-main.sh` and the
  `settings.json` deny-list. Read that list as: ruleset, git hooks, CI audit, and `/ship`.
- Re-adding a per-agent layer later is cheap (it is in git history). If that happens, it should
  again wrap a shared script, per ADR 0002, and needs a new ADR.

## Alternatives considered

1. **Remove only the blocking parts; keep the SessionStart hooks to auto-activate git hooks.**
   Rejected: it keeps both config files and Codex's trust onboarding just to save a one-time
   command per clone.
2. **Also remove the git hooks and `scripts/setup.sh`; rely on the server alone.** Rejected: the
   hooks are agent-independent and cost nothing. They answer before any network round-trip, and
   on a fork without the ruleset they are the only thing that blocks a push before it lands.
3. **Keep the layer as refreshed by ADR 0004.** Rejected for the reasons under Context.

## How this stays true

- `AGENTS.md` states that there is no per-agent guard layer and points here.
- The enforcement ladder is: ruleset → git hooks → CI audit. Any future per-agent
  protected-`main` config needs a new ADR.
