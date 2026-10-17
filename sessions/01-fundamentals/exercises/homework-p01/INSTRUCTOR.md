# P01 take-home · instructor notes

This file is public, like the rest of the repository. It records where the instance comes from,
how it was revised, how the known optimum was obtained, and where the private reference model
lives. It deliberately does not describe the reference formulation.

## Provenance

The instance is ported from P01 of the 2025 workshop pack:
[agentic-or-workshop `exercise/problems/P01-ev-linehaul-charging`](https://github.com/GuilhemBusset/agentic-or-workshop/tree/main/exercise/problems/P01-ev-linehaul-charging),
at commit `28228a90eaacc35f82395a2b8ccef8d5a302c036`, under the MIT licence. The untouched
upstream files are archived in
[`tests/fixtures/p01_upstream/`](../../tests/fixtures/p01_upstream/), together with the
licence. `tests/test_p01_homework.py` pins them by SHA-256 over the raw bytes:

| Upstream file | SHA-256 |
| --- | --- |
| `LICENSE` (repository root) | `834c9a7d9ead7c08a7a2c9fde89a051b1f8ff89457dfd11dd1f1e4ed27bffa76` |
| `exercise-statement.md` | `deb2f28a5b7abc510805ea1718218eab4b7621cc6880bed859d26ae55305d290` |
| `data/deadhead_minutes.csv` | `85fa296ef8a6e9443f37f7b5bdf8a8419ca5d6febb3c46a192848680ff0d629b` |
| `data/depots.csv` | `529aa3af2f2c7a81824b6eb231e7145ab3d841942ab11246fe00eb57bf70a004` |
| `data/tariff_blocks.csv` | `ce6bfaf10d1679af2fbdd7e25ee7b980bf6fdae4bca4d6edc355cd104ad880fb` |
| `data/trips.csv` | `49961fac9e8c12797e6672156455fb21049eeb7006da4a85503fca384cfee866` |
| `data/vehicles.csv` | `4a09cd6d9f90fca02f243b51785c92f58aa2f0879d0ef9e7c788295bf0203102` |

The upstream pack had a statement and CSVs only, with no checker, tests or reference solution.
Its 180 legs and 36 trucks were also loose enough that every model found the same answer.

## Revisions

The revised instance in [`data/`](data/) keeps upstream IDs and values. These are the only
changes, and `test_provenance_archive_and_revision_rules` enforces them row by row:

| | Change |
| --- | --- |
| a | **Subset.** The 40 legs `T001, T005, T010, ..., T176` (upstream row `1 + floor(4.5 k)` for `k = 0..39`) are spread from 05:00 to 20:41 and start at all eight depots. The 10 trucks `B001` to `B010` include `B009`, which has the 11:30-13:00 maintenance window. |
| b | `vehicles.csv`: `home_depot` changes from upstream `D1..D8` to the depot names `D_A..D_H`, through upstream `depots.csv`. |
| c | `depots.csv`: the `depot_id` column (`D1..D8`) is dropped, and `depot` is the only key. |
| d | `tariff_blocks.csv`: the inclusive ends (`02:59`, ..., `23:59`) become half-open slot-aligned ends (`03:00`, ..., `24:00`). |
| e | **Tightened capacity** (these values only go down). Every truck has `max_soc_kwh` 230 (upstream 399 or 437) and `initial_soc_kwh` 160 (upstream 252 to 345). The charger counts are below. |
| f | Upstream `T180` has the invalid origin `D_X`. It is not in the subset, so no repair was needed. If a later revision keeps it, the origin becomes `D_D`, from the eight-trip origin cycle. |
| g | New `parameters.csv`: `deadhead_cost_per_minute` = 1.0 and `degradation_cost_per_kwh` = 0.04. Upstream named both costs without values. |

| Depot | Upstream slow / fast | Revised slow / fast |
| --- | --- | --- |
| `D_A` | 3 / 2 | 1 / 1 |
| `D_B` | 4 / 3 | 0 / 1 |
| `D_C` | 5 / 1 | 1 / 0 |
| `D_D` | 2 / 2 | 0 / 1 |
| `D_E` | 3 / 3 | 1 / 1 |
| `D_F` | 4 / 1 | 0 / 1 |
| `D_G` | 5 / 2 | 1 / 0 |
| `D_H` | 2 / 3 | 0 / 1 |

`D_A` and `D_B` are each home to two trucks but have one fast charger, and `D_C` and `D_G`
have none.

### Simplifications against the 2025 statement

[`PROBLEM.md`](PROBLEM.md) makes the loose upstream statement precise. These are choices, not
upstream facts:

- Repositioning is immediate: after a leg, a truck deadheads straight to its next origin, or
  home after its last leg. Where it charges therefore follows from the assignment.
- Charging uses fixed 30-minute slots on a grid from 00:00. A slot counts only if it lies
  wholly inside a wait, and it uses one charger, slow or fast.
- A truck ends the day at home with at least its initial SoC.
- Charging has no efficiency loss, and `battery_kwh` and `service_km` are information only.
- The two cost rates in `parameters.csv` are new.

## Known optimum

`KNOWN_OPTIMUM = 835.52` in `p01_checker.py`. It was obtained as follows:

- **Solve.** The private reference model was solved with HiGHS 1.15.1 through `highspy`, with
  `threads=1` and `mip_rel_gap=0`. The model status is `kOptimal`, the primal and dual bounds
  are both 835.52, and the MIP gap is 0.
- **Plan.** The plan covers all 40 legs and cancels none. Its cost is 625.52 for energy and
  degradation plus 210.00 for deadheads.
- **Check.** The plan passes `p01_checker.py`, and the locked test oracle recomputes the same
  cost.

The solver-free tests also check that the value is finite, positive and below the all-cancel
cost of 108,520.

### Binding evidence

Both kinds of constraint bind. Removing either one gives a plan that is feasible for every
other contract and strictly cheaper. `test_variant_binding` re-solves both of these:

| Variant (seeded mistake) | HiGHS objective | Checker verdict |
| --- | --- | --- |
| reference | 835.52 | PASS |
| `dropped-charger-capacity`: no per-depot, per-slot, per-type count | 832.58 | FAIL, `charger-capacity` only |
| `dropped-charging-window`: a slot only has to overlap the wait | 826.28 | FAIL, `charging-window` only |
| `relaxed-binary`: assignment and charger-use variables continuous | 824.48 (LP) | FAIL, `integrality` (71 fractional values) |

The revisions are also what makes the limits bind. These are reference solves while tuning,
not part of the locked checks:

| Instance | Optimum |
| --- | --- |
| revised (this pack) | 835.52 |
| revised, but with upstream `max_soc_kwh` and `initial_soc_kwh` | 755.70 |
| revised, but with upstream charger counts | 832.58 |

## Solve time

The issue asks for two things: instance sizing so that HiGHS needs 5 to 60 seconds (D1), and a
reference solve under 60 seconds on a laptop (A2). `test_reference_solve_time` runs three
fresh-process solves. It times only `highs.run()` (the model reports it as `solve_seconds`,
taken from `getRunTime()`) and asserts that each is in `[5, 60)`. The test cannot tell what kind
of machine it runs on, so a pass proves the sizing on that host and nothing about laptops.
`test_laptop_benchmark` is the separate A2 procedure below: the same three fresh solves, an
upper bound only, and a printed evidence line for the laptop table.

### Sizing measurement (D1), on the instructor's desktop

Measured on 2026-10-10:

| Run | Status | Primal = dual | HiGHS `solve_seconds` | End-to-end wall (load, build, solve, write) |
| --- | --- | --- | --- | --- |
| 1 | `kOptimal`, gap 0 | 835.52 | 12.41 s | 12.53 s |
| 2 | `kOptimal`, gap 0 | 835.52 | 12.41 s | 12.56 s |
| 3 | `kOptimal`, gap 0 | 835.52 | 12.39 s | 12.54 s |

Host: Intel Core Ultra 9 285K, 24 logical CPUs, 32,581,280 kB RAM, Ubuntu 26.04 LTS on WSL2 (`Linux-6.18.33.2-microsoft-standard-WSL2-x86_64-with-glibc2.43`), HiGHS 1.15.1, Python 3.12 in the locked session environment. The run is single-threaded and HiGHS is deterministic at a fixed thread
count, so repeated runs on one machine differ only by machine load.

The host is the instructor's machine under WSL2, and WSL cannot read the chassis type. The
Intel Core Ultra 9 285K is a desktop-class part, so **this is not a laptop measurement**.

### Laptop benchmark (A2): outstanding owner obligation

**Status: not proven.** No laptop run has been recorded. A2 stays an open owner obligation
(ADR 0011, decision 1). It is not satisfied by the desktop run above, by the throttled-core
runs below, or by `test_reference_solve_time` or `test_laptop_benchmark` passing on that
desktop. The margin below makes a laptop pass likely, but likely is not measured. The issue
therefore ends as *delivered*, not *done*, until the table at the end of this section has a
laptop row that matches the current pins.

**Slowdown margin (supporting evidence, not a laptop run).** On 2026-10-10, on the same desktop,
`test_reference_solve_time` was run pinned to one core (`taskset -c 2`) while one or two busy-loop
processes shared that core. The solver then got about a half or a third of the core. HiGHS
`getRunTime()` measures wall-clock time, so the shared core shows in `solve_seconds`:

| Share of one desktop core | Run 1 | Run 2 | Run 3 | Under 60 s |
| --- | --- | --- | --- | --- |
| all (no competing process) | 12.39 s | 12.37 s | 12.35 s | yes |
| about 1/2 (one busy loop) | 25.07 s | 24.94 s | 25.13 s | yes |
| about 1/3 (two busy loops) | 38.01 s | 38.02 s | 37.98 s | yes |

Time scales linearly with the CPU share. A laptop core would need about a fifth of this desktop
core's single-thread throughput (12.4 s × 4.8 ≈ 60 s) to fail A2. The run time-shares a fast
core, so it does not model a laptop's smaller caches, lower memory bandwidth or thermal
throttling. That is why it does not close A2.

To close A2, on a laptop (Linux, macOS or Windows) with the private reference installed (see
[The private reference](#the-private-reference); on Windows, or anywhere the reference is not at
the default path, set `P01_REFERENCE_DIR` to its directory):

1. Clone the repository, run `setup/` as for a fresh clone, and `cd sessions/01-fundamentals`.
2. Plug the laptop in and leave its power profile on the default.
3. Run `uv run pytest -q -s tests/instructor_p01_reference.py -k laptop_benchmark`. It runs
   three fresh single-thread solves of the reference. Each must reach `kOptimal` with a closed
   gap, pass `p01_checker.py` with exit 0, and report `solve_seconds` under 60. There is no lower
   bound, unlike the D1 sizing test. On success it prints one JSON evidence line: the host's
   CPU, logical CPUs, RAM and OS (best effort; `unknown` where the platform does not say), the
   Python and HiGHS versions, the checkout revision, the SHA-256 of the reference and of each
   `data/*.csv` (CRLF normalised to LF, as the checker pins them), and each run's
   `solve_seconds`, wall seconds, status, primal, dual and gap.
4. Add a row to the table below and paste the full evidence line under it. Record the laptop's
   manufacturer and model and its power profile by hand: the test cannot tell a laptop from a
   desktop. Land that change through a PR.

A row counts only if its reference SHA-256 equals the pin in
[The private reference](#the-private-reference) and its data digests equal `DATA_SHA256` in
`p01_checker.py` at that revision. A row that does not match the current pins is history, not
evidence. A2 stays unproven until a matching row exists.

| Date | Laptop manufacturer / model | CPU | RAM | OS | Power profile | Checkout revision | Reference SHA-256 | Data digests | HiGHS | Run 1 | Run 2 | Run 3 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| _not yet run_ | | | | | | | | | | | | |

Evidence lines (one per row, as printed):

```text
(none yet)
```

If any run reaches 60 s, A2 fails. In that case, shrink the instance (fewer legs or trucks) and
re-derive `KNOWN_OPTIMUM`, `DATA_SHA256` and the binding evidence. Do not raise the limit.

## The private reference

The reference model is not in this repository, because the repository and every homework branch
are public. It is a drop-in `p01_model.py` with the student API and a module constant
`VARIANT = "none"` that selects the seeded mistakes above.

- **Location:** `~/.local/share/coding-agent-cursus/instructor/s01-p01/p01_model.py`. Set
  `P01_REFERENCE_DIR` to use another directory. The same directory holds `make_instance.py` and
  `instance-config.json`, which regenerate `data/` from the upstream archive.
- **SHA-256 of the reference:** `e7580af9279d40c666a855760570909a3043a60383a9c2dcb5ceaab8544cc88e`.
  The instructor check fails if the file is missing or its hash differs.
- **Backup:** keep a copy of the whole directory in a private repository you control, for example
  `gh repo create <you>/cursus-instructor --private`. Never use a public or secret gist, because
  secret gists are only unlisted. This PR does not create that backup. Make it once, by hand.
- **Release after the deadline:** open a PR that copies the reference to
  `exercises/homework-p01/reference/p01_model.py`. The same PR must retire the release guard in
  `tests/test_p01_homework.py`, which asserts that no `p01_model.py` in the pack contains a
  formulation.

## Instructor checks

From `sessions/01-fundamentals/`:

```sh
uv run pytest -q tests/test_p01_homework.py          # solver-free: data, checker, starter, turn-in
uv run pytest -q tests/instructor_p01_reference.py   # needs the private reference; a few minutes
```

`tests/instructor_p01_reference.py` is not collected by a plain `uv run pytest`. It fails rather
than skips when the reference is missing. It copies the pack to a temporary directory and swaps
the reference in there, then runs the model, the checker and `p01_contract.py` as subprocesses.

## Grading notes

- **Source of truth.** Grade by rerunning `main`'s `p01_checker.py` and `data/` on the turned-in
  `solution.json`, and read the diff of `p01_model.py`. Copies on a homework branch are not
  trusted.
- **Weighting.** A checker-proven feasible plan counts for more than the objective value.
- **What the checker cannot see.** It cannot tell a model's plan from a hard-coded one, or from a
  plan copied from another student's public homework branch. Reading the model diff is what
  catches these. The homework sheet (#45) owns the grading rubric.
