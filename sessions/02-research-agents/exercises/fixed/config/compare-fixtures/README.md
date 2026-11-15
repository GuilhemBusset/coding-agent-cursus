# Public synthetic comparison inputs

`baseline/` and `candidate/` are saved versions produced by `snapshot.save`, with
verified `snapshot.json` manifests. Their prompts are identical. Their harnesses
consume JSON model output through the actual Pi boundary and execute a corpus
search; baseline additionally makes one redundant model call. A carried file or
module state makes either harness fail. No candidate supplies its own scores.

`A.json`, `B.json`, `C.json` are public scripted Responses streams for the announced
seeded variants. They contain worked typed answers and evidence from the public
references, including explicit uncertainty. These are fixture answers, not model
research or completed teaching checkpoints. Compact JSON keeps the deliberately
conservative admission bound within the shared default budget. The third response
exists for baseline's redundant call; candidate consumes only the first two.
The runner independently grades the actual output against verified rating support.

`aggregate.v1.json` is a separate hand-calculated aggregation fixture: successful
and failed quality attempts, with raw trace events including a metered service
failure and retry. Its inputs, arithmetic and expected totals are explained in
[`../../scorecards/manual-calculation.md`](../../scorecards/manual-calculation.md).
It is not a class or submission schedule and does not claim live evidence.

Run the single command in [`../../../runs/README.md`](../../../runs/README.md#compare-two-saved-versions)
from the session directory. No API key is needed. `compare.scripted.v1.json` uses
relative paths resolved from its own directory, the existing public offline rating
export, shared `run.v1.json` settings and the published class schedule.
