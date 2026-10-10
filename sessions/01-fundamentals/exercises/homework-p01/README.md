# P01 take-home · EV linehaul charging

**Your task: drive your agent to build the model, then prove it with the checker.**

The labs used P00, which is small enough to check by hand. P01 is not. It is the scheduling and
charging problem in [`PROBLEM.md`](PROBLEM.md): 40 linehaul legs, 10 electric trucks and eight
depots with a few slow and fast chargers. The battery and charger limits are tight enough to
bind. HiGHS needs several seconds to prove a correct model optimal, and a plausible but wrong
model can look fine and still fail the checker. The story carries on in Sessions 3 and 5.

You work in Claude Code or Codex, whichever you have. The model is your agent's to write. Your
job is the discipline: state the contract, make the agent meet it, and believe only what the
independent checker certifies.

## What to do

Run every command from `sessions/01-fundamentals/` in your course checkout.

1. **Read [`PROBLEM.md`](PROBLEM.md)** and the CSVs in `data/`.
2. **Have your agent build `p01_model.py`.** Ask Claude Code or Codex to formulate PROBLEM.md as
   a MILP on HiGHS through `highspy`, keeping the API of the stub:
   - `DATA_DIR`;
   - `contract_status(model_status, has_solution)`, which returns `optimal`, `feasible` or
     `no_solution`;
   - `solve(data_dir=DATA_DIR, time_limit=120.0)`, which returns the solution object below;
   - a `__main__` block that writes `solution.json` next to the model.

   Use only `highspy` and the session's dependencies. Do not edit `data/`,
   `p01_checker.py` or `p01_contract.py`, because grading uses the copies on `main`.
3. **Solve:** `uv run python exercises/homework-p01/p01_model.py` writes
   `exercises/homework-p01/solution.json`.
4. **Prove it:**
   - `uv run python exercises/homework-p01/p01_checker.py` replays your plan with no solver and
     prints PASS or FAIL;
   - `uv run pytest exercises/homework-p01/p01_contract.py` runs the solve-contract suite, with
     one test per contract.

   When something fails, give the failure line to your agent. Each line starts with the contract
   that broke.
5. **Turn in:** `/turn-in 01` in Claude Code, `$turn-in 01` in Codex, or
   `scripts/turn-in.sh 01` from a terminal at the repository root. The turn-in first runs
   `exercises/turn-in-check.sh`, which runs the checker. A missing `solution.json` only warns.
   A malformed `solution.json` or an edited `data/` stops the turn-in, so you can fix it. An
   infeasible or suboptimal plan is reported and still turned in. Every run adds a commit to
   your homework branch, which is public.

`uv run pytest` on its own (the session suite) does not collect `p01_contract.py`. Name the file
explicitly, as above.

## Solution format

`solution.json` is one JSON object. The values below only illustrate the shape; they are not a
plan for this instance.

```json
{
  "status": "optimal",
  "objective": 1234.5,
  "assign": {"B001": {"T001": 1.0, "T019": 1.0}, "B002": {"T005": 1.0}},
  "cancel": {"T001": 0.0, "T005": 0.0, "T019": 0.0, "T010": 1.0},
  "charge": {"B001": [{"slot": "21:00", "charger": "fast", "kwh": 90.0}]},
  "solve_seconds": 12.3
}
```

| Field | Meaning |
| --- | --- |
| `status` | `optimal` (HiGHS proved it) or `feasible` (for example a time-limit stop with an incumbent). Anything else fails the `status` contract. |
| `objective` | The cost your model reports. The checker recomputes it from your decisions. |
| `assign` | `{vehicle_id: {trip_id: value}}`: 1 when that truck covers that leg. |
| `cancel` | `{trip_id: value}`: 1 when the leg is cancelled. |
| `charge` | `{vehicle_id: [{"slot", "charger", "kwh"}]}`: the slot start as `HH:MM` on the 30-minute grid, `slow` or `fast`, and the kWh received. The depot is not given, because it follows from the schedule. |
| `solve_seconds` | Optional, information only. Your solve time is not graded. |

A missing entry means 0. Write the raw solver values for `assign` and `cancel` without rounding
them, so the checker can see a fractional answer. Unknown IDs, non-numeric values (including
`NaN`, `Infinity`, `true` and strings) and extra keys in a charge entry are format errors.

## Reading the checker

The first line is `PASS` or `FAIL`. Each failure line starts with its contract, and a summary
follows with the recomputed objective, its breakdown, the known optimum and the gap.

| Contract | Fails when |
| --- | --- |
| `data` | a CSV in `data/` differs from the pinned instance (line endings do not matter) |
| `format` | the file is missing, is not JSON, or does not match the format above |
| `status` | the status is not `optimal` or `feasible` |
| `coverage` | a leg is not covered exactly once or cancelled |
| `integrality` | an assign or cancel value is not 0 or 1; the schedule checks are then skipped |
| `sequence` | a truck cannot reach a leg's origin in time, or cannot get home by 24:00 |
| `maintenance` | a truck drives or charges during its maintenance window |
| `charging-window` | a charge is off the slot grid, or in a slot the truck does not wait through |
| `charging-power` | a slot delivers more than `min(max_charge_kw, charger kW) x 0.5` kWh, or a negative amount |
| `charger-capacity` | more trucks charge on one charger type at one depot and slot than it has |
| `soc` | the SoC leaves `[min_soc_kwh, max_soc_kwh]`, or ends the day below `initial_soc_kwh` |
| `objective` | the reported objective differs from the recomputed cost by more than 1e-6 relative |
| `optimality` | a feasible plan costs more than the known optimum |

The checker exits with 0 for PASS, 1 when a contract fails, and 2 when nothing could be
checked (`data`, `format` or a bad argument). A feasible plan that costs less than the known
optimum passes, with a warning. If you get one, report it to the instructor.

## Grading

Grading reruns the checker and data from `main` on the `solution.json` you turned in, and reads
the diff of your `p01_model.py`. Copies of the checker, the data or the contract suite on your
homework branch are not trusted. A plan the checker proves feasible counts for more than its
objective value: a correct model stopped at a feasible incumbent beats a wrong model with a
lower number.

## Files

| File | Role |
| --- | --- |
| `PROBLEM.md` | Statement and data dictionary |
| `data/*.csv` | The instance (do not edit) |
| `p01_model.py` | Your model: an empty stub to start with |
| `p01_checker.py` | Independent checker, standard library only, no solver |
| `p01_contract.py` | Solve-contract suite, run by explicit path |
| `INSTRUCTOR.md` | Provenance, revisions and how the known optimum was obtained |
| `../turn-in-check.sh` | The session's turn-in gate (runs the checker with `--turn-in`) |
