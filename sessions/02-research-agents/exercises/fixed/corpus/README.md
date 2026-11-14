# Portable offline public corpus utilities

Uses Python 3.12's standard library only, already pinned by this session's setup.
From a fresh clone, follow the session setup instructions, then from the session:

```sh
uv sync --locked
uv run --locked python -m exercises.fixed.corpus.variants
uv run --locked pytest tests/labs/test_case_c_variants.py
```

Generation writes the three announced bundles under `exercises/cases/*/variants/`.
To inspect regeneration elsewhere without changing published assets:

```sh
uv run --locked python -m exercises.fixed.corpus.variants --out "path with spaces"
```

The output is an exercises-shaped tree. Each generated directory is a complete
case overlay: its contents replace `cases/<case-name>/` in a fresh run workspace.
Consequently `case.json.reference_path` keeps the existing contract's canonical
`cases/<case-name>/reference.json` shape. Relative source paths resolve inside that
overlay, not against another case or a base dossier. The generator does not launch
runs, mount overlays, inject faults, implement research tools or grade answers.

`provenance.json` records seed, base revision, method/source/passage/row/pair/
experiment/family mappings, source order and numeric transformations. The variants
prefix transformed source/run/family identities with `V<seed>-`, rename methods,
change timing/cost values and reorder source metadata without manufacturing new
independent support. A/B retain P01's half-hour assumptions and B's 60-second
threshold, correction and duplicate-report relationships. C retains its feasible
pair filter and missing uncertain-demand evidence while changing the result.

`audit.py` checks the supplied CSV's row IDs, unambiguous pair identities and
numeric data, and computes a worksheet. It is an asset utility, not the future
`check_table` research tool. The tests independently recompute using Decimal and
inspect primary notes rather than accepting generated reference values as an
oracle. They validate every generated case/reference/example against the existing
schemas, exercise boundary tolerances and reject broken spans/relationships.

No dependencies or OS installs were added. Paths, file encoding and CSV newlines
are explicit; utilities are portable Python. Validation here runs on this Linux
host; it does not claim actual macOS or Windows execution.
