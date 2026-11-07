# Mini homework · Weekly staffing

**The P01 loop, end to end, on a problem small enough to check by hand.**

You do this one in class, in the five steps you will repeat on P01 tonight: read, plan, build,
check, ship. The model is your agent's to write. Your job is the evidence: believe only what
the checker prints. It works the same in Claude Code and in Codex.

## Problem

A shop is open seven days a week and needs a minimum number of staff on duty each day, given in
`data/demand.csv`. Every employee works the same pattern: five consecutive days on, then two
days off, and the pattern wraps around the week, so a block that starts on Friday runs Friday,
Saturday, Sunday, Monday and Tuesday, then rests on Wednesday and Thursday. Decide how many
people start their block on each day of the week so that every day has at least its required
number of people on duty, using as few employees as possible in total (minimise the headcount).

## Data

`data/demand.csv` has a header `day,demand` and one row per day, Monday to Sunday:

| Day | Mon | Tue | Wed | Thu | Fri | Sat | Sun |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Demand | 8 | 7 | 8 | 9 | 8 | 5 | 6 |

The checker pins these values: if the file is edited, it reports `FAIL` with a `data:` line.

## What to do

Run every command from `sessions/01-fundamentals/` in your course checkout, as for P01.

### 1. Read

Read this file and `data/demand.csv` yourself before your agent does.

### 2. Plan

Start your agent in plan mode, so it cannot edit anything yet: `claude --permission-mode plan`
in Claude Code; in Codex, start `codex`, then type `/plan` and press Enter. Send this prompt:

```text
Plan only: do not create or edit any file yet. Read exercises/mini-homework/README.md. Propose a model for this problem using HiGHS through highspy: the decision variables and their type, the coverage constraint for each day including the wraparound, and the objective. Say how we will check the result without trusting the solver. Once I accept the plan, implement it in exercises/mini-homework/work/model.py, run it so that it writes exercises/mini-homework/solution.json, then run uv run python exercises/mini-homework/check.py and show its full output. If it prints FAIL, fix the model, never check.py or data/.
```

Review the plan before any code exists. Look for one integer variable per start day; for each
day, the start days that put someone on duty, wrapping around the week (work out Monday by
hand); the objective, the total headcount, minimised; and `check.py` as the check, not the
solver's status. If something is missing, say so and let the agent revise the plan.

### 3. Build

Accept the plan when the agent asks: a *Yes* option in Claude Code, *Yes, implement this plan* in
Codex. The agent then builds, runs the model and runs the checker, as the plan prompt asked. Read
each command before you approve it. If it does not ask, leave plan mode (Shift+Tab in Claude
Code, `/plan` again in Codex) and send:

```text
Implement the plan.
```

### 4. Check

What the agent reports is a claim. Run the evidence yourself, in a second terminal:

```sh
uv run python exercises/mini-homework/work/model.py
uv run python exercises/mini-homework/check.py
git status --short exercises/mini-homework
```

Done when the checker's first line is `PASS`, and `git status` lists only
`?? exercises/mini-homework/solution.json` and `?? exercises/mini-homework/work/`. A line with
`M` means the agent changed the checker or the data. On `FAIL`, give the failure line to your
agent: each line starts with the contract that broke.

### 5. Ship

In your agent, `/turn-in 01` in Claude Code or `$turn-in 01` in Codex. Without an agent, run
`bash scripts/turn-in.sh 01` from the repository root (in Git Bash on Windows).

The turn-in reruns this checker first, then P01's, which only warns until you solve P01. A
malformed `solution.json` or an edited `data/`, here or in P01, stops it. It then commits only
`sessions/01-fundamentals/exercises/` to your own branch, `homework/s01/<handle>`, and pushes
it, never to `main`. Homework branches are public. Tonight's P01 turn-in adds a commit to the
same branch.

Done early? Read [P01's statement](../homework-p01/PROBLEM.md): tonight's loop.

## Solution file

The model writes `solution.json` in this folder. It is a JSON object with exactly two keys:

- `"objective"`: the headcount your model reports.
- `"start"`: for each of the seven days, how many people start their five-day block that day.
  The keys must be exactly the day names used in `data/demand.csv`.

This example shows the shape only; replace the zeros with your own numbers:

```json
{
  "objective": 0,
  "start": {"Mon": 0, "Tue": 0, "Wed": 0, "Thu": 0, "Fri": 0, "Sat": 0, "Sun": 0}
}
```

The model lives in `work/`. Keep `check.py` as the only Python file at the top of this folder.

## Reading the checker

The checker uses only the Python standard library and never calls a solver, so
`python exercises/mini-homework/check.py` works too. To check another file, pass its path:
`uv run python exercises/mini-homework/check.py path/to/other.json`.

The first line is `PASS` or `FAIL`. Each problem found is then printed on its own line,
starting with the contract it breaks:

| Prefix | Meaning |
| --- | --- |
| `data:` | `data/demand.csv` no longer matches the instance |
| `format:` | the file is missing, not valid JSON, or has missing, extra or non-numeric entries |
| `feasibility:` | a start is negative, or a day has fewer people on duty than it needs |
| `integrality:` | a start is not a whole number |
| `objective:` | the reported objective differs from the headcount recomputed from `start` |
| `optimality:` | the recomputed headcount is not the known optimum |

Whenever the headcount can be recomputed, a summary follows: the recomputed headcount, the
LP-relaxation bound, the known optimum and the gap to the bound, as an absolute value and as a
percentage of the headcount. The exit code is 0 on `PASS` and 1 on `FAIL`.

## Bound and optimum

- LP-relaxation bound: `10.2` people. Each person covers five of the seven days and the daily
  demands add up to 51, so five times the headcount must be at least 51.
- Known optimum: `11` people. Your roster must reach it with whole numbers.

So the best possible result is a headcount of 11 and a gap of 0.8 people to the bound.
