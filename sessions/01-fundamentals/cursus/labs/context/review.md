# Context lab: review evidence

Agent review by the implementer, 2026-10-16. Reviewed file: `../context.html`,
111,162 bytes, sha256 `d8dc0bc8d21071ac25987af2c9bf5d591827c0b08233346734a3aed7ab741d2e`.
Any edit to the page invalidates this review; re-review and update the hash.

## Checks run

- `node tools/html-pages/check-page.mjs sessions/01-fundamentals/cursus/labs/context.html`:
  PASS, 70 of 70 checks. It covers offline `file://` loading, shared-asset hashes, axe, desktop
  1440×900, laptop 1280×720 and mobile 390×844 with no horizontal overflow, no-JS, reduced motion
  and print.
- `node tools/html-pages/tests/run-suite.mjs tools/html-pages/tests/context.test.mjs`: the
  locked suite, 10 tests, all passing. It covers D1–D5, A1, A2 and A3 (reduced motion at 390 px).
- The suite is registered in `setup/package.json` `scripts.test` and in the `suites` list of
  `tools/html-pages/tests/component-helpers.mjs`.
- `npm --prefix setup test` and `npm --prefix setup run check-repo` were run after the last edit.

## Model choices

- Everything is closed-form arithmetic over `CONFIG`. Nothing is random, so every load and reset
  gives identical numbers.
- **Panel 1** estimates tokens as ceil(characters ÷ `tokens.charsPerToken`). It shows two calls.
  - Call 1: input is system + tools + user; output is the tool call.
  - Call 2: input is the call 1 input + tool call + tool result; output is the reply.

  The example has 160 → 32 estimated tokens for call 1 and 270 → 48 for call 2.
- **Panel 2** sends I_t = P + U + (t − 1)(U + A) input tokens on turn t, with P = 4,000,
  U = 200 and A = 800.
  - With caching, turn 1 writes I_1. Turn t > 1 reads I_{t−1} and writes U + A.
  - Through turn 30 the request is 33,200 input tokens. The cumulative input is 561,000 tokens:
    527,800 read from cache and 33,200 written.
  - That costs $1.1220 without caching and $0.1358 with it.
  - Turn 1 costs more with caching ($0.0105 vs $0.0084), because the cache write is billed at
    1.25× the input price. From turn 2 on, the cached cumulative cost is lower.
- **Panel 3** follows the agreed rules.
  - Autocompact fires only when used > window − buffer (strictly greater). It then sets
    messages to min(messages, 6,000), after any action or a window switch.
  - `add-mcp` is one-shot, and its button disables itself until Reset.
  - `/clear` empties messages and keeps system, tools, MCP, memory and skills.
  - The subagent adds 200 + 1,500 tokens. A separate readout shows the 40,000 tokens of child
    investigation, which never enter the parent window.
- **No-JS copies.** The static numbers come from the page's own renderer at load and are written
  into the file: the badges, the call totals, the 30-row table, the turn-30 readout, the meter
  rows and bar, the sources table and a phone-width chart snapshot. The suite's no-JS test
  checks them against CONFIG.
- **Numeric literals.** Numeric literals ≥ 100 occur only inside `CONFIG` and the `chartLayout`
  geometry object. Percentages use `Intl.NumberFormat` percent style, and the meter's widths are
  `flex-grow` values.

## Screenshot review

Sources: the `check-page.mjs` screenshots, plus per-panel screenshots from a disposable
Playwright script kept outside the repository. That script shot each panel at the default
state and at a stress state: raw view, tokens chart, four `solver.log` reads (which trigger
autocompact on 200k), then the MCP server and a subagent.

- **Desktop 1440 and laptop 1280.**
  - Panel 1: the chat bubbles, and the six raw segments in order, each with a single badge.
  - Panel 2:
    - The formula and assumptions sit in a bordered block.
    - The six-value readout fits on one row.
    - The chart draws two series on one linear scale, solid for without caching or input and
      dashed for with caching or cache reads, labelled directly at the line ends.
    - In the tokens view the two line ends are too close for two labels. Only the solid line
      is labelled there; the legend under the chart names both styles. A first version placed
      the dashed label over the lines and was changed.
    - Tick labels use consistent decimals ($0.00 … $1.50).
  - Panel 3:
    - The eight hatched segments are contiguous. The table's swatches match the hatches.
    - After autocompact the status line reports it, and the child-context box appears after
      the subagent.
  - Sources table: an earlier version overflowed at 1440 because of long link texts. It now
    fits, using short source titles, one-line dates and names that break only at dots.
- **Mobile 390.**
  - Everything stacks into one column and the document does not overflow.
  - The chart redraws at the figure's real width with 12 px text. It thins the turn ticks to
    1, 10, 20, 30 and drops the in-chart labels in favour of the legend.
  - The meter table first scrolled sideways (its share column was cut off). Tighter mobile cell
    padding now makes it fit.
- **No-JS (1280).** Both the chat and raw views show. The predict answer shows, with its buttons
  disabled. The readout, the table, the meter and the sources are static and correct. The chart
  is a capped phone-width snapshot.
- **Print.** Light colours. Both panel 1 views, the predict answer, the full cost table (the
  details are opened), the meter table and the sources table print. The controls are hidden.
- **Reduced motion.** No transitions; the meter's 0.2 s `flex-grow` transition applies only
  under `prefers-reduced-motion: no-preference`.

