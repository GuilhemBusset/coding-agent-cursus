# HTML pages

Use this guide when creating or restyling repository teaching HTML. The skill wrappers in
`.agents/skills/html-page/` and `.claude/skills/html-page/` both load this file. The visual
source of truth is `assets/theme.css`; the templates demonstrate its components.

## Delivery and scope

- A viewer opens the HTML directly from the checkout. Default to one HTML file with inline
  CSS, classic JavaScript, data, and SVG. No server, build command, CDN, remote font, module
  import, runtime fetch, or installed package is needed to view it.
- Use relative links for bundled sources and assets. For an unbundled local source, cite its
  title in text; do not embed a machine-specific absolute path or `file:///home/...` link.
- Keep material in the appropriate `sessions/NN-*/cursus/` or `sessions/NN-*/exercises/` directory
  when a session exists; honor a requested destination. Otherwise use the current `docs/`
  organization rather than creating a new session package just for a page. Authoring tools stay here, but delivered
  pages must not import root tooling or another session. This follows ADR 0001.
- Embedded assets are versioned snapshots. Edit an existing page in place; never regenerate
  over authored content. For a style or behavior refresh, replace only its clearly marked
  shared style or script block after reviewing differences, then update its `cursus-*-sha256`
  metadata to the SHA-256 of the replacement asset. These hashes record asset provenance,
  not a requirement to use the newest version. Page-specific CSS belongs after the shared
  block and uses its variables. Do not silently refresh other sessions.
- The six core semantic colors are a compatibility contract checked independently of asset
  versions. If intentionally evolving that palette, add an accepted palette to the checker
  rather than replacing the old one and forcing historical pages to change. Snapshot hashes
  must match their embedded blocks; they are integrity checks, not signatures of authorship.
- If a requested live service is essential, provide a clearly labelled offline example and
  distinguish example data from live results. Agree on the changed delivery contract before
  introducing a server requirement; never simulate a successful service response.

## Workflow

1. Read the actual source material and nearby pages. Identify the audience, one main takeaway,
   and the interaction (if any) that helps explain it. Keep commands, contracts, units,
   constraints, and material qualifications accurate when shortening prose.
2. Choose a shape: `page` for an exercise, handout, comparison, or report; `deck` for a paced
   presentation; `lab` for a control that changes a visual or result. Avoid building a dashboard
   around a simple explanation. Read the chosen template and shared CSS before editing.
3. For a new file, scaffold from the repository root:

   ```sh
   node tools/html-pages/create-page.mjs --kind lab --title "Context is a budget" --out docs/context.html
   ```

   The destination must not exist. Replace the example body with the requested material;
   retain the design tokens and relevant behavior. Remove irrelevant sample sections and
   controls. A scaffold alone is not a finished response to a content request.
   For an existing page without these assets, preserve its content and behavior while adding
   the shared style and appropriate runtime. Set `<html data-design-system="cursus"
   data-page-kind="page">` (or `deck`/`lab`), document language, and viewport metadata. Use
   marked style/script blocks and provenance metadata as in the selected template.
4. Keep one dominant visual or argument per section. Implement only interactions with a
   teaching purpose. For a static comparison, a table may explain more than a toggle.
5. Validate the delivered file as described below, inspect the screenshots, fix problems,
   and report the path, viewing instructions, checks performed, and any remaining limits.

## Visual contract

The dark variant of `system_one.html` informed this system; future agents do not need that
external checkout. It uses green-gray paper and sheet surfaces, near-white text, fine rules,
teal for action, amber for alternatives or qualifications, and coral for failure.

- Reuse the palette, spacing, font roles, and components in `assets/theme.css`. Do not invent
  a new theme per page. Dark is the default regardless of the OS theme. Use semantic variables
  in SVG and canvas as well as CSS; never use status color as the only label.
- Large, tightly spaced sans-serif headings lead. System fonts keep viewing reliable offline;
  monospace is for code, labels, and numeric readouts. The reference's Bricolage Grotesque and
  JetBrains Mono are inspiration, not download requirements. Add fonts only as licensed local
  assets when specifically needed, with a tested fallback.
- Use open space, aligned columns, and thin separators. Panels group meaningful inputs/results;
  they are not wrappers around every sentence. Avoid decorative gradients, glass effects,
  gratuitous badges, and decorative motion. Keep corners restrained.
- Prefer a short heading, one sentence of orientation if needed, then the diagram, table,
  code, or exercise itself. Move derivations, instructor notes, and long logs into labelled
  `details`. Important assumptions and qualifications stay visible. Do not impose word caps
  on exact prompts, contracts, or formulas.
