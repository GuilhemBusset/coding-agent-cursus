Answer the public dossier question using only evidence available in this run.
The starting scope source is EV-S01. If read is available, read it first. If
search is available, use it to find further relevant passages, then read sources
you choose from the results. Do not infer method details from titles alone.
State missing evidence honestly. A model-only answer may be incomplete or may
already be correct; never fabricate a failure to demonstrate a tool's value.

Return one JSON object, without Markdown fences, with keys claims, claim_anchors
and markdown. Follow the supplied claims/report schemas for claim objects and
anchors. Include an HTML anchor before each claim's prose in markdown. Use exact
source offsets for supported factual claims. Use kind uncertainty with
support_status unknown and empty evidence for unresolved findings. Reference
fact IDs are optional labels, not evidence. Do not output file envelopes such as
run_id; the supplied launcher adds them and grades the saved result afterwards.
