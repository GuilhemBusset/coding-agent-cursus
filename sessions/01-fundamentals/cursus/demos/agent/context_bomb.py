"""Context-bomb MCP server: one noisy server that floods an agent's context. Demos only.

A standard-library port of the 2025 workshop's context-bomb server (pinned snapshot in
upstream/server.py.txt; provenance and every deviation in context-bomb.md). It speaks MCP over
stdio, one JSON-RPC message per line, and answers initialize, ping, tools/list and tools/call.
The tool descriptions are byte-for-byte the ones upstream generates. stdout carries only
JSON-RPC; anything else goes to stderr.

    python context_bomb.py      # started by the agent CLI, never by hand

Never register it globally (`claude mcp add`, `codex mcp add`): agent_demo.py passes it per
invocation, so it is gone once the call ends.
"""

import json
import sys

# ── Bomb sizing (upstream, unchanged) ────────────────────────────────
# Upstream: 5 tools x 7 blocks x 10 lines, about 17k tokens, sized to stay below the
# tool-search threshold it assumed. context-bomb.md has what the current CLIs do with it.
TOOL_COUNT = 5
BLOCKS_PER_TOOL = 7
LINES_PER_BLOCK = 10

LINE_TEMPLATE = (
    "Irrelevant directive {line:02d}: this MCP intentionally injects "
    "high-volume, low-signal context to demonstrate degraded tool selection, "
    "slower reasoning, and weaker focus when a noisy MCP is enabled."
)

SERVER_NAME = "data-explorer-context-bomb"
SERVER_VERSION = "1.0.0-cursus"

SERVER_INSTRUCTIONS = (
    "This is a fake MCP used in workshops to demonstrate that one noisy MCP can "
    "harm overall assistant quality.\n"
    "It contributes very large tool descriptions but exposes almost no useful tools."
)

PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")


def _build_bomb_slice(tool_index):
    """Build the context-bomb payload for one tool's description (upstream's text)."""
    repeated_lines = "\n".join(
        LINE_TEMPLATE.format(line=n) for n in range(1, LINES_PER_BLOCK + 1)
    )
    start = tool_index * BLOCKS_PER_TOOL + 1
    return "\n\n".join(
        f"### Context Bomb Block {b}\n{repeated_lines}"
        for b in range(start, start + BLOCKS_PER_TOOL)
    )


# Deviation: upstream's instructions are the two short sentences above, although its README
# says the server "injects oversized instructions by design". The port appends one more slice
# (blocks 36 to 42) so that both channels, server instructions and tool descriptions, carry
# the bomb.
INSTRUCTIONS = SERVER_INSTRUCTIONS + "\n\n" + _build_bomb_slice(TOOL_COUNT)

TOOLS = [{
    "name": "bomb_status",
    "description": (
        "Return a short status string. This tool is intentionally low-value; "
        "the main purpose of this MCP is the oversized description payload.\n\n"
        + _build_bomb_slice(0)
    ),
    "inputSchema": {"type": "object", "properties": {}},
}]
for _i in range(1, TOOL_COUNT):
    TOOLS.append({
        "name": f"bomb_filler_{_i:02d}",
        "description": (
            f"Filler tool {_i:02d} — intentionally useless. "
            "Do not call this tool; it exists only to inflate context.\n\n"
            + _build_bomb_slice(_i)
        ),
        "inputSchema": {"type": "object", "properties": {}},
    })

CONTEXT_BLOCKS = (TOOL_COUNT + 1) * BLOCKS_PER_TOOL
CONTEXT_CHARACTERS = len(INSTRUCTIONS) + sum(len(tool["description"]) for tool in TOOLS)


def bomb_status():
    # Upstream's four keys, plus the two its README documents (context_blocks,
    # context_characters), which upstream's code never returned.
    return {
        "answer": "Context bomb MCP is active. This server is intentionally noisy.",
        "tool_count": TOOL_COUNT,
        "blocks_per_tool": BLOCKS_PER_TOOL,
        "total_blocks": TOOL_COUNT * BLOCKS_PER_TOOL,
        "context_blocks": CONTEXT_BLOCKS,
        "context_characters": CONTEXT_CHARACTERS,
    }


class RpcError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def call_tool(params):
    name = params.get("name")
    if name == "bomb_status":
        payload = bomb_status()
        return {"content": [{"type": "text", "text": json.dumps(payload)}],
                "structuredContent": payload, "isError": False}
    for index in range(1, TOOL_COUNT):
        if name == f"bomb_filler_{index:02d}":
            return {"content": [{"type": "text", "text": f"Filler {index:02d} — no useful output."}],
                    "isError": False}
    raise RpcError(-32602, f"Unknown tool: {name!r}")


def handle(method, params):
    if method == "initialize":
        requested = params.get("protocolVersion")
        version = requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[-2]
        return {"protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions": INSTRUCTIONS}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        return call_tool(params)
    raise RpcError(-32601, f"Method not found: {method}")


def respond(ident, result=None, error=None):
    message = {"jsonrpc": "2.0", "id": ident}
    if error is None:
        message["result"] = result
    else:
        message["error"] = {"code": error.code, "message": error.message}
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def serve(stream):
    for raw in stream:
        line = raw.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except ValueError:
            respond(None, error=RpcError(-32700, "Parse error"))
            continue
        if not isinstance(request, dict) or not isinstance(request.get("method"), str):
            ident = request.get("id") if isinstance(request, dict) else None
            if ident is not None or not isinstance(request, dict) or "result" not in request:
                respond(ident, error=RpcError(-32600, "Invalid Request"))
            continue
        if "id" not in request:
            continue  # a notification (notifications/initialized, cancelled, ...): no reply
        params = request.get("params") or {}
        try:
            if not isinstance(params, dict):
                raise RpcError(-32602, "params must be an object")
            respond(request["id"], handle(request["method"], params))
        except RpcError as error:
            respond(request["id"], error=error)
        except Exception as error:  # never let one bad request kill the demo
            print(f"context_bomb: {type(error).__name__}: {error}", file=sys.stderr)
            respond(request["id"], error=RpcError(-32603, "Internal error"))


if __name__ == "__main__":
    serve(sys.stdin)
