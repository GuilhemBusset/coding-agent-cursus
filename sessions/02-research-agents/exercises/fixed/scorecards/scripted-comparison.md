# Scripted comparison result

Recorded with the documented compare command on 15 November 2026, Node 24.15.0,
Python 3.12.13 and the locked session dependencies. Exit status: **0**.
Evidence kind: **synthetic**; peer prose review: **pending**.

| Measurement | Baseline | Candidate |
| --- | --- | --- |
| Successful / scheduled attempts | 3 / 3 | 3 / 3 |
| A, B, C pass rates | 1, 1, 1 | 1, 1, 1 |
| Required facts | 35 / 35 | 35 / 35 |
| Model attempts / logical requests | 9 / 9 | 6 / 6 |
| Tool invocations | 3 | 3 |
| Total tokens, all attempts | 1,080 | 720 |
| Tokens per success | 360 | 240 |
| Usage, including cache fields | complete | complete |
| Completed stop reasons | 3 | 3 |

Machine recommendation: **retain**, provisional. Quality is preserved with fewer
measured tokens per successful attempt. Elapsed time is recorded in the scorecards
but never ranked. These scripted results establish neither live compatibility nor
classroom readiness, and they do not replace a peer prose audit.

Saved generated scorecards: [before](scripted-before.json), [after](scripted-after.json).
[Manual arithmetic and the failure/retry fixture](manual-calculation.md).

Regenerate full manifests, all attempts, traces, reports, grading, peer checklists,
and readable scorecards with the one command in
[the runbook](../../runs/README.md#compare-two-saved-versions). The generated
`exercises/runs/compare-scripted/` evidence is retained locally and ignored by git;
choose a new output directory for another run.
