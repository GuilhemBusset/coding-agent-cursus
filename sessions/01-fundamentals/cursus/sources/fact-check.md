# Fact-check pass, 2026-10-18

The pass happened one week before Session 1 (issue #50). Every dated claim on a delivered page was
re-read against its primary source on 2026-10-18. That covers models, prices, plans, CLI commands,
benchmarks and incidents. Each claim was then kept, updated or reworded. No claim had to be
removed: every one either still held or could be corrected from its source. The bibliography is
[`../sources.html`](../sources.html).

## Method

- **Pages covered.** The decks `cursus/00-opening`, `01-sampler`, `02-thinking`, `03-agent`,
  `05-failure` and `99-close`; every lab under `cursus/labs/`; and `exercises/00-prework`,
  `lab-ladder` and `home`; and the session hub `index.html`, `cursus/run-of-show.html` and
  `cursus/instructor-notes.html`. The demo runbooks that state an as-of date were also covered:
  `demos/model/sampling.md`, `demos/effort/README.md` and `demos/agent/context-bomb.md`.
- **How sources were read.** Every external link on those pages was fetched on 2026-10-18 and
  read as text. CLI flags were also checked against the installed CLIs: `claude --help` for
  Claude Code 2.1.302, and `codex --help` and `codex exec --help` for codex-cli 0.162.1.
- **Sites that refuse automated reading:**
  - openai.com (403): read through the Internet Archive copies of 2026-10-10 (sycophancy) and
    2026-09-25 (Codex agent loop);
  - openreview.net (browser challenge): the LeCun PDF was read through the Internet Archive copy
    of 2026-06-26;
  - doi.org (403): the Dell'Acqua et al. abstract was read through its Crossref record;
  - X: post text was read through X's public embed endpoint, and the long Karpathy post through
    the fxtwitter mirror. The PocketOS founder's X article needs a login, so only its title, author
    and date were checked.
- **Dates.** A date that the page itself controls was moved to 2026-10-18 once its claim was
  rechecked. Two kinds of date stay as they are, with a visible "rechecked 2026-10-18" next to
  them, because tests tie them to a recorded snapshot:
  - the price snapshot `demos/effort/prices.json` (2026-10-11), which the effort recording and the
    context lab use;
  - the pre-work audit dates in `prework-verification.md` (2026-10-10).

  "Recorded 2026-10-16" and similar dates say when a run happened, not when a fact was last true.
  They are not as-of dates and stay.
- **Single secondary sources.** A claim counts as single-secondary when its only support is a
  news article, a recap or an aggregator, with no primary page and no second independent source.
  Those claims are listed under A2 below.

`tests/test_sources.py` enforces the dates. Every as-of, checked, read or accessed date on a
delivered page must be on or after the pass date in `sources.html` (`data-fact-check`). An older
snapshot date passes only next to a "rechecked" date that is on or after the pass date. The test
also checks two more things: `sources.html` lists every external link the pages cite, and the pass
date is no earlier than the latest date in this log.

## Claim log

Outcomes:

- **kept**: the claim still holds and only its date moved;
- **updated**: the claim's content changed;
- **reworded**: the attribution or phrasing changed, and the facts did not.

All sources were accessed on 2026-10-18.

### Opening (`cursus/00-opening.html`)

| Claim | Primary source | Outcome |
| --- | --- | --- |
| METR 2025 RCT: 24% forecast, 19% slower, 20% believed; 16 developers, 246 issues | https://metr.org/blog/2025-07-10-early-2025-ai-experienced-os-dev-study/ | kept |
| METR 2026 follow-up: -18% (CI -38% to +9%), -4% (-15% to +9%), 10 and 47 developers, $150 to $50/hr, 30% to 50% withheld tasks, quotes | https://metr.org/blog/2026-02-24-uplift-update/ | kept |
| Jagged frontier: 758 workers, 18 tasks, 12.2% more, 25.1% faster, 19% less likely correct; Organization Science 37(2), March 2026 | https://doi.org/10.1287/orsc.2025.21838 (Crossref record) | kept |
| Agenda and modes "as of" the Session 1 plan | `docs/cursus-narrative.md` (unchanged since 2026-10-04) | kept, as-of 2026-10-10 to 2026-10-18 (3 places) |

### Act I (`cursus/01-sampler.html` and its labs)

| Claim | Primary source | Outcome |
| --- | --- | --- |
| Neither CLI exposes a temperature, top-p or seed option | https://code.claude.com/docs/en/cli-reference; https://developers.openai.com/codex/cli/reference (now learn.chatgpt.com/docs/developer-commands); `--help` of Claude Code 2.1.302 and codex-cli 0.162.1 | kept, as-of 2026-10-11 to 2026-10-18, versions named; `demos/model/sampling.md` gets a recheck line |
| Claude's tokenizer is not public; the counting endpoint gives counts only; Opus 4.7 and later use a newer tokenizer (tokenizer lab) | https://platform.claude.com/docs/en/build-with-claude/token-counting | kept, as-of 2026-10-13 to 2026-10-18 |
| The older anthropic-tokenizer-typescript is inaccurate from Claude 3 on | https://github.com/anthropics/anthropic-tokenizer-typescript | updated: the repository was archived on 2026-09-01, which the lab now says |
| Delétang et al., Tülu 3, DeepSeek-R1 (arXiv), Karpathy deep dive | arXiv 2309.10668, 2411.15124, 2501.12948; YouTube 7xTGNNLPyMI (2025-02-05) | kept (publication facts, not as-of claims) |

### Act II (`cursus/02-thinking.html` and its labs)

| Claim | Primary source | Outcome |
| --- | --- | --- |
| Opus 5.5 $4/$20, GPT-6 Astra $10/$50 per MTok (notes) | https://platform.claude.com/docs/en/about-claude/pricing; https://developers.openai.com/api/docs/models/gpt-6-astra (platform.openai.com/docs/pricing redirects to developers.openai.com) | kept; "as of 2026-10-11, rechecked 2026-10-18 and unchanged" (snapshot date tied to `prices.json`) |
| Claude effort levels low to max, Opus 5.5 default medium, "a behavioral signal, not a strict token budget" | https://platform.claude.com/docs/en/build-with-claude/effort | kept, as-of 2026-10-18 |
| Codex `model_reasoning_effort` levels | https://developers.openai.com/codex/config-reference (now learn.chatgpt.com/docs/config-file/config-reference) | updated: "low, medium, high, xhigh" is now "per model and client, such as low, medium, high, xhigh, max". The reference also names `ultra`; `demos/effort/README.md` notes both |
| Gemini `thinking_level` minimal to high, by model | https://ai.google.dev/gemini-api/docs/thinking | kept |
| Sharpen or expand is open | arXiv 2504.13837, 2505.24864; arXiv search 2026-10-18 shows new work (for example arXiv 2610.04158, 2026-10-03) and no settled answer | kept, contested label stays, as-of 2026-10-18 |
| Effort-demo recording costs at list prices | `demos/effort/recorded/results.json`, prices above | kept; "list prices as of 2026-10-11, rechecked 2026-10-18 and unchanged" |
| R1-Zero AIME 15.6% to 77.9%, Nature 645, 633–638 | https://www.nature.com/articles/s41586-025-09422-z | kept |
| Faithfulness 25% and 39%, over 99% exploit, under 2% admit | https://www.anthropic.com/research/reasoning-models-dont-say-think | kept |
| 36 + 59 and rhyme planning | https://transformer-circuits.pub/2025/attribution-graphs/biology.html | kept |
| LeCun Mode-1/Mode-2 "by analogy", v0.9.2, 2022-06-27; world model adjusted after the next observation | https://openreview.net/pdf?id=BZ5a1r-kVsf (Internet Archive copy) | kept |
| Bengio 2019 System 2 | https://neurips.cc/virtual/2019/invited-talk/15488 | kept |
| V-JEPA 2, Genie 3 (24 fps, 720p, a few minutes), Cosmos 3 (2026-05-31) | arXiv 2506.09985; deepmind.google; nvidianews.nvidia.com | kept, labelled makers' claims |
| AMI Labs: $1.03B round, aims; "LeCun's company" (notes) | https://amilabs.xyz/updates; https://amilabs.xyz/ (lists Yann LeCun, states the representation-space aim) | updated: the home page is now cited as well, since the launch post alone does not name LeCun |
| Merrill and Sabharwal, Vaswani, Brown, Snell, Chen, Gema, Greshake, Li, Vafa | arXiv abstracts (latest versions checked) | kept |

### Act III (`cursus/03-agent.html` and its labs)

The deck was written on 2026-10-18, so its "read 2026-10-18" dates already met the pass date.
The pass still re-read the time-sensitive claims.

| Claim | Primary source | Outcome |
| --- | --- | --- |
| Opus 5.5 and Fable 5.1: 1M window, default effort medium and high | https://platform.claude.com/docs/en/about-claude/models/overview (now served at /docs/en/models/overview) | kept |
| GPT-6 Astra: 1,050,000 window, "takes at most 922,000 input tokens", effort low to max | https://developers.openai.com/api/docs/models/gpt-6-astra | updated: the page states 1,050,000 and 128,000 max output, not 922,000 input. The slide now says the window includes up to 128,000 output tokens |
| Gemini 4 Argon: 1,048,576 input and output, thinking low/medium/high | https://ai.google.dev/gemini-api/docs/models/gemini-4-argon | kept; still Google's flagship. GPT-6 Astra is still OpenAI's flagship (models page), and the Claude lineup is unchanged |
| Cache hit 5% on Opus 5.5 ($0.20), 10% on GPT-6 Astra ($1) | Anthropic pricing; GPT-6 Astra page | kept |
| METR time horizons: points, doubling times, "no longer actively updated", last update 2026-09-08 | https://metr.org/time-horizons/; https://metr.org/blog/2026-1-29-time-horizon-1-1/ | kept |
| Terminal-Bench 4.0: vendor 66.4% ± 2.6 (xhigh), 57.9% (as reported by OpenAI); leaderboard 64.8% ± 3.1, 57.9% ± 3.0, 58.2% ± 2.8 | https://www.anthropic.com/news/claude-opus-5-5; https://www.tbench.ai/leaderboard (now opens the 4.0 board on the home page) | kept |
| MCP to the AAIF; founding projects; Agent Skills origin; AGENTS.md 32 KiB; hooks, subagents, sandbox modes, plan mode, `claude -p`, `codex exec` | the vendor docs cited on each slide | kept |
| "Agentic engineering" used by Karpathy and others in early 2026 | was: Willison's 2026-02-11 post only; now also https://x.com/karpathy/status/2019137879310836075 (2026-02-04) and https://addyosmani.com/blog/agentic-engineering/ (2026-02-04) | updated: Karpathy's and Osmani's own posts are now cited |
| Karpathy's "vibe coding" quote | https://twitter.com/karpathy/status/1886192184808149383 (text checked against the post) | kept |
| Rungs 4 and 5 exist: agent teams, projects, Codex subagents, Ultra (notes) | https://code.claude.com/docs/en/agents; https://learn.chatgpt.com/docs/agent-configuration/subagents | kept |
| Context lab: Sonnet 5.5 $2 / $2.50 / $0.10; 200k and 1M windows; `/context`, `/compact`, `/clear`, `/status`, `/new` | Anthropic pricing and context-windows pages; Claude Code commands; Codex developer commands | kept; snapshot dates stay 2026-10-11, with a recheck stamp in the caption, the figure and the footer; the commands' "checked 2026-10-16" is now "rechecked 2026-10-18" |
| Agent-loop lab: gather, act, verify; Codex resends the transcript | https://code.claude.com/docs/en/how-claude-code-works; https://openai.com/index/unrolling-the-codex-agent-loop/ (archive copy) | kept |
| Tool search and `ENABLE_TOOL_SEARCH` values, 4,096 and 16,384 character caps (`demos/agent/context-bomb.md`) | https://code.claude.com/docs/en/mcp | kept (still matches; the runbook's dated findings are a recording) |

### Act IV (`exercises/lab-ladder.html`)

| Claim | Primary source | Outcome |
| --- | --- | --- |
| CLI commands "as of 2026-10" on Claude Code 2.1.291 and Codex CLI 0.160.0. These are `--permission-mode plan`, `-p --permission-mode acceptEdits`, `--sandbox read-only`, `exec --sandbox workspace-write`, `/plan`, `/permissions`, and the skill paths and invocations | `--help` of Claude Code 2.1.302 and codex-cli 0.162.1; code.claude.com cli-reference, common-workflows, skills; learn.chatgpt.com developer-commands, build-skills | updated: as-of 2026-10-18 with the current versions, and the first-check versions kept in brackets |
| Anthropic coding-skills RCT: 52 developers, 50% against 67%, largest gap on debugging | https://www.anthropic.com/research/AI-assistance-coding-skills (modified 2026-09-09, figures unchanged) | kept, accessed 2026-10-05 to 2026-10-18 |
| Codex's "Implement this plan?" prompt | interactive UI only, not in the docs; evidence in `cursus/labs/lab-ladder-evidence/` | not rechecked live. The page already hedges it ("If it does not ask, type /plan again") and gives it no date |

### Act V (`cursus/05-failure.html`, verifier-gaming lab)

| Claim | Primary source | Outcome |
| --- | --- | --- |
| ImpossibleBench quotes, submitted 2025-10-23 | https://arxiv.org/abs/2510.20270 | kept |
| ExploitGym: from July 8, ~1,200 agents, >70,000 messages, ~700 in the Hugging Face attack, stop around 01:30 on July 12, lockout July 13, METR's caveats | https://metr.org/blog/2026-08-26-openai-hugging-face-incident-investigation/ | kept |
| AlphaEvolve "cheating phenomenon" quote, v3 2025-12-22 | https://arxiv.org/html/2511.02864v3 | kept |
| PocketOS: founder quotes ("entirely on its own initiative", "9 seconds", "all volume-level backups") | was: Tom's Hardware only (secondary); the founder's own article exists at https://x.com/lifeofjer/status/2048103471019434248 (2026-04-25, login needed) | reworded: the quotes are attributed "as quoted by Tom's Hardware", and the founder's article is cited (see A2) |
| PocketOS: local token, `volumeDelete`, account scope, recovery, "Tokens should have scopes that match the task" | https://blog.railway.com/p/your-ai-wants-to-nuke-your-database | kept; Railway does not name the customer, which the slide now says |
| Lethal trifecta quotes | https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/ | kept |
| Package hallucinations: 576,000 samples, 16 LLMs, 5.2% and 21.7%, 205,474 names | https://arxiv.org/abs/2406.10279 | kept |
| 28.65 million new secrets in 2025, blog of 2026-03-17 | https://blog.gitguardian.com/the-state-of-secrets-sprawl-2026/ | kept |
| GPT-4o sycophancy: 2025-04-25 update, rollback from 2025-04-28, quotes | https://openai.com/index/expanding-on-sycophancy/ (archive copy) | kept |
| Verifier's rule quote, 2025-07-15 | https://www.jasonwei.net/blog/asymmetry-of-verification-and-verifiers-law | kept |

### Close (`cursus/99-close.html`)

| Claim | Primary source | Outcome |
| --- | --- | --- |
| Exit-ticket parameters, homework, Session 2 | `docs/cursus-narrative.md`; `docs/adr/0009-homework-on-per-student-branches.md` (both unchanged since 2026-10-04) | kept, as-of 2026-10-10 to 2026-10-18 (5 places) |

### Pre-work (`exercises/00-prework.html`)

| Claim | Primary source | Outcome |
| --- | --- | --- |
| git, gh, uv, mise install commands per platform | git-scm.com install pages; cli/cli install docs; docs.astral.sh; mise.jdx.dev | kept: every command matches its page. A "rechecked 2026-10-18" stamp sits beside each "checked 2026-10-10" |
| Claude Code native installers; Pro, Max, Team, Enterprise or Console account; Git Bash on Windows | https://code.claude.com/docs/en/setup | kept, stamped |
| Codex installers (sh, ps1, Homebrew cask, `npm install -g @openai/codex`); ChatGPT plan or API key; Windows sandbox | https://developers.openai.com/codex/cli; https://github.com/openai/codex; https://developers.openai.com/codex/windows | kept, stamped |
| `npm i -g codex` installs an unrelated package | https://registry.npmjs.org/codex (a static site generator, 0.2.3) | kept; now backed by the registry itself |
| Login: press c to copy the URL; `ANTHROPIC_API_KEY` always used with `-p`; `codex login --device-auth` after enabling device code login | https://code.claude.com/docs/en/authentication; https://developers.openai.com/codex/auth | kept, stamped |
| Videos: 3Blue1Brown about 8 min (7:58); Karpathy 2 h 11 min, chapters 2:54, 22:54, 31:00, 1:14:02, about 38 min | YouTube pages and their chapter lists | kept, stamped |
| Claude Code 101: "lesson estimates add up to about 2 hours" | https://anthropic.skilljar.com/claude-code-101 | reworded: the public page no longer shows lesson times. The page says 12 lessons and a quiz, that the times shown on 2026-10-10 added up to about 2 hours, and that they are gone now |
| Get Started with Codex, "~80 minutes" | https://academy.openai.com/public/courses/get-started-with-codex-jkhsq | kept, stamped |

### Session hub and instructor pages (`index.html`, `cursus/run-of-show.html`, `cursus/instructor-notes.html`)

| Claim | Primary source | Outcome |
| --- | --- | --- |
| Agenda and time boxes | `docs/cursus-narrative.md` (unchanged since 2026-10-04) | kept, as-of 2026-10-10 to 2026-10-18 (hub and run of show) |
| Neither agent CLI exposes a temperature setting | `claude --help` (Claude Code 2.1.302), `codex --help` and `codex exec --help` (codex-cli 0.162.1) | kept, as-of 2026-10-11 to 2026-10-18 |
| The 2025 primer's misconceptions and anticipated questions; file last changed 2026-03-07 | https://github.com/GuilhemBusset/agentic-or-workshop/blob/main/workshop/materials/part-00-fundamental/00-llm-architecture/instructor-llm-architecture-primer.md and its GitHub commit history | kept; added to `sources.html` |

## A2 · Claims backed by a single secondary source

| Page | Claim | Before | Now |
| --- | --- | --- | --- |
| Act V, PocketOS | The founder's words: "decided — entirely on its own initiative…", "our production database and all volume-level backups", "It took 9 seconds" | Tom's Hardware only, presented as what the founder says | Attributed on the slide "as quoted by Tom's Hardware". The founder's own article (primary, behind an X login) is cited. Railway's post independently confirms the event, the token and the recovery |
| Act III, vibe vs agentic | Karpathy uses "agentic engineering" | Willison's post only | Karpathy's own post and Osmani's post cited |
| Act III, vibe vs agentic | Karpathy's vibe-coding quote | Willison's reproduction | Checked against the original post, which the slide already links |
| Act II, notes | AMI Labs is LeCun's company | not stated by the cited launch post | AMI's home page cited |
| Opening | Jagged frontier figures | primary (journal), unreachable by bot | Read through the Crossref record of the publisher's abstract |

No other claim rests on a secondary source alone. These stay labelled as what they are:

- the contested research positions in Act II;
- the makers' world-model announcements;
- the instructor's first-hand 2025 workshop case.

## Changelog

The PR description repeats this list.

- **Act I deck:** CLI sampling-flag claim rechecked against Claude Code 2.1.302 and codex-cli
  0.162.1; as-of 2026-10-18.
- **Act II deck:**
  - Codex effort levels updated (max added, per model and client);
  - vendor docs as-of 2026-10-18;
  - the open sharpen-or-expand question rechecked;
  - prices stamped "rechecked 2026-10-18 and unchanged";
  - AMI Labs home page cited.
- **Act III deck:**
  - the GPT-6 Astra "922,000 input tokens" figure, which the vendor page does not state, replaced
    by the stated 128,000 maximum output;
  - Karpathy's and Osmani's own "agentic engineering" posts cited.
- **Act V deck:** PocketOS founder quotes attributed "as quoted by Tom's Hardware" (single
  secondary source); the founder's own article cited; Railway marked as not naming the customer.
- **Opening and Close decks:** plan and ADR as-of dates moved to 2026-10-18 after the recheck.
- **Labs:**
  - tokenizer lab as-of 2026-10-18, with the archived tokenizer repository noted;
  - context lab prices and constants stamped "rechecked 2026-10-18", commands rechecked.
- **Lab ladder:** CLI commands rechecked on current versions (as-of 2026-10-18); the
  Anthropic study accessed 2026-10-18.
- **Pre-work:**
  - every install, login and reading source stamped "rechecked 2026-10-18";
  - the Claude Code 101 duration reworded, since the course page no longer shows lesson times.
- **Session hub, run of show, instructor notes:** plan and CLI as-of dates moved to 2026-10-18
  after the recheck; the 2025 primer added to the bibliography.
- **Runbooks:** `sampling.md` and the effort README note the 2026-10-18 recheck.
- **New:**
  - `cursus/sources.html`, the bibliography by act with access dates;
  - this log;
  - `tests/test_sources.py`.