- On smaller screens, columns stack and text remains readable. Do not scale a desktop canvas
  down to fit a phone. Wide code, tables, or diagrams may scroll in a labelled local container;
  the document itself should not overflow horizontally. Long copy must grow or scroll, not clip.
  In paged decks, each slide must fit at desktop and laptop sizes without internal scrolling;
  split dense slides or put supporting detail in a linked reading page.

## Content and interaction patterns

| Material | Prefer |
| --- | --- |
| Process or architecture | Directly labelled HTML/SVG flow, with a text equivalent |
| Exercise or mathematical model | Givens, decisions, constraints, deliverable; semantic math or inline SVG with accessible text |
| Prompt or shell contract | Exact selectable `pre`/`code`; optional details for long output |
| Comparison or measured report | Semantic table with headers; visible units, source and qualifications |
| Simulation | One labelled control, synchronized diagram/readout, deterministic reset |
| Instructor presentation | One claim and dominant visual per slide; visible navigation and slide count |

Mark invented numbers as illustrative. Preserve distinctions such as measured versus estimated,
LP versus MILP, infeasible versus failed, and shipping cost versus total objective. A reduced
test scope must not become an unqualified “passed.” Link source evidence without making viewing
depend on reaching that source.

For canvas diagrams, read colors from `getComputedStyle(document.documentElement)` and repaint
on print-media changes, or provide an HTML/SVG print equivalent. CSS variables alone cannot
recolor pixels already drawn into a canvas.

Use native buttons, ranges, selects and disclosures. Keep focus visible and targets comfortably
clickable (about 44px). Keyboard navigation must not hijack sliders, form fields, or buttons.
Update textual readouts with visual state, and provide reset when state changes. Keep transitions
short (roughly 150–250ms) and disable nonessential movement for `prefers-reduced-motion`.

Decks use the starter's `data-slide`/navigation contract and unique section IDs. Desktop navigation
supports hash links and browser history; narrow or short windows show a readable continuous page.
Without JavaScript, the content stays visible. Print reveals all slides and disclosure content.
Other labs may use their own behavior; do not retain the starter budget demo's markers on
unrelated controls.

## Browser validation

Follow [`setup/README.md`](../../setup/README.md) for installation, the complete dependency
inventory, and diagnostics. The pinned authoring environment lives under `setup/`.

If dependencies are absent, perform the documented setup as part of the requested authoring
work using the environment's normal permission mechanism. Keep OS-level installs explicit;
do not silently elevate routine skill execution or bypass a rejected installation.

From the repository root:

```sh
node tools/html-pages/check-page.mjs docs/context.html
```

Read `report.json` and open the generated PNGs in the reported output directory. The checker
uses Chromium with external requests blocked and opens `file://` at desktop, laptop, and mobile
sizes. It checks generic delivery/accessibility issues plus the starter's deck and lab behavior.
It cannot prove factual accuracy, good composition, or arbitrary custom interactions.

Before calling the page finished:

- Inspect every slide and the whole page at presentation size and mobile; check hierarchy,
  copy density, label sizes, collisions, awkward empty space, and figure/text contrast.
- Exercise every custom control with pointer and keyboard, including limits and reset. Add a
  small page-specific Playwright check when generic checks cannot establish correct state.
  During authoring put disposable checks under `tools/html-pages/`, import browser tools
  from `./browser.mjs`, and remove the checks after use. Keep reusable checks in
  `tools/html-pages/tests/`, naming the target page; use `pathToFileURL` to open its actual file.
  Such checks are authoring infrastructure, not runtime imports in a session.
- Verify no-JavaScript reading, reduced motion, and print behavior. Check meaningful formulas,
  tables and diagrams at the intended projector size, not just in a tiny screenshot.
- Re-run checks after fixes. If browser execution is blocked, state exactly what was not
  verified; do not claim a visual or interaction pass from source inspection.

The generic checker is an acceptance aid, not an automatic guarantee of visual consistency.
When updating these tools, run `npm --prefix setup test` to exercise all three starters.
CI also checks opted-in teaching files under `docs/` and `sessions/` via
`npm --prefix setup run check-repo`; a `data-design-system="cursus"` marker opts a page in.
Unrelated application interfaces and test fixtures are outside this check. These CI jobs do
not alter the repository's GitHub ruleset or claim to be required branch-protection checks.

## Research

Read [research.md](research.md) only when evaluating a different tool or changing this design
system. It records the source references and why we chose direct Playwright for offline HTML.
