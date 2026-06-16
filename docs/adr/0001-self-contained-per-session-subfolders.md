# ADR 0001 — Each session is a self-contained, independently deployable subfolder

- **Status:** Accepted
- **Date:** 2026-06-16
- **Deciders:** Guilhem Busset (instructor / repo owner)
- **Context:** [`docs/cursus-narrative.md`](../cursus-narrative.md), [`docs/cursus-key-technical-notions.md`](../cursus-key-technical-notions.md)

## Context

This repository hosts a five-session biweekly cursus that walks a cohort of optimization PhDs
from "what is an LLM" to a cohort-wide, deployed optimization tournament. Two forces pull on how
the repository is laid out, and they pull in opposite directions:

- **Continuity.** The narrative is explicitly built so that "each session makes the next
  inevitable." One thread is carried the whole way: the `P01–P05` problem pack, the solve
  contract / metamorphic suite (`or_verify`), and the guardrail spine. The story *wants* concepts
  to travel from Session 1 to the Session 5 Arena.

- **Self-containment.** Each session is taught, run, and — where it has one — *deployed* on its
  own. A learner must be able to check out a single session and get a complete, reproducible,
  working environment without first building the previous four. This is not incidental to the
  material: Session 4 defines "deploy" as *"a merge to `main` that re-solves the canonical instance
  and regenerates the study artifact"* — inherently scoped to one study, not the whole tree — and
  Session 5 is *"one shared repo"* whose contributors each own a single directory behind a frozen
  interface. Both are sub-tree-scoped by construction.

We need a layout that honours both, is obvious from day one, and stays durable across the term as
the instructor evolves individual sessions.

## Decision

**Organize the repository as a monorepo of self-contained, per-session packages.**

1. **The session subfolder is the unit.** Each session lives under `sessions/NN-<slug>/` and is
   independently runnable, testable, and deployable. Each owns its own `pyproject.toml` + `uv.lock`
   (and `mise.toml` where a session needs a pinned toolchain), its own `pytest` suite, its own
   `README.md` runbook (how to set up and run *this* session, standalone), and — for sessions with
   a deploy story (notably 04 and 05) — its own deploy artifact and a **path-filtered** CI workflow
   scoped to that folder, so a change in one session deploys only that session's subtree.

2. **Inside a session, the taught course and the offline exercises are separate parts.** The cadence
   is biweekly, so every session has live, instructor-led material *and* self-paced work students do
   offline between meetings. Each session subfolder splits cleanly along that line:
   - **`cursus/`** — the taught part: lecture notes and the live demos the instructor drives in the room.
   - **`exercises/`** — the offline part: the pre-work, labs, and home exercises students do on their
     own (e.g. Session 1's spiral-setting `/ship` PR, Session 3's staged pre-work, Session 4's guided
     post-work AWS deploy).

   The boundary is load-bearing: a student works `exercises/` on their own time, and the instructor
   can revise a `cursus/` lecture without disturbing an exercise a cohort is part-way through.

3. **Continuity is copy-forward, not a live shared import.** The artifacts the narrative carries
   across sessions (the P-pack, the solve contract) are **owned per session**: a session begins
   from a pinned copy of the previous session's matured artifact and owns it thereafter. The
   *concepts* travel; the *code* is versioned into each session. This is what makes "check out any
   one session and it works" literally true, and it means evolving Session 4's contract can never
   silently rewrite Session 1's demo.

4. **The guardrail spine is the one deliberate repo-wide exception.** `.claude/hooks/guard-main.sh`,
   `.githooks/`, `.github/workflows/pr-only.yml`, `/ship`, and the `settings.json` deny-list are
   boundary/traceability **meta-infrastructure** that every session inherits — the narrative says
   students *"inherit all of this on day one and do not build it."* It lives at the repo root,
   governs every session's PRs and deploys, and is **never duplicated** into a session. It is not
   session content; it is the layer that makes per-session self-containment safe.

### Resulting structure

```
/                              # repo root = the shared guardrail spine (repo-wide)
  CLAUDE.md
  .claude/  .githooks/  .github/workflows/pr-only.yml   # inherited by all sessions
  docs/
    cursus-narrative.md
    cursus-key-technical-notions.md
    adr/                       # this decision and its successors
  sessions/
    01-fundamentals/           # self-contained: own uv env, tests, README
      cursus/                  #   taught part: lecture notes + live demos
      exercises/               #   offline part: pre-work, labs, home exercises
    02-research-agents/        # ... same cursus/ + exercises/ split inside each session
    03-coding-agents/
    04-deploying-code/         # + path-filtered deploy workflow
    05-arena/                  # "one shared repo" pattern, recursed: engine/ + policies/<name>/
```

## Consequences

**Positive**
- A learner can start at any session; each is reproducible in isolation from its own lockfile.
- "Deploy" means deploy *one subfolder* — path-filtered workflows make this the default, not a
  special case, and match the OR-specific definition of deploy in Session 4.
- Blast radius of any change is a single session; editing one cannot silently break another.
- Taught material and offline work evolve independently within a session — a lecture can be reworked
  in `cursus/` without disturbing an `exercises/` lab a cohort has in flight, and vice versa.
- The Session 5 Arena's "owned-directory-behind-a-frozen-interface" model is the same principle
  applied one level down — self-containment is consistent at both scales.

**Negative / costs (accepted)**
- The P-pack and `or_verify` are duplicated across sessions, with attendant drift risk. This is
  **intentional**: each copy is canonical *for the session that teaches it*, and divergence is
  allowed because each session pins exactly what it taught. A lightweight drift-report can flag
  copies that fell behind, but copies are never auto-synced.
- More lockfiles and more (smaller) CI workflows to maintain than a single shared environment.

**Neutral**
- Sessions may legitimately use different tool versions; the per-session lockfile is the record of
  what that session was taught against.

## Alternatives considered

1. **Shared core library (`or_core/`) imported by every session.** Maximally DRY. *Rejected:* it
   couples all sessions to one mutable codebase — a change to the contract retroactively alters
   earlier sessions' demos, "check out one session and it works" breaks, and per-subfolder deploy
   gets tangled. The narrative wants concepts to travel, not a single shared mutable package.

2. **Flat repo; sessions as docs only, no per-session code isolation.** *Rejected:* there is no
   "part of the project" to deploy, no reproducible per-session environment, and labs bleed into
   one another.

3. **Polyrepo — one Git repo per session.** *Rejected:* the guardrail spine and PR-only integrity
   layer are repo-wide and meant to be inherited on day one; the Arena is explicitly *one shared
   repo*; five repos fragments the single narrative and dilutes the `/ship` / protected-`main`
   muscle the whole course rests on.

## How this stays true

This is a **documented, durable convention reinforced by structure** — not a hard gate (per the
intent that it be *clear from the get-go* rather than *enforced*):

- Per-session lockfiles keep each environment reproducible standalone.
- Path-filtered workflows mean a session deploys only its own subtree.
- The repo-wide spine already enforces the PR-only integrity layer for every change, whatever
  session it touches.

New sessions follow the same shape. This ADR is the reference for that shape.
