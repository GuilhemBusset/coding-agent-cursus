# P00 · Fixed-charge transport

A small optimization repository. The tests can come out green while the model is
quietly wrong, so this lab is about checking what a solve means, not just running it.

## The problem

A company has 3 plants (`P1`, `P2`, `P3`) and 5 customers (`C1` to `C5`).

- Each plant has a **capacity** (units it can ship in total) and a **fixed cost** paid only
  if it is opened. A closed plant ships nothing.
- Each customer has a **demand** that must be met exactly.
- Shipping one unit from plant `p` to customer `c` costs `unit_cost[p, c]`.

Choose which plants to open and how much to ship on each route so that every demand is met at
minimum total cost (fixed costs plus shipping costs). This is the classic **fixed-charge
transportation problem**, a mixed-integer linear program (MILP).

### Formulation

Decisions: `y[p]` in {0, 1} (open plant `p`) and `x[p, c] >= 0` (units shipped from `p` to `c`).

```text
minimize    sum_p fixed_cost[p] * y[p]  +  sum_{p,c} unit_cost[p, c] * x[p, c]
subject to  sum_p x[p, c] = demand[c]              for every customer c
            sum_c x[p, c] <= capacity[p] * y[p]    for every plant p
            x[p, c] >= 0,  y[p] in {0, 1}
```

### Data

| File | Columns |
| --- | --- |
| `data/plants.csv` | `plant`, `capacity`, `fixed_cost` |
| `data/customers.csv` | `customer`, `demand` |
| `data/costs.csv` | `plant`, `customer`, `unit_cost` (one row per route, 15 rows) |

## The files

| File | Role |
| --- | --- |
| `p00_model.py` | The model: builds the MILP with HiGHS (`highspy`) and returns a solution. `python p00_model.py` prints it as JSON. |
| `p00_checker.py` | An independent checker: recomputes feasibility, integrality and the objective from a solution using only the standard library, with no solver. |
| `test_p00_contract.py` | The solve contract, as tests. |
| `data/` | The instance. |

A solution is a dictionary:

```python
{"status": "optimal" | "feasible" | "no_solution",
 "objective": 123.0,
 "open": {"P1": 1.0, ...},
 "flow": {"P1": {"C1": 20.0, ...}, ...}}
```

## The solve contract

The tests check four contracts, and every failure message starts with the one it broke:

- **status contract**: the solve status is in an accepted set (optimal, or feasible when a
  time limit stopped the solver with a solution in hand). A time-limit stop is never reported
  as a proven optimum, and a run with no solution is never accepted.
- **feasibility contract**: the independent checker finds every demand met, every plant within
  its capacity, only non-negative finite shipments, and an objective that matches the
  recomputed cost.
- **integrality contract**: every opening decision is 0 or 1, and rounding the openings
  changes neither feasibility nor cost.
- **objective contract**: the objective equals the known optimum, which the test file derives
  by hand and re-derives by enumeration, without a solver.

## Your task

1. Set up and run the tests:

   ```sh
   mise install && uv sync
   uv run pytest
   ```

   (Or `python -m pytest` in any Python 3.12 environment with `highspy`, `numpy` and `pytest`.)
2. If a test fails, read its message: it names the broken contract. Find the cause in
   `p00_model.py` and fix it there. The checker, the tests and the data are the contract, so
   leave them unchanged.
3. You are done when every test passes and you can explain, in one or two sentences, which
   contract was broken (if any) and why a solver alone did not tell you.
