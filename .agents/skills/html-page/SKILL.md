---
name: html-page
description: Create or restyle teaching HTML pages, presentations, exercises, reports, and interactive labs in this repository using its lean dark visual language. Use for repository HTML teaching material, not unrelated application UIs or HTML test fixtures.
---

# HTML page

Read and follow [`tools/html-pages/GUIDE.md`](../../../tools/html-pages/GUIDE.md) from the
repository root. It owns the workflow, design contract, source-content handling, and browser
review. Use its shared templates and tokens rather than inventing a new visual identity.

Find the repository root relative to this skill (three directories up), even when invoked
inside a session. Run the documented commands there. The output is viewable directly from
disk, offline; authoring dependencies must not become viewer requirements.

Create or edit the requested content, then run the file-based Playwright checker, inspect its
screenshots, and exercise task-specific interactions. A generated starter or a passing
generic checker alone does not complete the content task. Report any checks you could not run.

This wrapper is byte-identical in `.agents/skills/html-page/` and
`.claude/skills/html-page/`; the shared source of truth remains in `tools/html-pages/`.
