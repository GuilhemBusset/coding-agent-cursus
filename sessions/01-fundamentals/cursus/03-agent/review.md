# Act III deck: review evidence

Agent review by the implementer, 2026-10-18. Reviewed file: `../03-agent.html`,
94,895 bytes, sha256 `8f196a87837430044204cce9ba81bb39ffd8765fc8213bce4f32034c55b735be`.
Any edit to the deck invalidates this review; re-review and update the hash and byte size.

Every external source below was opened on 2026-10-18 while authoring. Each date comes from the
source itself: the arXiv submission line, a blog's date line, a page's "last updated" line, or a
page's `updated_time` metadata. Recorded numbers come from the committed recordings. Model ids are
copied from those recordings' meta, not typed from memory.

## Checks run

- `node tools/html-pages/check-page.mjs sessions/01-fundamentals/cursus/03-agent.html`: PASS,
  0 failed checks. That covers offline `file://`, the shared-asset hashes, axe, deck navigation,
  every slide fitting without internal scrolling at desktop 1440×900 and laptop 1280×720, no
  horizontal overflow at 390 px, no-JS, reduced motion and print.
- `uv run --locked pytest -q tests/test_agent_deck.py` in `sessions/01-fundamentals/`: 3 passed.
  - Every slide has one labelled speaker-notes block, and the minutes add up to 40.
  - Each demo and lab link sits on its slide.
  - Every relative link resolves to a file inside the session, every `#id` to an element of its
    target, and every `#run=` to a run inlined in the replay widget.
  - Every landscape slide shows an as-of date and an https source.
  - A mutation (a misspelled `#run=` id) makes the suite fail.
- `uv run --locked pytest -q tests/test_pages.py tests/test_self_contained.py`: passed. The deck
  carries the page markers, and no resource is remote or leaves the session.
- `npm --prefix setup run check-repo`: PASS, 19 pages. It ran one cosmetic edit before the final
  file, which only moved a chart label. `check-page.mjs` was rerun on the final file and passed.
- `node tools/html-pages/tests/run-suite.mjs tools/html-pages/tests/pages.test.mjs`: 9 passed.

## Screenshot review

I opened the check-page screenshots and looked at each one.

- **Laptop 1280×720, first pass:** five slides scrolled internally: `permissions-modes` by
  128 px, `time-horizons` 109, `ladder` 28, `benchmarks` 7 and `models` 4. Fixes:
  - shorter headings;
  - the demo-rights sentence moved to the notes;
  - one compact citation line for the docs table;
  - lower ladder steps;
  - the METR chart capped at 34rem on short screens.

  A disposable Playwright probe, deleted after use, measured every slide at 0 px overflow at
  1280×720 and 1440×900. It also measured `loop-demo` and `bomb-demo` with the recorded-results
  reveal open. Once the bets are in, the reveal replaces the predict prompt and runbook, as in
  Act II. The bomb reveal first overflowed by 25 px; the detail on what tool search defers moved
  to the notes.
- **Desktop 1440×900, all 20 slides:** one slide at a time, and the collapsed "Speaker notes · N min"
  summary sits top right without collisions. In the METR chart the tick labels are 13 px in SVG
  units. The "Mythos Preview · 17 h" label crossed a confidence-interval line. It now sits to the
  left with a leader line.
- **Mobile 390×844:** a continuous page. The agenda, ladder, habit cards and two-column slides
  stack; tables scroll inside their labelled regions.
  The examiner's navigation probe (`tools/html-pages/examiner-48-navigation.mjs`) failed about one
  run in ten: it counts slides right after shrinking the viewport, before the media-query change
  event re-renders. A page-specific CSS rule now mirrors the paged condition, so slides show as
  soon as the viewport stops matching it. After the fix the probe passed 15 runs out of 15.
- **No-JS:** every slide is visible in order, navigation is hidden, and notes and reveals are
  closed but open natively.
- **Print:** every slide is on its own page, with notes and reveals expanded.
- **Reduced motion:** the same as desktop. The deck has no animation of its own.

## Timing plan

The `data-minutes` add up to 40:

