---
name: turn-in
description: Turn in a session's homework by pushing it to the student's own branch homework/s<NN>/<handle>. Invoke explicitly with /turn-in <NN> (Claude Code) or $turn-in <NN> (Codex) when the student wants to submit the homework of session NN. Do not invoke implicitly.
compatibility: Requires git and an authenticated GitHub CLI (gh)
disable-model-invocation: true
allowed-tools: Bash, Read
---

# turn-in — push a session's homework to your own branch

You are turning in the homework of one session. Goal: the student's work under `sessions/<NN>-*/exercises/` lands as a new commit on their own branch `homework/s<NN>/<handle>` in the course repo (or their fork). Homework never goes to `main` and never through a PR.

The deterministic mechanics (resolve the GitHub handle, switch to the homework branch, stage only the session's `exercises/` folder, run the session's own check, commit, push with retry, fall back to the student's fork) live in `scripts/turn-in.sh`, the single agent-independent source of truth, so this workflow is identical under Claude Code, Codex, or a bare terminal. This skill body is checked in byte-identically at `.agents/skills/turn-in/SKILL.md` (Codex and other Agent Skills consumers) and `.claude/skills/turn-in/SKILL.md` (Claude Code) — CI enforces the match. Implicit invocation is disabled in both harnesses: `disable-model-invocation` in the frontmatter for Claude Code, `policy.allow_implicit_invocation: false` in `agents/openai.yaml` for Codex. Invoke it as `/turn-in <NN>` in Claude Code or `$turn-in <NN>` in Codex, for example `/turn-in 01`.

## Session number

1. Take the two-digit session number `<NN>` from the invocation (for example `01`; turn `1` into `01`). If it is missing, ask the student which session they are turning in. Do not guess it from the files.

## Preflight

2. Confirm `gh` is authenticated (`gh auth status`); if not, tell the student to run `gh auth login`, then stop.
3. Show what will be submitted: `git status --short -- sessions/<NN>-*/exercises/`. Only that folder is ever committed; other changes stay in the working tree, untouched. Mention it if the folder has no changes: the run still records a new submission commit.

## Turn it in

4. Run `scripts/turn-in.sh <NN>` from the repository. It:
   - switches to `homework/s<NN>/<handle>` (a new branch starts from the course's default branch; an existing one only fast-forwards);
   - runs `sessions/<NN>-*/exercises/turn-in-check.sh` if the session has one, and stops if it fails;
   - commits only `sessions/<NN>-*/exercises/` with the message `Turn in session <NN> homework (<handle>)`;
   - pushes with retry, to the course repo or, without push access, to the student's fork.
5. Report the branch URL it prints. If it also prints a compare URL (fork fallback), report that too: it shows the submission against the course repo.

## When it refuses

6. If the script exits non-zero, STOP and show its message. Do not work around it. Typical refusals:
   - the session check failed: help fix the reported problem, then re-run;
   - switching would overwrite uncommitted changes: ask the student what to do with them;
   - the local and remote homework branches have diverged: ask before reconciling;
   - the current branch has commits that are not on the course's default branch, or the homework branch changes files outside `exercises/`: ask the student;
   - no fork or several forks were found: report it and ask.

## Hard rules

- Never run `git push --force`, `git commit --no-verify`, or push to `main`.
- Never stash, reset, rebase, or resolve conflicts on the student's behalf without asking.
- Never stage or commit files outside the session's `exercises/` folder.
- Homework branches are public, because the course repo is public.
