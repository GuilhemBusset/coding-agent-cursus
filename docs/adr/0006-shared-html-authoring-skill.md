# ADR 0006 — Shared HTML authoring assets, self-contained output

- **Status:** Accepted
- **Date:** 2026-10-03
- **Context:** [ADR 0001](0001-self-contained-per-session-subfolders.md), [ADR 0003](0003-ship-as-shared-skill-and-codex-convenience-layer.md)

## Context

Teaching pages need one lean dark visual language across Claude Code and Codex. They are
presented by opening checked-in HTML directly, including offline. Runtime imports from a
root theme would break the session self-containment required by ADR 0001.

## Decision

Keep byte-identical `html-page` skill wrappers in each harness's native directory and one
shared guide, theme, runtime and set of templates under `tools/html-pages/`. This extends
the repo-wide authoring infrastructure beyond the guardrail exception in ADR 0001, without
adding runtime dependencies to session content.

A generator embeds theme and behavior snapshots into each new HTML file, records SHA-256
asset provenance in metadata, and refuses to overwrite existing files. Pages own those
snapshots thereafter. Updates are explicit, scoped to the requested page or session, and
reviewed like other copy-forward artifacts. The sibling reference repositories are research
inputs only; neither is required to use the skill.

Setup scripts, diagnostics, dependency manifests and lockfiles live under `setup/`, alongside
git-hook activation and GitHub ruleset setup. Authoring tools import the locked browser
environment through `tools/html-pages/browser.mjs`; installation is documented in `setup/README.md`.

Project-local, pinned Node/Playwright tooling checks actual file URLs with networking blocked.
Node and Chromium are author/CI dependencies only. Students need a browser. CI checks the
starters and teaching pages marked `data-design-system="cursus"`; screenshot inspection and
custom interaction review remain agent responsibilities. This does not add mandatory status
checks to the GitHub ruleset.

## Consequences

- No symlink or per-agent implementation drift; CI compares both wrappers.
- New pages share a template and semantic tokens without importing another session.
- Styling and behavior fixes are not automatically applied to historical pages; snapshot
  hashes identify their provenance and marked blocks support deliberate updates.
- Browser checks catch delivery and structural problems, but cannot guarantee factual
  accuracy, composition, or every possible lab behavior.
