# Repository setup

This directory is the home for repository-wide installation scripts, dependency manifests,
diagnostics, and setup documentation. Run the commands below from the repository root.
Installation needs internet access; viewing generated HTML needs only a browser.

## Every clone: activate git hooks

Prerequisites: Git and Bash (Git Bash on Windows).

```sh
bash setup/git-hooks.sh
```

This sets the clone's `core.hooksPath` to `.githooks/`, activating the protected-main checks.
It is safe to repeat. Run it yourself once per clone; agents do not activate it automatically.

## HTML authors: install browser tooling

Install [Node.js](https://nodejs.org/en/download) 22 or newer, including npm, then run:

```sh
node setup/html-pages.mjs
```

On a fresh supported Linux machine, include Chromium's OS libraries (may prompt for sudo):

```sh
node setup/html-pages.mjs --with-system-deps
```

The installer runs `npm ci --include=dev` against this directory's lockfile, downloads the
browser revision required by that Playwright version, and verifies offline `file://` rendering.
It resolves paths from its own location, so it also works from another directory when invoked
by its full path. Re-run after the lockfile changes; repeating it is safe. It does not activate
git hooks or change GitHub settings.

If you lack privileges to install Linux packages, ask the machine administrator to install
Playwright's Chromium dependencies. Setup reports failure until Chromium can launch; there
is no dependency on temporary libraries from an author's machine. See
[Playwright's browser documentation](https://playwright.dev/docs/browsers) for supported
environments, browser caches, and proxy/download configuration.

Verify the installation without reinstalling, then run the HTML tooling tests:

```sh
node setup/doctor.mjs
npm --prefix setup test
```

Check existing Cursus teaching pages with `npm --prefix setup run check-repo`. CI is configured
to run this same setup and test sequence on Linux, macOS, and Windows.

## Claude Code and Codex

Use your installed, configured agent from the cloned repository. The repository supplies
`/html-page` and `/ship` through `.claude/skills/`, and `$html-page` and `$ship` through
`.agents/skills/`. No separate skill download or MCP registration is needed.

Skill wrappers and git hooks stay in their native discovery locations; this directory owns
their setup. Page authoring assets and checks live under `tools/html-pages/` and consume the
locked browser environment through `tools/html-pages/browser.mjs`.

## Repo administrators and fork owners: apply the ruleset

Prerequisites: Bash, GitHub CLI (`gh`) authenticated as a repository administrator, and `jq`.
Install those tools using your platform's package manager, and authenticate with `gh auth login`.
Then run once per repository or fork:

```sh
bash setup/apply-ruleset.sh
```

This creates or updates the GitHub ruleset from [`pr-only-main.json`](pr-only-main.json):
PR-only changes to the default branch, a passing `required` CI check before merge (see
[ADR 0007](../docs/adr/0007-required-ci-gate-and-merge-forward-shipping.md)), no force pushes,
no deletion, and no bypass. Rulesets
are server state, so cloning or forking alone does not apply them. Re-running the script updates
the matching ruleset. It requires admin access and is separate from local author setup.

## Installation inventory

| Component | Source and destination |
| --- | --- |
| Git/Bash; Node/npm for HTML authors; gh/jq for administrators | Contributor-installed prerequisites; no global package manager changes are made by default |
| Repository skills and HTML assets | Checked-in `.claude/skills/`, `.agents/skills/`, and `tools/html-pages/`; no global skill installation |
| Git hooks | Checked-in `.githooks/`; `git-hooks.sh` configures the clone's `.git/config` |
| Playwright, axe and transitive npm dependencies | Exact versions and integrity hashes in [`package-lock.json`](package-lock.json); installed in `setup/node_modules/` |
| Chromium, headless shell and FFmpeg | Downloaded by the locked Playwright CLI into its per-user browser cache; `doctor.mjs` prints the executable location |
| Linux browser libraries | OS packages installed only with `--with-system-deps`; versions come from the supported distribution's repositories |
| GitHub ruleset | [`pr-only-main.json`](pr-only-main.json); applied to the selected repository only when an administrator runs `apply-ruleset.sh` |
| MCP servers, third-party agent skills, global agent configuration | None installed or modified |

When adding another repository-wide tool, put its installer, manifests/lockfiles and diagnostic
entry points here, document its prerequisites and destinations in this inventory, and verify
the setup in a clean environment. Keep student-facing session runtime dependencies local to
their session, as required by [ADR 0001](../docs/adr/0001-self-contained-per-session-subfolders.md).
