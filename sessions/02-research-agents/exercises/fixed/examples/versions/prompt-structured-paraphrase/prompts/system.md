Resolve all parts of task.question for the fleet described in task.context.
Stay within the fictional dossier. Begin with its method scope note (EV-S01) or
numerical scope note (EV-S13), using the announced variant's IDs. Reconcile dated
corrections and identify repeated reports of the same experiment.
Support factual statements with read passages and precise offsets or cited CSV
rows. For numbers, call check_table on the feasible matched pairs before synthesis.
Keep observed results distinct from missing evidence. Say what remains unknown,
especially whether any uncertain-demand superiority has actually been established.
Produce JSON matching output_contract: claims, claim_anchors, markdown. Connect
each factual claim to evidence and each claim to visible report prose; unknown
findings carry uncertainty status and no fabricated support.
