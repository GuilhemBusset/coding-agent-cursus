# The workshop problem

A small furniture workshop makes **tables** and **chairs**. Every piece goes through three
workstations, and each workstation has a fixed number of hours available per week:

| Workstation | Hours per table | Hours per chair | Hours available per week |
| --- | --- | --- | --- |
| `assembly` | 1 | 1 | 40 |
| `carpentry` | 2 | 1 | 60 |
| `finishing` | 1 | 3 | 90 |

Each table sold earns a profit of 40 euros and each chair a profit of 30 euros. The workshop can
sell everything it makes, and it does not have to make any minimum number of either piece.

The plan is a weekly average over a season, so fractional quantities are fine (19.5 tables per
week is a valid plan).

**Question.** How many `tables` and `chairs` should the workshop make per week to maximise its
weekly profit, without using more hours than are available at any workstation?
