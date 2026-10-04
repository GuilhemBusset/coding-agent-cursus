Implement this issue in your working directory, following the agreed design.

<design>
{{design}}
</design>

- Change only these paths: {{files}}. The acceptance checks at {{check_files}} are locked:
  do not edit, move or delete them, and do not add test configuration (conftest.py,
  pytest.ini, [tool.pytest] settings) that changes how they run.
- Run the checks yourself until they pass:
{{commands}}
- HTML pages: use the repository's `html-page` skill (it points to
  tools/html-pages/GUIDE.md); scaffold with its templates and validate with its checker.
- Do not commit or push. Leave your changes in the working tree; they are kept whatever
  status you return.
- If a locked check is itself wrong (it contradicts the issue or another check, or no correct
  implementation can pass it), finish everything else, then return status "check_defect" with
  `defect_file` and a `defect_reproduction` someone else can run. An independent agent will try
  to reproduce it; if it does, the check is amended. Never weaken, skip or special-case a check
  to get green.
- If the design makes the issue impossible for another reason, return status "impossible" and
  say why; the design is redone with your note.

{{feedback}}

Return {"status": "done" | "check_defect" | "impossible", "note": "...", "defect_file": null, "defect_reproduction": null}.
