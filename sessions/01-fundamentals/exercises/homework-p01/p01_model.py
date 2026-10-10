"""P01 model: EV linehaul scheduling and charging. This is yours to build.

Have your agent (Claude Code or Codex) turn PROBLEM.md into a MILP solved with HiGHS
through highspy, keeping the API below. `python p01_model.py` must write solution.json
in the format of README.md; then prove it with `uv run python p01_checker.py` and
`uv run pytest exercises/homework-p01/p01_contract.py` (from sessions/01-fundamentals).
"""

import json
from pathlib import Path


DATA_DIR = Path(__file__).parent / "data"


def contract_status(model_status, has_solution):
    """Translate a HiGHS model status into 'optimal', 'feasible' or 'no_solution'.

    A proven optimum is 'optimal'. A stop on the time limit with an incumbent is
    'feasible', never 'optimal'. No primal solution is 'no_solution', whatever the status.
    """
    raise NotImplementedError("p01_model.contract_status is empty: build it with your agent (README.md)")


def solve(data_dir=DATA_DIR, time_limit=120.0):
    """Solve the instance in data_dir and return a JSON-serialisable solution dict.

    The dict has status, objective, assign, cancel and charge (see README.md), and
    optionally solve_seconds.
    """
    raise NotImplementedError("p01_model.solve is empty: build the model with your agent (README.md)")


if __name__ == "__main__":
    solution = solve()
    Path(__file__).with_name("solution.json").write_text(json.dumps(solution, indent=1), encoding="utf-8")
    print(f"status {solution['status']}, objective {solution['objective']}; wrote solution.json")
