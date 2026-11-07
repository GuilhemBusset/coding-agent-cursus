# ADR 0016 — Install and configure the Python editor with the project

- **Status:** Accepted
- **Date:** 2026-11-07
- **Context:** [ADR 0001](0001-self-contained-per-session-subfolders.md),
  [ADR 0014](0014-type-checking-with-ty.md), [ADR 0015](0015-student-setup-one-command-per-platform.md)

## Context

A fresh session installation had no editor configuration and did not install ty. VS Code used
Pylance, so its diagnostics differed from CI's ty checks. Manually installing ty did not last:
a plain `uv sync` removed the non-default typecheck group. Instructions with absolute paths
fixed one checkout but did not travel with a fresh clone or exported lab.

ty's language server currently creates one project per workspace folder. The repository's
`ty.toml` excludes session code, so opening only the repository root can suppress session
diagnostics even when the correct interpreter is selected. VS Code's `ty.path` and
`python.languageServer` settings have window scope and need workspace-level values in a
multi-root workspace.

## Decision

1. Sessions make `typecheck` a uv default group. Runtime dependencies stay in `[project]`;
   fixtures and parallel test runners remain opt-in. A normal install provides the pinned
   checker and later syncs retain it.
2. Each ty configuration explicitly names its project-relative Python environment. Editor
   diagnostics use the same dependencies as CI regardless of an old interpreter selection.
3. Check in portable `.vscode` settings and extension recommendations. ty supplies Python
   language features and diagnostics; the Python extension supplies execution and debugging.
   Executable candidates cover both Unix and Windows, without machine-specific paths.
4. `setup/cursus.code-workspace` gives the repository and every session separate workspace
   folders. Its window settings choose the pinned repository ty, while project configurations
   resolve each folder's imports. A session also works as a standalone workspace folder.
5. The existing preparation step syncs repository tools as well as sessions, then invokes
   `setup/editor.py`. The helper uses the supported VS Code CLI to install and verify pinned
   extension releases from `setup/editor.json`, including the Python extension's automatically
   installed Pylance, debugpy and Python Environments pack members. Pylance is inactive in this
   workspace. Repetition avoids reinstalling matching
   versions. It never edits user settings or trust decisions. No editor CLI is an explicit
   skip; a detected CLI failing to install is a setup failure with a retry command.
6. P00 exports carry the session settings, default group, installer and extension pins. Their
   installation works outside the course checkout and does not consult its parent folders.

## Consequences

Normal setup configures Python editing without personal settings or a separate unpinned checker.
Opening the checked-in course workspace, or a session/export folder, remains the user's choice;
VS Code's normal trust prompt applies. A window already open during setup may need a reload.
VS Code remains optional, and macOS users need its `code` CLI on PATH for automatic extension
installation. WSL uses the normal `code` routing through Remote - WSL.

Regression checks exercise default sync, actual language-server diagnostics and package
resolution in separate workspace folders, extension installation/repetition/failure, and the
standalone export. New sessions must add themselves to the course workspace.

References: [ty editor integration](https://docs.astral.sh/ty/editors/),
[VS Code extension CLI](https://code.visualstudio.com/docs/configure/command-line#_working-with-extensions),
[ty server project routing](https://github.com/astral-sh/ruff/blob/main/crates/ty_server/src/session.rs).