| Slide | Minutes |
| --- | ---: |
| title | 0.5 |
| pure-function | 2 |
| resend | 2 |
| context-window | 1.5 |
| cost-growth (2-3 min context lab) | 4 |
| kv-cache | 2 |
| agent-loop | 2 |
| loop-demo (runbook's 4:00) | 4 |
| stop-conditions | 2 |
| instructions | 2 |
| skills-mcp | 2 |
| bomb-demo (runbook's 5:00) | 5 |
| subagents-hooks | 2 |
| permissions-modes | 2 |
| ladder | 1 |
| models | 1 |
| time-horizons | 2 |
| benchmarks | 1 |
| vibe-vs-agentic | 1 |
| wrap | 1 |

This is a plan, not a measured delivery. A timed rehearsal needs a person and a room.

## D2 · Pure function, re-sent transcript, window, cost, KV cache

- **`pure-function` and `resend`.** These follow `docs/cursus-narrative.md` (Act III). The Claude
  Code prompt-caching page states it directly: "The model doesn't remember anything between
  requests, so Claude Code re-sends the full context". The measured illustration is
  `context-bomb-claude.json`, from 26 calls with per-step `tokens`:
  - the first call's input is 15,654 tokens and the last is 373,202;
  - the input grows monotonically;
  - the inputs sum to the CLI total of 4,889,658.
- **`context-window`.** The 13k figure is `/context` before the bomb, and "13.8K used / 828K" is
  Codex `/status`, both from the bomb runbook's captures. The compaction claims come from the
  docs:
  - Claude Code's memory doc says the project-root CLAUDE.md is re-read after `/compact`, and an
    instruction given only in the conversation can disappear;
  - the Codex slash-command reference lists `/compact` and `/status`.
- **`cost-growth`.** The totals are those of `context-bomb-claude` and `context-bomb-codex`
  (2,982,361). "Roughly with the square of the number of turns" is the closed form in the speaker
  notes, n·P + u·n²/2. The lab instructions match panel 2 of `labs/context.html`: one predict
  question, a turn slider, a cost/tokens selector, and with- and without-caching curves.
- **`kv-cache`.** The memoization framing is the narrative's. Prices are the vendor list prices:
  - Opus 5.5: $4 input, $0.20 cache hit ("0.05x the base input price");
  - GPT-6 Astra: $10 input, $1 cached input.

  The 92% is 4,497,201 / 4,889,658. The cost estimate in the notes is labelled an estimate and
  "at most", because the normalized run does not split cache writes from fresh input. It works
  out to $19.56 uncached against $0.90 + $1.96 = $2.86.

  The Driving line separates changes to the request prefix from changes that leave it alone, per
  the caching doc: switching models invalidates the cache, and so does connecting an MCP server when its tools
  load upfront (with tool search on, the default, the tool list is kept); in Claude
  Code, changing effort on Opus 5.5 or Haiku 5.5 (API key or subscription) keeps it, and a
  mid-session edit to the root CLAUDE.md keeps it because the edit loads only on `/clear`,
  `/compact` or a restart. An earlier version said every effort change or instruction-file edit
  threw the memo away; the examiner found that false (E48-1-1) and it was corrected.

## D3 · The agent loop and stop conditions

- **ReAct.** It is cited from its abstract: reasoning traces and task-specific actions
  "interleaved", with reasoning that helps "induce, track, and update action plans", and actions
  that "gather additional information". "Agents run tools in a loop to achieve a goal" is quoted
  from Willison. Gather, act, verify are the same three phases as the replay widget's lane.
- **`loop-demo`.** Everything matches `demos/agent/loop.md`:
  - the prompt, models and effort;
  - the timing beats;
  - 5 and 6 tool calls;
  - 80,956 and 49,808 tokens for run 1;
  - 30 passed, only `p00_model.py` changed, and line 66.
- **`stop-conditions`.** The runaway loop and premature victory are named. Each has a labelled
  illustrative pattern and a brake taken from the docs:
  - `--max-turns` and `--max-budget-usd`, which the CLI reference lists as print-mode flags;
  - `Stop` hooks, which both hook references list.

  The good stop is real: `impossible-claude` and `impossible-codex` both kept the budget test red
  (`verification.post` is `1 failed, 30 passed`), had empty `changed_files`, and ended with a
  message naming the 400 versus 485 conflict. Claude Code also derived a 445 lower bound. The
  notes call it a case, not a rate.

## D4 · Harness primitives

Each primitive is shown for both CLIs, as ADR 0002 requires:

| Primitive | Claude Code | Codex | Slide |
| --- | --- | --- | --- |
| AGENTS.md and CLAUDE.md | CLAUDE.md; can read AGENTS.md instead | AGENTS.md, root to working folder, 32 KiB cap | `instructions` |
| Skills | follows agentskills.io | "build on the open agent skills standard" | `skills-mcp` |
| MCP | `--mcp-config`, `/mcp` | `-c mcp_servers…`, `/mcp` | `skills-mcp`, `bomb-demo` |
| Subagents | own fresh context window, summary back | spawned in parallel, results collected | `subagents-hooks` |
| Hooks | `PreToolUse` can block, `Stop` | `PreToolUse`, `Stop` and others | `subagents-hooks` |
| Permissions and sandboxing | rules and modes, built-in sandbox | approval policy, `read-only` / `workspace-write` / `danger-full-access`, network off by default | `permissions-modes` |
| Plan mode | Shift+Tab or `/plan` | `/plan` | `permissions-modes` |
| Headless | `claude -p` | `codex exec` | `permissions-modes` |

- **MCP and the foundation.** These come from the MCP blog post of 2025-12-09: Anthropic donated
  MCP to the Agentic AI Foundation, a directed fund under the Linux Foundation, co-founded by
  Anthropic, Block and OpenAI, whose founding projects are MCP, goose and AGENTS.md.
- **Agent Skills.** The format "was originally developed by Anthropic, released as an open
  standard". Skills load in three stages: discovery, activation, execution.
- **`bomb-demo`.** Every number matches `demos/agent/context-bomb.md`:
  - totals 17,233, 18,909 and 40,377;
  - deltas +1,676 and +23,144;
  - Codex 13,502 and +0;
  - `/context` 13k, 14.6k and 36.5k.

  The notes say plainly that the narrative's "agent forgets an earlier instruction" beat did not
  reproduce on these CLI versions. In the recorded context-bomb task, `final_ends_with_rule` is
  true for both vendors.

## D5 · The 2026 landscape

These five slides carry `data-landscape`, a visible "As of 2026-10-18" badge and https sources:
`ladder`, `models`, `time-horizons`, `benchmarks` and `vibe-vs-agentic`.

- **Ladder.** The five rungs are the issue's. The slide says the ladder is this course's framing,
  and the vendor pages show rungs 4 and 5 exist (cloud sessions, parallel agents).
- **Models.** The figures come from the vendor model pages:
  - Opus 5.5 and Fable 5.1 have a 1M window, with default effort medium and high respectively;
  - GPT-6 Astra has 1,050,000 tokens (922,000 maximum input) and `reasoning.effort` levels low,
    medium, high, xhigh and max;
  - Gemini 4 Argon has 1,048,576 tokens of unified input and output, and thinking levels low,
    medium and high.
- **METR.** The chart plots every TH1.1 point marked `is_sota: true` from 2023 on, from METR's
  `benchmark_results_1_1.yaml`. Each point is the p50 estimate with its CI, in minutes:

  | Model | p50 (min) | CI (min) |
  | --- | ---: | ---: |
  | GPT-4 | 3.99 | 1.93–8.00 |
  | GPT-4o | 6.99 | — |
  | Claude 3.5 Sonnet | 11.4 | — |
  | o1-preview | 20.3 | — |
  | o1 | 38.8 | — |
  | Claude 3.7 Sonnet | 60.4 | — |
  | o3 | 120 | — |
  | GPT-5 | 203 | — |
  | Claude Opus 4.5 | 293 | — |
  | GPT-5.2 | 352 | — |
  | Claude Opus 4.6 | 719 | 317–3,634 |
  | Claude Mythos Preview (early) | 1,045 | 509–3,304 |

  The doubling times come from the TH1.1 post's appendix: 196.5 days all time (the slide says
  about 7 months), 130.8 days since 2023 and 88.6 days since 2024. The caveats, in the notes and
  the chart, are METR's own:
  - 50% reliability;
  - self-contained, well-specified tasks;
  - "Measurements above 16 hrs are unreliable with our current task suite";
  - the page "is no longer actively updated", last updated 2026-09-08.
- **Benchmarks.** The two sources disagree with the narrative.

  **Decision.** The narrative says vendor numbers "run far above" standardized ones. The numbers
  found on 2026-10-18 do not show that for Terminal-Bench 4.0:

  | Model | Vendor (Anthropic launch post, 2026-09-22) | Leaderboard (tbench.ai) |
  | --- | --- | --- |
  | Opus 5.5 | 66.4% ± 2.6, xhigh | 64.8% ± 3.1, Claude Code, max |
  | GPT-6 Astra | 57.9%, high, "as reported by OpenAI" | 57.9% ± 3.0, Codex, high |

  The slide shows the comparison as it is, so the figures are not bent to fit the narrative. It
  teaches what does differ: who ran the numbers, the setting, the harness, the trials and the
  error bars. It also quotes Anthropic: "benchmark margins have become a less reliable guide to
  real-world differences". The notes call 66.4 and 64.8 what they are, two evaluations of the
  same model (Opus 5.5), and place the between-model gap at about 65 against 58 (E48-1-2).
- **Vibe coding and agentic engineering.** The Karpathy quote is the original post as Willison
  reproduces it (2025-03-19). The definition of agentic engineering paraphrases Willison's guide
  chapter (`updated_time` 1773614517, that is 2026-03-15). That the term spread in early 2026 is
  Willison's 2026-02-11 post.

## D6 · Demo slots and links

| Slide | Links |
| --- | --- |
| `loop-demo` | `demos/agent/loop.md`; `labs/agent-loop.html#run=loop-claude-run1` and `#run=loop-codex-run1` |
| `bomb-demo` | `demos/agent/context-bomb.md`; `labs/agent-loop.html#run=bomb-claude-run1-without`, `-with`, `-with-tool-search-off` and `bomb-codex-run1-with` |
| `context-window`, `cost-growth` | the context lab's `#budget-title` and `#cost-title` panels |
| `resend`, `cost-growth`, `stop-conditions` | recorded task runs in the replay widget |
| `wrap` | both pages |

The run and reset commands are the runbooks' own. `test_agent_deck.py` checks every link.

## A1 · Claim inventory for the fact-check pass (#50)

There is one row per dated or "latest" claim on a slide or in its notes. The recheck itself
belongs to the fact-check issue, done one week before the session.

| Slide | Claim | Date | Source URL | Source section | Outcome |
| --- | --- | --- | --- | --- | --- |
| pure-function | The model remembers nothing between requests | 2026-10-18 (read) | https://code.claude.com/docs/en/prompt-caching | How the cache is organized | Supported, quoted |
| resend | Claude Code re-sends the full context each request; new content appended | 2026-10-18 (read) | https://code.claude.com/docs/en/prompt-caching | How the cache is organized | Supported |
| resend, cost-growth, kv-cache | 26 calls; 15,654 → 373,202; 4,889,658 total, 4,497,201 cached; Codex 2,982,361 | 2026-10-16 | sessions/01-fundamentals/cursus/fixtures/runs/context-bomb-claude.json, context-bomb-codex.json | steps[].tokens, totals | Matches the recordings |
| context-window | Claude Code re-reads project-root CLAUDE.md after `/compact`; chat-only instructions can be lost | 2026-10-18 (read) | https://code.claude.com/docs/en/memory | Instructions seem lost after /compact | Supported |
| context-window | Codex `/compact` and `/status` (context capacity) | 2026-10-18 (read) | https://learn.chatgpt.com/docs/developer-commands?surface=cli | Slash command table | Supported |
| context-window | `/context` 13k before; `/status` 13.8K used / 828K | 2026-10-16 | sessions/01-fundamentals/cursus/demos/agent/context-bomb.md | Expected outcome | Matches |
| kv-cache | Prefix match is exact; a change recomputes everything after it; model switch recomputes | 2026-10-18 (read) | https://code.claude.com/docs/en/prompt-caching | How the cache is organized | Supported |
| kv-cache | Model switch invalidates, and an MCP server change does when tools load upfront (tool search off); effort change on Opus 5.5 / Haiku 5.5 and a mid-session root CLAUDE.md edit keep the cache | 2026-10-18 (read) | https://code.claude.com/docs/en/prompt-caching | Changing effort level; Editing CLAUDE.md mid-session | Supported |
| kv-cache | Opus 5.5 $4 input, $0.20 cache hit (0.05x) | 2026-10-18 (read) | https://platform.claude.com/docs/en/about-claude/pricing | Model pricing table, footnote 2 | Supported |
| kv-cache | GPT-6 Astra $10 input, $1 cached input | 2026-10-18 (read) | https://developers.openai.com/api/docs/models/gpt-6-astra | Pricing, text tokens | Supported |
| agent-loop | ReAct interleaves reasoning traces and actions | 2022-10-06 | https://arxiv.org/abs/2210.03629 | Abstract | Supported |
| agent-loop | "Agents run tools in a loop to achieve a goal" | 2026-03-15 | https://simonwillison.net/guides/agentic-engineering-patterns/what-is-agentic-engineering/ | What's an agent? | Supported, quoted |
| loop-demo | Paths, 5 and 6 tool calls, 80,956 and 49,808 tokens, 30 passed, line 66 | 2026-10-16 | sessions/01-fundamentals/cursus/demos/agent/loop.md | Expected outcome; Recorded runs | Matches |
| stop-conditions | `--max-turns` and `--max-budget-usd` (print mode) | 2026-10-18 (read) | https://code.claude.com/docs/en/cli-reference | CLI flags | Supported |
| stop-conditions | `Stop` and `PreToolUse` hook events in both CLIs | 2026-10-18 (read) | https://code.claude.com/docs/en/hooks; https://learn.chatgpt.com/docs/hooks | Hook events | Supported |
| stop-conditions | Impossible task: both agents changed nothing and reported the conflict | 2026-10-16 | sessions/01-fundamentals/cursus/fixtures/runs/raw/impossible-claude.meta.json, impossible-codex.meta.json | verification, changed_files; final message | Matches |
| instructions | AGENTS.md is an open format, a README for agents | 2026-10-18 (read) | https://agents.md/ | Home | Supported |
| instructions | Codex reads AGENTS.md root to cwd, concatenated, 32 KiB default | 2026-10-18 (read) | https://learn.chatgpt.com/docs/agent-configuration/agents-md | Discovery | Supported |
| instructions | Claude Code reads CLAUDE.md each session and can read AGENTS.md instead | 2026-10-18 (read) | https://code.claude.com/docs/en/memory | AGENTS.md | Supported |
| skills-mcp | Skill = folder with SKILL.md; progressive disclosure; originally developed by Anthropic, open standard | 2026-10-18 (read) | https://agentskills.io/ | Overview; Open development | Supported |
| skills-mcp | Claude Code and Codex skills follow the standard | 2026-10-18 (read) | https://code.claude.com/docs/en/skills; https://learn.chatgpt.com/docs/build-skills | Intro | Supported |
| skills-mcp | MCP donated to the AAIF, directed fund under the Linux Foundation, co-founded by Anthropic, Block, OpenAI; founding projects MCP, goose, AGENTS.md | 2025-12-09 | https://blog.modelcontextprotocol.io/posts/2025-12-09-mcp-joins-agentic-ai-foundation/ | The Agentic AI Foundation | Supported |
| bomb-demo | Token totals, deltas, `/context` and `/status` readings; all answers OK | 2026-10-16 | sessions/01-fundamentals/cursus/demos/agent/context-bomb.md | Expected outcome | Matches |
| subagents-hooks | Subagent: fresh separate context window, returns summary | 2026-10-18 (read) | https://code.claude.com/docs/en/sub-agents | Intro; context | Supported |
| subagents-hooks | Codex spawns subagents in parallel and collects results | 2026-10-18 (read) | https://learn.chatgpt.com/docs/agent-configuration/subagents | Intro | Supported |
| subagents-hooks | `PreToolUse` hook can block a tool call | 2026-10-18 (read) | https://code.claude.com/docs/en/hooks | Hook events table | Supported |
| permissions-modes | Claude Code modes, sandbox, plan mode (Shift+Tab, `/plan`), `claude -p` | 2026-10-18 (read) | https://code.claude.com/docs/en/permission-modes; https://code.claude.com/docs/en/sandboxing; https://code.claude.com/docs/en/headless | Modes; plan mode; intro | Supported |
| permissions-modes | Codex sandbox modes, network off by default, approval policy, `/plan`, `codex exec` | 2026-10-18 (read) | https://learn.chatgpt.com/docs/sandboxing; https://learn.chatgpt.com/docs/agent-approvals-security; https://learn.chatgpt.com/docs/non-interactive-mode | Modes; defaults | Supported |
| ladder | Cloud sessions and parallel agents exist in both products | 2026-10-18 (read) | https://code.claude.com/docs/en/claude-code-on-the-web; https://code.claude.com/docs/en/agents; https://learn.chatgpt.com/docs/cloud; https://learn.chatgpt.com/docs/agent-configuration/subagents | Intros | Supported; the ladder is labelled the course's framing |
| models | Opus 5.5 and Fable 5.1: 1M context; default effort medium and high | 2026-10-18 (read) | https://platform.claude.com/docs/en/about-claude/models/overview | Compare models | Supported |
| models | GPT-6 Astra: 1,050,000 context, 922,000 max input, effort low to max | 2026-10-18 (read) | https://developers.openai.com/api/docs/models/gpt-6-astra | Model details | Supported |
| models | Gemini 4 Argon: 1,048,576 unified window, thinking low/medium/high | 2026-10-18 (read) | https://ai.google.dev/gemini-api/docs/models/gemini-4-argon | Model card table | Supported |
| time-horizons | TH1.1 doubling: 196.5 days all time, 130.8 since 2023, 88.6 since 2024 | 2026-01-29 | https://metr.org/blog/2026-1-29-time-horizon-1-1/ | Appendix table | Supported |
| time-horizons | Frontier p50 points 2023–2026; GPT-4 ≈ 4 min, Mythos Preview (early) ≈ 17 h | 2026-09-08 (page update) | https://metr.org/time-horizons/ (data: https://metr.org/assets/benchmark_results_1_1.yaml) | is_sota points | Plotted as published |
| time-horizons | Above 16 h unreliable; page no longer actively updated | 2026-09-08 | https://metr.org/time-horizons/ | Header; chart note | Supported |
| benchmarks | Opus 5.5 66.4% ± 2.6 (xhigh); GPT-6 Astra 57.9% (high, as reported by OpenAI); "benchmark margins … less reliable" | 2026-09-22 | https://www.anthropic.com/news/claude-opus-5-5 | Benchmark table, footnote 1, intro | Supported |
| benchmarks | Leaderboard: Opus 5.5 + Claude Code 64.8% ± 3.1 (max); GPT-6 Astra + Codex 57.9% ± 3.0 (high), 58.2% ± 2.8 (max) | 2026-10-18 (read) | https://www.tbench.ai/leaderboard | Terminal-Bench 4.0 table | Supported |
| vibe-vs-agentic | Karpathy's "vibe coding" post, quote | 2025-02-02 | https://twitter.com/karpathy/status/1886192184808149383 (via https://simonwillison.net/2025/Mar/19/vibe-coding/) | Quoted in full by Willison | Supported via Willison |
| vibe-vs-agentic | Agentic engineering: tools, specify, verify and iterate | 2026-03-15 | https://simonwillison.net/guides/agentic-engineering-patterns/what-is-agentic-engineering/ | Agentic engineering | Supported, paraphrase |
| vibe-vs-agentic | The term appears in early 2026, notably from Karpathy and Addy Osmani | 2026-02-11 | https://simonwillison.net/2026/Feb/11/glm-5/ | Body | Supported |
