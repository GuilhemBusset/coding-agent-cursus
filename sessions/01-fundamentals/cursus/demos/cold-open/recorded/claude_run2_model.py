"""Workshop problem: weekly tables and chairs that maximise profit, solved with HiGHS."""

import sys

import highspy
import numpy as np

PRODUCTS = ["tables", "chairs"]
PROFIT = [40.0, 30.0]  # euros per piece

# workstation: (hours per table, hours per chair, hours available per week)
WORKSTATIONS = {
    "assembly": (1.0, 1.0, 40.0),
    "carpentry": (2.0, 1.0, 60.0),
    "finishing": (1.0, 3.0, 90.0),
}

BINDING_TOL = 1e-6


def fmt(x: float) -> str:
    return f"{x + 0.0:g}"  # + 0.0 turns -0.0 into 0.0


h = highspy.Highs()
h.setOptionValue("output_flag", False)

# Columns: quantity per week, x >= 0 and continuous (fractional plans are fine).
inf = highspy.kHighsInf
n = len(PRODUCTS)
h.addVars(n, np.zeros(n), np.full(n, inf))
h.changeColsCost(n, np.arange(n, dtype=np.int32), np.array(PROFIT))
h.changeObjectiveSense(highspy.ObjSense.kMaximize)

# Rows: hours used at each workstation <= hours available.
names = list(WORKSTATIONS)
hours = np.array([WORKSTATIONS[w][2] for w in names])
for w in names:
    per_table, per_chair, available = WORKSTATIONS[w]
    h.addRow(-inf, available, n, np.arange(n, dtype=np.int32), np.array([per_table, per_chair]))

h.run()

status = h.getModelStatus()
print(f"status: {h.modelStatusToString(status)}")
if status != highspy.HighsModelStatus.kOptimal:
    sys.exit(1)

sol = h.getSolution()
x = np.array(sol.col_value)
used = np.array(sol.row_value)
# HiGHS reports row duals as d(objective)/d(rhs) in the model's own sense, so for this
# maximisation they are already profit gained per extra hour: no flip needed.
shadow = np.array(sol.row_dual)

primal_obj = float(np.dot(PROFIT, x))
dual_obj = float(np.dot(hours, shadow))
binding = [w for w, avail, u in zip(names, hours, used) if avail - u < BINDING_TOL]

print(f"solution: {', '.join(f'{p}={fmt(v)}' for p, v in zip(PRODUCTS, x))}")
print(f"duals: {', '.join(f'{w}={fmt(d)}' for w, d in zip(names, shadow))}")
print(f"primal objective: {fmt(primal_obj)}")
print(f"dual objective: {fmt(dual_obj)}")
print(f"duality gap: {fmt(abs(primal_obj - dual_obj))}")
print(f"binding constraints: {', '.join(binding)}")
