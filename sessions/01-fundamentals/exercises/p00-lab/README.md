# P00 lab · instructor notes

**Instructor material. Do not hand this file to students.** It names the bugs. Students get
an export (below), where [`PROBLEM.md`](PROBLEM.md) becomes the README and nothing names
the bug.

P00 is a fixed-charge transport MILP with 3 plants and 5 customers. It is small enough to solve
in milliseconds and to prove by hand. It is the running example for Session 1. The code can be
green while the model is silently wrong, and a solve contract is what catches it. The checker
and test pattern carry forward to the P01 take-home.

## Contents

| File | Role | Exported |
| --- | --- | --- |
| `PROBLEM.md` | Student-facing statement | yes, as `README.md` |
| `data/*.csv` | Instance: plants (capacity, fixed cost), customers (demand), 15 route costs | yes |
| `p00_model.py` | Reference model on HiGHS through `highspy`; `python p00_model.py` prints JSON | yes, patched for the chosen bug |
| `p00_checker.py` | Independent checker, standard library only, no solver | yes |
| `test_p00_contract.py` | Student solve-contract suite | yes |
| `export.py` | Builds a standalone student repo | no |
| `README.md` | These notes | no |

The export also gets the session's `pyproject.toml`, `uv.lock` and `mise.toml`, copied
byte-for-byte, plus a generated `AGENTS.md` (a task-scoped navigation rule), `CLAUDE.md`
(`@AGENTS.md`) and `.gitignore`. All of it is committed as a single `Initial commit` in a fresh
`git init`.

## Exporting a lab

From this directory, in the session environment (`uv run` from `sessions/01-fundamentals/`,
or any Python 3.12 with git on `PATH`):

```sh
python export.py --bug <name> --out <dir>
```

`<dir>` must be new or empty and outside this course checkout. `export.py` refuses anything
else and leaves the target untouched. Every variant has the same file names, the same
`AGENTS.md`, the same commit message and the same tests. Only `p00_model.py` differs, and it
carries no comment about the change.

| `--bug` | What changes in `p00_model.py` | Contract that fails | Result |
| --- | --- | --- | --- |
| `none` | nothing (reference) | none | 485, all tests pass |
| `flipped-sense` | objective sense `kMinimize` becomes `kMaximize` | objective | 1085, "optimal" |
| `dropped-demand` | the demand constraints skip the last customer (C5) | feasibility (also objective) | 425, looks *better* than 485 |
| `relaxed-binary` | `y` becomes continuous on [0, 1] (the LP relaxation) | integrality (also objective) | about 413.10, `y = (5/7, 2/3, 0.2)` |
| `timelimit-as-optimal` | `contract_status` reports a time-limit stop with a solution as `optimal` | status | 485 here; the mapping test catches it |

Each variant still reports status `optimal` from HiGHS, which is the point: the solver's own
status says nothing about whether the model is the right one. The last bug is invisible on
this instance, because HiGHS finishes in milliseconds. Only the status-mapping test, which
asks what a `kTimeLimit` stop would be reported as, exposes it.

### `--tests-dir`: the lab ladder layout

```sh
python export.py --tests-dir --bug <name> --out <dir>
```

The opt-in `--tests-dir` flag moves the unchanged contract suite to
`tests/test_p00_contract.py`, adds an empty `tests/__init__.py`, and makes the generated
`AGENTS.md` name `tests/` as part of the contract. Everything else is the same as above, and
without the flag the export is byte-for-byte what it was before. The
[lab ladder](../lab-ladder.html) uses this layout so that its L2 done check,
`git diff --stat -- tests/`, covers the whole test suite.

## Running the lab ladder

Students make their own exports from `sessions/01-fundamentals` in their course checkout:
`--bug none` into `p00-explore` for L1, and the variant you write on the board into `p00-fix`
for L2 (and again into `p00-headless` for the L4 headless option). The page never names a
variant; write one name on the board for the whole room just before L2.

- **Use `dropped-demand` or `relaxed-binary`.** Both fail visibly in `uv run pytest`, name a
  contract in their first failure message, and are fixed by one line in `p00_model.py`.
  The [rehearsal](../../cursus/labs/lab-ladder-rehearsal.md) used `dropped-demand`.
- **Avoid `flipped-sense` for L2.** L1 has just trained everyone's attention on where the
  objective sense is set, so the bug is found by memory, not by reading the failure.
- **Avoid `timelimit-as-optimal` for a first run.** Its only symptom is the status-mapping
  test, which is a good discussion but a poor 12-minute exercise.
- **The done commands do not rule out hard-coding.** The contract suite solves only the
  bundled instance, so a `p00_model.py` that returns a fixed optimal plan (keeping the real
  `contract_status`) passes `uv run pytest` and both Git checks. Read
  `git diff -- p00_model.py` to confirm the fix repairs the model.

## The known optimum, derived without a solver

Total demand is 20 + 30 + 25 + 15 + 10 = 100. No single plant (capacity 70, 60, 50) can cover
it, so at least two plants are open. For each remaining subset of plants, take the fixed costs
plus each customer's cheapest route among the open plants. This is a lower bound, because it
ignores capacity.

| Open | Fixed | Cheapest routes (C1..C5) | Lower bound |
| --- | --- | --- | --- |
| P1, P2 | 200 | 20·2 + 30·3 + 25·2 + 15·3 + 10·6 = 285 | **485** |
| P1, P3 | 250 | 20·2 + 30·3 + 25·5 + 15·5 + 10·2 = 350 | 600 |
| P2, P3 | 250 | 20·5 + 30·5 + 25·2 + 15·3 + 10·2 = 365 | 615 |
| P1, P2, P3 | 350 | 20·2 + 30·3 + 25·2 + 15·3 + 10·2 = 245 | 595 |

The smallest bound, 485, is attained. P1 ships C1 and C2 (50 ≤ 70) and P2 ships C3, C4 and
C5 (50 ≤ 60), which respects capacity, so 485 is optimal and it is the unique optimum.
Dropping C5's demand saves 10·6 = 60 and gives 425.

`test_p00_contract.py` hard-codes `KNOWN_OPTIMUM = 485.0` with this proof as a comment.
`test_known_optimum_by_enumeration` re-derives it from the CSVs in pure Python. The value
never comes from the reference solver's output.

## The solve-contract suite

`test_p00_contract.py` checks the following. Each failure message starts with the contract it
breaks.

- **status**: the status is in a whitelist `{optimal, feasible}`, never `== optimal`. A
  time-limit stop with a solution maps to `feasible`, and no solution is never accepted.
- **feasibility**: `p00_checker` recomputes demand, capacity × opening, sign and finiteness,
  and the objective from the decisions alone.
- **integrality**: openings are within tolerance of 0 or 1. Rounding them preserves
  feasibility and cost.
- **objective**: the reported objective is within tolerance of `KNOWN_OPTIMUM`.
- **checker unit tests**: hand-built plans show that the checker accepts the optimum and
  rejects an unserved customer, a fractional opening, non-finite values and malformed IDs.

It runs in well under a second once the dependencies are installed, and uses only open
solvers (`highspy`).

## Instructor checks

From `sessions/01-fundamentals/`:

```sh
uv run pytest exercises/p00-lab/test_p00_contract.py   # reference passes in place
uv run pytest tests/test_p00_lab.py                    # exports every variant and checks it
```

`tests/test_p00_lab.py` exports all five variants to a temporary directory. It checks that the
reference passes, that each bug fails its named contract in under 10 seconds, and that no
exported file or commit gives the bug away.
