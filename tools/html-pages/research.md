# Design and tooling research

Reviewed 2026-10-03. This is a repository-specific implementation, not a vendored third-party
skill. External tools and skills were studied, not installed globally.

## Source material

- `~/projects/jev_tutorial/presentation/system_one.html`: dark palette, editorial typography,
  optical-mark navigation, diagrams, thin borders, semantic teal/amber/coral, restrained motion.
  We adapt those choices, remove remote font dependencies, and replace fixed-canvas mobile
  scaling with real reflow. The secondary muted text is brighter for legibility.
- `~/projects/agentic-or-workshop/workshop/materials`: exercises, exact prompts, LP/MILP models,
  reports, architecture diagrams, context-budget labs, and service-backed demonstrations.
  These informed the reading/deck/lab shapes. Its Atom One Dark palette is not adopted because
  the requested visual reference is System One. Important model assumptions and partial-success
  qualifications must survive shortening.

Neither sibling checkout is needed to use the finished skill.

## Existing options

| Option | Findings and decision |
| --- | --- |
| [Anthropic frontend-design](https://github.com/anthropics/skills/blob/main/skills/frontend-design/SKILL.md) | Useful design judgment and critique; a fixed repository style still needs reusable tokens and templates. Its brief-first guidance supports following the user's visual reference. |
| [Anthropic web-artifacts-builder](https://github.com/anthropics/skills/blob/main/skills/web-artifacts-builder/SKILL.md) | React/Tailwind/shadcn bundling can produce a single HTML artifact, but adds machinery beyond these plain HTML teaching pages. Reserve for sufficiently complex requests. |
| [Anthropic webapp-testing](https://github.com/anthropics/skills/blob/main/skills/webapp-testing/SKILL.md) | Its static HTML example uses file URLs. We adopt actual-file testing with repeatable assertions rather than relying on a development server. |
| [Playwright](https://playwright.dev/docs/browsers) | Chosen project-local author dependency: predictable browser automation, screenshots and keyboard checks without altering either agent's MCP configuration. Installation and browser provisioning need network access; viewing does not. |
| [Playwright MCP](https://github.com/microsoft/playwright-mcp) | Useful exploratory tooling, but direct scripts give both agents the same reproducible tests. File URLs require `--allow-unrestricted-file-access`, which broadens filesystem access beyond workspace roots; no persistent browser service is needed here. |
| [Chrome DevTools MCP](https://github.com/ChromeDevTools/chrome-devtools-mcp) | Useful live browser debugging and performance analysis, but unnecessary for this file-based authoring and validation loop. |

The architecture separates maintained authoring assets from independently viewable output:
templates inline a snapshot of the theme and behavior. This follows this repository's
[session self-containment decision](../../docs/adr/0001-self-contained-per-session-subfolders.md)
and [thin per-agent wrappers](../../docs/adr/0003-ship-as-shared-skill-and-codex-convenience-layer.md).

Tests use actual file URLs because [JavaScript module loading](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Modules#other_differences_between_modules_and_classic_scripts)
can encounter CORS restrictions there. Runtime data stays embedded; no network-idle readiness
heuristic is necessary. [Playwright discourages that heuristic](https://playwright.dev/docs/api/class-page#page-wait-for-load-state)
for test readiness. Screenshot review remains necessary; browser assertions do not measure taste.
