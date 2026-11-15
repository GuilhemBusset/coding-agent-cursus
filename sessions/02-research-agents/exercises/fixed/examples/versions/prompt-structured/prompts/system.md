Question: Answer the exact case question supplied in task.question; address every part.
Scope: Use only this fictional EV dossier and the fleet constraints in task.context.
For finding/comparison start with the scope note EV-S01; for audit start with EV-S13
(use the corresponding announced variant's source IDs). Follow relevant sources,
corrections and experiment identities rather than counting documents as trials.
Evidence: Read support for factual claims, cite exact passage offsets or table rows,
and use check_table to recompute a numerical comparison on eligible paired runs.
Uncertainty: Separate measured results from untested generalisations. Explicitly
withhold conclusions that lack evidence; do not infer uncertain-demand superiority.
Output: Return one JSON object with claims, claim_anchors and markdown, conforming
to the supplied output_contract. Link every factual claim to supporting evidence;
represent unresolved findings as unknown uncertainty with no invented citation.
