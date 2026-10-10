"""Workshop problem: weekly tables and chairs that maximise profit, solved with HiGHS."""

import sys

import highspy

# Problem data (from problem.md).
PRODUCTS = ["tables", "chairs"]
PROFIT = [40.0, 30.0]  # euros per piece
WORKSTATIONS = ["assembly", "carpentry", "finishing"]
HOURS_PER_PIECE = [  # rows: workstations, columns: products
    [1.0, 1.0],
    [2.0, 1.0],
    [1.0, 3.0],
]
HOURS_AVAILABLE = [40.0, 60.0, 90.0]
BINDING_TOL = 1e-6

h = highspy.Highs()
h.setOptionValue("output_flag", False)

# One non-negative continuous column per product, with its profit as objective coefficient.
for profit in PROFIT:
    h.addVar(0.0, highspy.kHighsInf)
    h.changeColCost(h.getNumCol() - 1, profit)
h.changeObjectiveSense(highspy.ObjSense.kMaximize)

# One row per workstation: hours used <= hours available.
for coefs, hours in zip(HOURS_PER_PIECE, HOURS_AVAILABLE):
    h.addRow(-highspy.kHighsInf, hours, len(coefs), list(range(len(coefs))), coefs)

h.run()

status = h.getModelStatus()
print(f"status: {h.modelStatusToString(status)}")
if status != highspy.HighsModelStatus.kOptimal:
    sys.exit(1)

solution = h.getSolution()
col_value = list(solution.col_value)
row_value = list(solution.row_value)
# For a maximisation HiGHS already reports the dual of a binding <= row as non-negative
# (profit gained per extra hour), so the row duals are the shadow prices as they are.
shadow_price = list(solution.row_dual)

primal_objective = sum(p * x for p, x in zip(PROFIT, col_value))
dual_objective = sum(b * y for b, y in zip(HOURS_AVAILABLE, shadow_price))
duality_gap = abs(primal_objective - dual_objective)
binding = [
    name
    for name, hours, used in zip(WORKSTATIONS, HOURS_AVAILABLE, row_value)
    if hours - used < BINDING_TOL
]

print("solution: " + ", ".join(f"{n}={v:g}" for n, v in zip(PRODUCTS, col_value)))
print("duals: " + ", ".join(f"{n}={v:g}" for n, v in zip(WORKSTATIONS, shadow_price)))
print(f"primal objective: {primal_objective:g}")
print(f"dual objective: {dual_objective:g}")
print(f"duality gap: {duality_gap:g}")
print(f"binding constraints: {', '.join(binding)}")
