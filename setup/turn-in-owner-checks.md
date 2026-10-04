# Turn-in: the repo owner's live checks

The offline tests in `tests/turn_in/` cover the script, the rulesets, the skill copies and the
docs. Three things need the real GitHub repository and both agents, so the repo owner runs them
once after the turn-in PR is merged (see
[ADR 0009](../docs/adr/0009-homework-on-per-student-branches.md)).

## Before you start

- The turn-in PR is merged and your clone is on an up-to-date `main` (`git switch main && git pull`).
- The rulesets are applied: `bash setup/apply-ruleset.sh` reports both `pr-only-main` and
  `homework-branches`.
- `gh auth status` succeeds, and Claude Code and Codex are both installed and logged in.

Write down `<handle>` (`gh api user --jq .login`). The branch is `homework/s01/<handle>`.

## 1. Both agents push a sample homework

1. Add a sample file, for example `sessions/01-fundamentals/exercises/owner-check.txt` containing
   `first run`.
2. In Claude Code, run `/turn-in 01`. Record the branch URL it prints and the tip SHA:
   `git ls-remote origin refs/heads/homework/s01/<handle>`.
3. Change the sample file to `second run`. In Codex, run `$turn-in 01`. Record the new tip SHA.
4. Confirm the second run added a commit on top of the first, without rewriting it:
   `git fetch origin homework/s01/<handle>` and
   `git log --format='%H %P %s' -2 FETCH_HEAD` shows the Codex commit whose parent is the
   Claude Code commit, both titled `Turn in session 01 homework (<handle>)`.

## 2. A force-push is rejected by the ruleset

This is a deliberate probe that is expected to fail, not a bypass. Run it from a throwaway
branch so your submission stays intact:

```sh
git switch -c probe/force-push "homework/s01/<handle>"
git commit --amend -m "Force-push probe (must be rejected)"
git push --force origin "HEAD:refs/heads/homework/s01/<handle>"
```

Record GitHub's rejection. It must name the ruleset (for example `GH013: Repository rule
violations found for refs/heads/homework/s01/<handle>` with `Cannot force-push to this branch`
and the `homework-branches` ruleset). Then confirm the remote tip is still the SHA from step 1.3
(`git ls-remote origin refs/heads/homework/s01/<handle>`), and clean up locally:
`git switch main && git branch -D probe/force-push`.

## 3. Record the evidence

Comment on the turn-in issue with: the branch URL, the two SHAs (and that the second's parent is
the first), the rejection text, and the unchanged tip after the probe.

## PR disclosure: homework branches are public

Paste this paragraph into the turn-in PR, and get an explicit reply from the instructor
(repo owner) on the PR before closing that item:

> **Homework branches are public.** This repository is public, so every `homework/s<NN>/<handle>`
> branch that `/turn-in` or `$turn-in` pushes, and every student fork used by the fork fallback,
> is readable by anyone, including the student's GitHub handle and the full submission history.
> Please confirm this is acceptable for the course, or say if the pre-work page (#24) should
> warn students and offer an alternative (for example a private submissions repository).
