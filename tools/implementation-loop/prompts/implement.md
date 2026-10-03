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
- Do not commit or push. Leave your changes in the working tree.
- If the design or the checks make the issue impossible, stop and return status
  "impossible" with the reason. Never weaken, skip or special-case a check to get green.

{{feedback}}

Return {"status": "done" | "impossible", "note": "..."}.
