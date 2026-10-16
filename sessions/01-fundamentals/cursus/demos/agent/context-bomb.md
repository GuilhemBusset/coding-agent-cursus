# The context bomb · runbook

The context window is a finite budget, and the harness decides what goes in it. Add one noisy
MCP server, about 82,000 characters of useless instructions and tool descriptions, then ask the
smallest possible question, `claude -p "Reply with exactly: OK"`, with and without it. Show
`/context` before and after, the token bill of each call, and what tool search does about it.
Then show the Codex equivalent.

The server is [`context_bomb.py`](context_bomb.py), a standard-library port of the 2025
workshop's context-bomb server (provenance and deviations [below](#the-server-and-where-it-comes-from)).
It is registered per invocation only, never with `claude mcp add` or `codex mcp add`:

| Arm | Claude Code (`claude-haiku-5-5`, effort low) | Codex (`gpt-6-luna`, effort low) |
| --- | --- | --- |
| without | `claude -p <prompt> --model … --effort low --strict-mcp-config --no-session-persistence --output-format stream-json --verbose` | `codex exec --json --ephemeral -C <work>/bomb --sandbox read-only -c approval_policy="never" -m … -c model_reasoning_effort="low" --skip-git-repo-check <prompt>` |
| with | the same plus `--mcp-config <work>/bomb/mcp.json` | the same plus `-c mcp_servers.context_bomb.command=… -c mcp_servers.context_bomb.args=[…] -c mcp_servers.context_bomb.required=true` |
| with-tool-search-off | the same as with, run with `ENABLE_TOOL_SEARCH=false` | no such control on this version (see [findings](#tool-search-re-checked-on-2026-10-16)) |

`--strict-mcp-config` keeps any MCP server of the instructor's own Claude Code configuration out
of both arms. For Codex, each arm's metadata records `codex mcp list --json` (the effective
server set) and `required=true` makes `codex exec` fail if the bomb does not start, so exit 0 in
the with arm means the server connected.

## Before class

1. Do the shared setup in the [README](README.md#before-class) (both CLIs logged in). This demo
   needs no uv cache and no export; it needs `tmux` for the Codex `/status` capture.
2. Rehearse once with each CLI (commands under [Run](#run)), then run the [reset](#reset).
3. Keep the [Fallback](#fallback) replay commands ready in a second terminal.

## Timing

| Beat | Duration |
| --- | --- |
| What an MCP server adds to every call; predict | 0:45 |
| Claude Code: `/context` before, three OK calls, `/context` after (twice) | 1:30 |
| Read the token table: the bomb with tool search on and off | 1:00 |
| Codex: the same OK calls, `/status` and `/mcp` | 1:00 |
| Debrief: budget, deferral, and why noisy servers still cost you | 0:45 |
| **Total** | **5:00** |

## Predict

"This server adds about 82,000 characters of noise. How many extra tokens does a one-word
answer cost with it switched on?" Take a show of hands: none, a few thousand, about 20,000,
more.

## Run

From this folder (`sessions/01-fundamentals/cursus/demos/agent`):

```sh
uv run agent_demo.py reset bomb             # <tempdir>/cursus-s1-agent/bomb holds only mcp.json
uv run agent_demo.py run bomb --via claude  # /context before, 3 arms, /context after (on, off)
uv run agent_demo.py run bomb --via codex   # /status before (TUI in tmux), 2 arms, /status after
```

To make a new recording, add `--record --run 1` (then `--run 2`). The Claude Code run captures
`/context` with `claude -p /context`, which this CLI version supports in print mode. The Codex run
starts its TUI in a detached tmux session, sends `Reply with exactly: OK`, `/status` and `/mcp`,
and keeps the screen: `codex exec` has no slash commands.

To show `/context` by hand in the Claude Code TUI instead, from the reset folder:

```sh
claude --strict-mcp-config                                   # then type /context
claude --strict-mcp-config --mcp-config mcp.json             # then /context again
ENABLE_TOOL_SEARCH=false claude --strict-mcp-config --mcp-config mcp.json
```

## Expected outcome

Recorded on 2026-10-16, both rehearsals of each CLI gave the same numbers.

**Claude Code 2.1.301**, `/context` (estimates by the CLI, see the captures):

- before: 13k tokens in use; no MCP lines.
- after, defaults: 14.6k tokens. New lines: "MCP server instructions 1.6k" and
  "MCP tools (deferred) 8k", with each of the five bomb tools at 1.6k.
- after, `ENABLE_TOOL_SEARCH=false` (second half of the same capture file): 36.5k tokens.
  "MCP tools 8k" now loads upfront, and so do Claude Code's own deferred tools: "System tools"
  grows from 7.7k to 21.7k.

Token usage of `claude -p "Reply with exactly: OK"`, every counter as the CLI reported it (total =
input + output + cache read + cache write; the prompt prefix was already cached, so the context
shows up as cache reads):

| Recording | Arm | Input | Output | Cache read | Cache write | Total | Δ total | Tools in init | ToolSearch tool |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `bomb-claude-run1` | without | 2 | 4 | 17,227 | 0 | 17,233 | +0 | 24 | yes |
| `bomb-claude-run1` | with | 2 | 4 | 18,903 | 0 | 18,909 | +1,676 | 29 | yes |
| `bomb-claude-run1` | with-tool-search-off | 2 | 4 | 40,371 | 0 | 40,377 | +23,144 | 28 | no |
| `bomb-claude-run2` | without | 2 | 4 | 17,227 | 0 | 17,233 | +0 | 24 | yes |
| `bomb-claude-run2` | with | 2 | 4 | 18,903 | 0 | 18,909 | +1,676 | 29 | yes |
| `bomb-claude-run2` | with-tool-search-off | 2 | 4 | 40,371 | 0 | 40,377 | +23,144 | 28 | no |

All six answers are exactly `OK`. The with arm's `system/init` event lists `context_bomb` as
`connected` and its five tools. With tool search on, the bomb costs 1,676 tokens per call (its
instructions and the tool names). With tool search off the call costs 23,144 more than the
baseline, more than doubling it. By `/context`'s estimates, about 9.6k of that is the bomb (8k of
tool descriptions, 1.6k of instructions) and about 14k is Claude Code's own tools, which tool
search had also been deferring. The arms measure the setting, not only the server.

**Codex 0.162.1**:

| Recording | Arm | Input | Cached input | Output | Reasoning output | Total | Δ total | Server required |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `bomb-codex-run1` | without | 13,497 | 13,312 | 5 | 0 | 13,502 | +0 | no |
| `bomb-codex-run1` | with | 13,497 | 11,648 | 5 | 0 | 13,502 | +0 | yes |
| `bomb-codex-run2` | without | 13,497 | 11,648 | 5 | 0 | 13,502 | +0 | no |
| `bomb-codex-run2` | with | 13,497 | 11,648 | 5 | 0 | 13,502 | +0 | yes |

Total = input + output (Codex's cached input is part of its input). All four answers are `OK`.
The with arm exits 0 with the bomb marked `required`, and the TUI's `/mcp` lists
`context_bomb: connected (5 tools)`, yet the input is the same 13,497 tokens: none of the bomb's
text reaches the model for this prompt. `/status` reads `Context window: 100% left (13.8K used /
828K)` before and after. `/mcp` also shows that Codex already brings two MCP servers of its own,
`codex_apps` (197 tools) and `codex_worktrees` (3 tools), which are deferred the same way.

Talking points:

- The window is a budget, and every MCP server spends it on every call, before the first word of
  your question. Turn tool search off and the cost of "OK" more than doubles: about 9.6k for the
  bomb, the rest for the harness's own tools.
- Deferral is why a default install looks fine. It is not free: Claude Code still pays for the
  server instructions and tool names (+1.7k per call), and a server's description is still read
  when tool search matches it.
- The bomb is smaller in the window than on disk. Claude Code's documentation says it cuts each
  upfront description and the instructions at 4,096 characters, and `/context` puts each
  13,700-character bomb tool at 1.6k tokens. A real server that is merely verbose stays under
  the cut and is paid for in full.
- The narrative beat "the agent forgets an instruction it was given earlier" is talk track here,
  not a scripted outcome: with tool search on, the bomb no longer floods the window on these CLI
  versions, which is itself the finding.

## Tool search, re-checked on 2026-10-16

Measured with **Claude Code 2.1.301** and **codex-cli 0.162.1** on 2026-10-16 (the recordings
above), against the vendors' documentation read the same day.

**Claude Code 2.1.301.** Tool search is on by default and defers every MCP tool, whatever the
size: only tool names and server instructions load at session start. The init event lists a
`ToolSearch` tool, and `/context` files the bomb under "MCP tools (deferred)". `ENABLE_TOOL_SEARCH`
controls it: `false` loads all MCP tools upfront, `auto` (or `auto:N`) is the old threshold mode
that loads them upfront while they stay under 10% (or N%) of the window, and `true` or unset
defers. Server instructions and upfront tool descriptions are cut at 4,096 characters
(16,384 for a description loaded through tool search); `CLAUDE_CODE_MAX_MCP_DESCRIPTION_LENGTH`
changes that. Source: https://code.claude.com/docs/en/mcp ("Scale with MCP tool search" and
"Configure tool search", read 2026-10-16).

This changes the upstream server's premise. Its comment sizes the bomb "just below" the ~10%
threshold so that "every tool loads eagerly and appears in `/context`". On 2.1.301 that threshold
only applies with `ENABLE_TOOL_SEARCH=auto`; by default the bomb is deferred. The demo shows both:
the default (deferred) and `ENABLE_TOOL_SEARCH=false` (the 2025 behaviour).

**Codex 0.162.1.** MCP tools are always deferred, and this version gives no way to turn that
off. `codex features list` reports `tool_search` and `tool_search_always_defer_mcp_tools` as
`removed`, the second one fixed at `true`. `--disable tool_search_always_defer_mcp_tools`
changes nothing: the call still uses 13,497 input tokens, so there is no tool-search-off arm for
Codex. The configuration reference lists `tool_search = false` and
`tool_search_always_defer_mcp_tools = false` among the retired switches that are rejected:
https://developers.openai.com/codex/config-reference (read 2026-10-16). The bomb is still
reachable. In a probe that asked Codex to call `bomb_status`, Codex found it and tried the call,
which `approval_policy=never` then blocked. Per-invocation servers and the `required` key:
https://developers.openai.com/codex/mcp. `/status`: https://developers.openai.com/codex/cli/slash-commands.

**What the raw streams show.** Claude Code's `stream-json` init event names the server and its
status (`{"name": "context_bomb", "status": "connected"}`) and the tools it added. Codex's
`codex exec --json` prints no MCP startup or discovery event on this version, whether the server
connects or fails to start. The evidence that it connected is the exit code with
`required=true` (a server that cannot start makes `codex exec` fail) plus the TUI's `/mcp` capture.

## Codex equivalent

Codex has no `/context`. Its equivalent is `/status` in the TUI ("Display session configuration
and token usage", including remaining context capacity), and `/mcp` lists the connected servers
and their tool counts. Both are captured in
[`bomb-codex-run1-status-before.txt`](recorded/bomb-codex-run1-status-before.txt) and
[`bomb-codex-run1-status-after.txt`](recorded/bomb-codex-run1-status-after.txt). The token
comparison uses `codex exec --json "Reply with exactly: OK"` and its `turn.completed` usage,
exactly like the original workshop demo, with the server passed through `-c mcp_servers.…`
instead of `codex mcp add`.

## Fallback

No login, no network, a CLI error or no tmux: replay the recordings. They start no CLI and open
no socket.

First choice, on the projector: the agent-loop replay widget, opened straight from disk. Each arm
shows the answer and the usage the CLI reported, and a disclosure holds the full `/context` or
`/status` captures from before and after:
[Claude Code without](../../labs/agent-loop.html#run=bomb-claude-run1-without),
[with](../../labs/agent-loop.html#run=bomb-claude-run1-with),
[with, tool search off](../../labs/agent-loop.html#run=bomb-claude-run1-with-tool-search-off);
[Codex without](../../labs/agent-loop.html#run=bomb-codex-run1-without),
[with](../../labs/agent-loop.html#run=bomb-codex-run1-with). The run 2 arms are in the same
page's selector.

Second choice, in a terminal:

```sh
uv run agent_demo.py replay bomb --via claude
uv run agent_demo.py replay bomb --via codex
uv run agent_demo.py replay bomb --via claude --run 2
uv run agent_demo.py replay bomb --via codex --run 2
```

Each prints the token table re-derived from the raw streams, the init or server details of each
arm, and the key lines of the `/context` or `/status` captures. The full captures are plain text in
[`recorded/`](recorded/).

## Recorded runs

Made with `uv run agent_demo.py run bomb --via <cli> --record --run <N>`, one after the other with
the reset between, never edited by hand. Times are UTC. "Model source": `reported` means the model
is named in the CLI's own stream; `requested` means it is the `-m` value (`codex exec --json` names
no model).

| Recording | CLI | Version | Model | Model source | Effort | Date | Start | End |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| [`bomb-claude-run1`](recorded/bomb-claude-run1.meta.json) | Claude Code | 2.1.301 | `claude-haiku-5-5` | reported | low | 2026-10-16 | 19:44:52 | 19:45:01 |
| [`bomb-claude-run2`](recorded/bomb-claude-run2.meta.json) | Claude Code | 2.1.301 | `claude-haiku-5-5` | reported | low | 2026-10-16 | 19:45:02 | 19:45:11 |
| [`bomb-codex-run1`](recorded/bomb-codex-run1.meta.json) | Codex | 0.162.1 | `gpt-6-luna` | requested | low | 2026-10-16 | 19:40:28 | 19:41:04 |
| [`bomb-codex-run2`](recorded/bomb-codex-run2.meta.json) | Codex | 0.162.1 | `gpt-6-luna` | requested | low | 2026-10-16 | 19:41:04 | 19:41:40 |

Per run: `-without.jsonl`, `-with.jsonl` (and `-with-tool-search-off.jsonl` for Claude Code) are
the raw streams; `-context-before.txt` and `-context-after.txt` (Claude Code; the after file holds
`/context` at CLI defaults, then with `ENABLE_TOOL_SEARCH=false`) or
`-status-before.txt` and `-status-after.txt` (Codex) are the captures, each headed by the command
that made it.

## The server and where it comes from

Upstream: https://github.com/GuilhemBusset/agentic-or-workshop/tree/28228a90eaacc35f82395a2b8ccef8d5a302c036/workshop/materials/part-01-explorer-paradigm/01-data-explorer/mcp/context-bomb
(repository `GuilhemBusset/agentic-or-workshop`, folder
`workshop/materials/part-01-explorer-paradigm/01-data-explorer/mcp/context-bomb`, pinned at
commit `28228a90eaacc35f82395a2b8ccef8d5a302c036`, the `main` head on 2026-10-16; the folder's
only commit is `e795e895d0724d9bdd2b2afcde79f8fc8e7bef7f`, "Initial import of Agentic OR Workshop").
Byte-for-byte snapshots, never edited:

| Snapshot | Upstream file | sha256 |
| --- | --- | --- |
| [`upstream/server.py.txt`](upstream/server.py.txt) | `server.py` | `faec004e6dab4e1ca9a73f582db1dbbca12ccb710855470c34a6d1a78d236db2` |
| [`upstream/README.md.txt`](upstream/README.md.txt) | `README.md` | `041fc46a6733b42a1fb392b3d9f71f7f5c1f045d637ad355ba37329911d32b19` |
| [`upstream/LICENSE.txt`](upstream/LICENSE.txt) | `LICENSE` (repository root) | `834c9a7d9ead7c08a7a2c9fde89a051b1f8ff89457dfd11dd1f1e4ed27bffa76` |

License and attribution: the workshop repository is MIT-licensed ("Copyright (c) 2026
agentic-or-workshop contributors"; full text in [`upstream/LICENSE.txt`](upstream/LICENSE.txt),
fetched at the pinned commit on 2026-10-16) and has the same author as this course. The port keeps that
attribution here and in the server's docstring. The workshop's `THIRD_PARTY.md` concerns its
FICO Xpress dependency, which the context-bomb server does not use. Neither does this port, nor
anything else in this folder.

### Port notes and deviations

What is kept: the server name `data-explorer-context-bomb`, the tool `bomb_status` (no arguments,
deliberately trivial) and the four `bomb_filler_NN` tools, the sizing (5 tools × 7 blocks × 10
lines) and the exact description text upstream generates, upstream's response keys (`answer`,
`tool_count`, `blocks_per_tool`, `total_blocks`), and the demos-only rule.

Deliberate differences:

1. **Standard library instead of FastMCP.** Upstream imports `mcp.server.fastmcp`, which is not a
   dependency of this session. The port speaks MCP over stdio itself (newline-delimited JSON-RPC
   2.0: `initialize`, `ping`, `tools/list`, `tools/call`, notifications ignored, `-32700`,
   `-32600`, `-32601` and `-32602` errors), so it runs with any Python 3.12 and needs no install
   (ADR 0001, `setup/README.md`).
2. **Response keys.** The upstream README documents `answer`, `context_blocks` and
   `context_characters`, but upstream's code returns `answer`, `tool_count`, `blocks_per_tool` and
   `total_blocks`. The port returns all six: `context_blocks` is 42 (the 35 description blocks plus
   7 in the instructions) and `context_characters` is the size of the whole payload, 82,473
   characters.
3. **Oversized instructions.** The upstream README says the server "injects oversized
   instructions by design", but its code sends two short sentences. The port appends one more
   seven-block slice (blocks 36 to 42) to those sentences, 13,815 characters in all, so that both
   channels, server instructions and tool descriptions, carry the bomb.
4. **Registration.** Upstream registers the server with `claude mcp add` and `codex mcp add` and
   removes it afterwards. The port is only ever passed per invocation (`--mcp-config`,
   `-c mcp_servers.…`), so a crashed demo cannot leave it switched on.

The README's safety rules still apply: this server is for this demo only. Never add it to a
project or global configuration.

## Reset

From this folder. It deletes only `<tempdir>/cursus-s1-agent/bomb/` and recreates it with a single
`mcp.json` (the absolute path of the session interpreter and of `context_bomb.py`). It registers
nothing with either CLI, so there is nothing else to undo.

```sh
uv run agent_demo.py reset bomb
```