## Plots and curves

The only plot is panel 2's chart of cumulative input tokens and cost. Both series are the
formula above evaluated at turns 1–30, with no fitted or measured curve. Its figcaption links
the pricing page and its as-of date. The page draws no recall, accuracy or latency curve.

Context rot appears only as a qualitative callout with no numbers. It cites
https://www.trychroma.com/research/context-rot (Chroma, Context rot, 2025-07-14) and
https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents (2025-09-29).
I re-read both on 2026-10-16:
- Chroma reports that "model performance degrades as input length increases, often in
  surprising and non-uniform ways".
- Anthropic says recall decreases as context grows, "a performance gradient rather than a hard
  cliff".

Neither gives one universal curve, so the lab shows none.

## Predict and reveal

The legend reads "Message 30 is as long as message 1. Why does it cost more?". The keyed choice
is that the harness re-sends the whole transcript, so turn 30's request carries messages 1–29 and
every earlier reply as input. The answer says the model keeps no memory between calls and is a
function of the context it receives, for a fixed model and settings. Caching bills the re-sent
prefix at the cache-read rate but does not remove it. The distractors are tokenization drift,
rising per-token price and output re-billing, and none of them is how the APIs bill.

## Per-constant source review

CONFIG dates every leaf 2026-10-11, the snapshot date of `demos/effort/prices.json`. I re-fetched
every source on 2026-10-16, and the documented values were unchanged.

- **Documented.**
  - https://platform.claude.com/docs/en/about-claude/pricing backs `pricing.input` (2),
    `pricing.cacheWrite5m` (2.5), `pricing.cacheRead` (0.1) and `units.tokensPerMTok`
    (1,000,000). The pricing table lists Claude Sonnet 5.5 at $2 / MTok input, $2.50 / MTok
    5-minute cache write, $4 / MTok 1-hour write and $0.10 / MTok cache hit. The page also says
    "On Claude Opus 5.5 and Claude Sonnet 5.5, a cache hit costs 5% of the standard input price".
    The values match `sessions/01-fundamentals/cursus/demos/effort/prices.json`.
  - https://platform.claude.com/docs/en/build-with-claude/context-windows backs
    `windows.standard` (200,000) and `windows.extended` (1,000,000). Claude Sonnet 5.5 and the
    other current models "have a 1M-token context window", and 1M is their default. Other models,
    including Claude Sonnet 4.5, have 200k.
  - The same page backs the panel 2 premise, "previous turns are preserved completely" as the
    conversation accumulates.
  - The Prompt caching docs (not a CONFIG source) give the formula's assumptions:
    - a 5-minute default TTL;
    - 512 tokens as the minimum cacheable length for Sonnet 5.5, so the 4,200-token first
      request qualifies.
- **Illustrative.** These sources back the idea, not the number.
  - Every `conversation`, `budget`, `actions` and `controls` leaf is illustrative, and so is
    `tokens.charsPerToken`.
  - https://platform.claude.com/docs/en/build-with-claude/context-windows: the conversation sizes
    `conversation.prefix`, `conversation.userMessage` and `conversation.reply`.
  - https://platform.claude.com/docs/en/build-with-claude/token-counting:
    `tokens.charsPerToken` (4). This is a rule of thumb; the page points to the token-counting
    endpoint for exact counts.
  - https://code.claude.com/docs/en/context-window: the meter categories and actions. The doc
    says its own visualization "uses representative numbers" and that `/context` gives the live
    breakdown by category. It also describes compaction, and a subagent that keeps large reads out
    of the parent context. This covers `budget.*`, `actions.testRun` and `actions.compactSummary`.
  - https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents: subagents
    "might explore extensively, using tens of thousands of tokens or more, but return only a
    condensed, distilled summary of its work (often 1,000-2,000 tokens)". This backs
    `actions.subagentSummary` (1,500), `actions.childInvestigation` (40,000) and
    `actions.subagentDispatch`. The same article frames just-in-time loading, which backs
    `actions.solverLog` as a cost.
  - https://github.com/GuilhemBusset/coding-agent-cursus/issues/34: the issue fixes the scenario:
    30 turns, and "the ~17k-token context bomb". This backs `actions.mcpServer` (17,000),
    `conversation.turns` and `controls.turnMin`, `controls.turnMax` and `controls.turnDefault`.
    - The MCP qualification is checked against https://code.claude.com/docs/en/costs: "MCP tool
      definitions are deferred by default, so only tool names and server instructions enter
      context until Claude uses a specific tool".
    - Panel 3 therefore labels the 17k action an upfront-loading scenario and names deferred tool
      loading and tool search.

## Command parity (Claude Code and Codex)

Checked on 2026-10-16.
- **Claude Code** (https://code.claude.com/docs/en/commands):
  - `/context` "Visualize current context usage as a colored grid";
  - `/compact [instructions]` "Free up context by summarizing the conversation so far";
  - `/clear` "Start a new conversation with empty context".
- **Codex** (https://developers.openai.com/codex/cli/slash-commands):
  - `/status` displays "session configuration and token usage", including the remaining context
    capacity;
  - `/compact` keeps "transcripts lean";
  - `/new` starts a new chat, and `/clear` also starts a new chat after clearing the terminal.

The design assumed `/new` as the Codex equivalent of `/clear`. The page names both, because
Codex's `/clear` exists too.
