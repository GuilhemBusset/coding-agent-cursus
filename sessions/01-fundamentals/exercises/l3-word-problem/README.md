# L3 · Weekly staffing, with a certificate

Build a small optimization model from a word problem, solve it, and prove the answer with a
checker that does not trust you or your agent. This exercise works the same in Claude Code and
in Codex: every command below is plain shell.

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

## Solution file

Write your answer to `solution.json` in this folder. It is a JSON object with exactly two keys:

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

Build your model wherever you like, for example in a `work/` subfolder of this folder. Keep
`check.py` as the only Python file at the top of this folder.

## Check

From this folder, run:

```sh
uv run python check.py
```

The checker uses only the Python standard library and never calls a solver, so
`python check.py` works too. To check another file, pass its path:
`uv run python check.py path/to/other.json`.

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

The `wrong/` folder holds three solutions the checker must reject. Run the checker on each one
(for example `python check.py wrong/understaffed.json`) to see what its messages look like.

## Done when

`uv run python check.py` prints `PASS` on your `solution.json`, and you report the gap to the
LP bound it prints. Back the claim with that output, not with what the solver or the agent said.
