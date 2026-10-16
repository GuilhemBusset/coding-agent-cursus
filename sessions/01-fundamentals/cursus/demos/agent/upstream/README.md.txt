# Context Bomb MCP Server

Local MCP server used to demonstrate a core risk: one noisy MCP can consume a
large share of context and degrade response quality even when it adds little
practical value.

## Tool surface

- `bomb_status()`
  - returns a short status payload confirming the noisy MCP is active

## MCP behavior contract

- This MCP is intentionally low-signal and high-volume.
- The server injects oversized instructions by design.
- The single tool (`bomb_status`) is deliberately trivial.
- Use this server only for workshop demonstrations of context pollution.

## Safety rules

- Treat this MCP as demo-only.
- Do not use it as a production dependency.
- Keep it disabled unless you are actively running the noise-impact demo.

## Run

From repository root:

```bash
uv run python workshop/materials/part-01-explorer-paradigm/01-data-explorer/mcp/context-bomb/server.py
```

The server runs on MCP `stdio` transport.

## Example query shape

Use `bomb_status` with no arguments.

## Prompt examples (for Codex / Claude Code)

Use prompts like these in Codex or Claude Code so it calls `bomb_status`:

1. `Call bomb_status and report whether the context bomb MCP is active.`
Expected tool args:
```json
{}
```

2. `Using bomb_status, show how many context blocks this MCP injects.`
Expected tool args:
```json
{}
```

## Output

Success payload includes:

- `answer`
- `context_blocks`
- `context_characters`

## Local MCP client config example

```json
{
  "mcpServers": {
    "data-explorer-context-bomb": {
      "command": "uv",
      "args": [
        "run",
        "python",
        "workshop/materials/part-01-explorer-paradigm/01-data-explorer/mcp/context-bomb/server.py"
      ]
    }
  }
}
```

## Codex CLI registration

For Codex CLI, register the server explicitly:

```bash
codex mcp add data-explorer-context-bomb -- \
  uv --directory "$(git rev-parse --show-toplevel)" run python \
  workshop/materials/part-01-explorer-paradigm/01-data-explorer/mcp/context-bomb/server.py
```

Verify:

```bash
codex mcp list
```

Deactivate (remove from Codex MCP registry):

```bash
codex mcp remove data-explorer-context-bomb
```

## Claude Code CLI registration

For Claude Code CLI, register the server explicitly:

```bash
claude mcp add data-explorer-context-bomb -- \
  uv --directory "$(git rev-parse --show-toplevel)" run python \
  workshop/materials/part-01-explorer-paradigm/01-data-explorer/mcp/context-bomb/server.py
```

Verify:

```bash
claude mcp list
```

Deactivate (remove from Claude Code MCP registry):

```bash
claude mcp remove data-explorer-context-bomb
```

## Demo (Codex)

```bash
codex exec --json "Reply with exactly: OK"

codex mcp add data-explorer-context-bomb -- \
  uv --directory "$(git rev-parse --show-toplevel)" run python \
  workshop/materials/part-01-explorer-paradigm/01-data-explorer/mcp/context-bomb/server.py

codex exec --json "Reply with exactly: OK"

codex mcp remove data-explorer-context-bomb
```

## Demo (Claude Code)

```bash
claude -p "Reply with exactly: OK" --output-format text

claude mcp add data-explorer-context-bomb -- \
  uv --directory "$(git rev-parse --show-toplevel)" run python \
  workshop/materials/part-01-explorer-paradigm/01-data-explorer/mcp/context-bomb/server.py

claude -p "Reply with exactly: OK" --output-format text

claude mcp remove data-explorer-context-bomb
```
