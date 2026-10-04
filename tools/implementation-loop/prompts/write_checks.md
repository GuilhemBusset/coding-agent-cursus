Write the acceptance checks for this issue, before any implementation exists. Another agent,
from a different vendor, will implement against them, and the engine will lock your files.

The agreed design:

<design>
{{design}}
</design>

Write files **only** at these paths: {{check_files}}. Anything else you write is discarded.
- Each `command` check in the design must exit 0 only when its ledger item holds. Use the test
  runner that fits the deliverable (pytest through uv for Python, node:test for the HTML
  tooling); make every test deterministic, offline, and independent of implementation details
  the issue does not specify (file names, function names, exact wording, hashes).
- Test the behaviour the issue asks for, including at least one case an implementation could
  not satisfy by hard-coding the obvious example.
- Do not write any implementation, fixtures beyond what the tests need, or configuration that
  changes how tests are collected.

{{feedback}}

Return {"files_written": [...], "note": "..."}.
