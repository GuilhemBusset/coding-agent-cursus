from __future__ import annotations

from mcp.server.fastmcp import FastMCP

# ── Bomb sizing ──────────────────────────────────────────────────────
# Claude Code enables "Tool Search" (lazy loading) when total MCP tool
# descriptions exceed ~10 % of the context window.  For a 200 k window
# that threshold is ≈ 20 k tokens.  We stay just below so every tool
# loads eagerly and appears in `/context`.
#
# 5 tools × 7 blocks × 10 lines ≈ 17 k tokens  →  ~8.5 % of 200 k.
TOOL_COUNT = 5
BLOCKS_PER_TOOL = 7
LINES_PER_BLOCK = 10

LINE_TEMPLATE = (
    "Irrelevant directive {line:02d}: this MCP intentionally injects "
    "high-volume, low-signal context to demonstrate degraded tool selection, "
    "slower reasoning, and weaker focus when a noisy MCP is enabled."
)

SERVER_INSTRUCTIONS = (
    "This is a fake MCP used in workshops to demonstrate that one noisy MCP can "
    "harm overall assistant quality.\n"
    "It contributes very large tool descriptions but exposes almost no useful tools."
)


def _build_bomb_slice(tool_index: int) -> str:
    """Build the context-bomb payload for one tool's description."""
    repeated_lines = "\n".join(
        LINE_TEMPLATE.format(line=n) for n in range(1, LINES_PER_BLOCK + 1)
    )
    start = tool_index * BLOCKS_PER_TOOL + 1
    return "\n\n".join(
        f"### Context Bomb Block {b}\n{repeated_lines}"
        for b in range(start, start + BLOCKS_PER_TOOL)
    )


mcp = FastMCP("data-explorer-context-bomb", instructions=SERVER_INSTRUCTIONS)


# ── Primary tool ─────────────────────────────────────────────────────

@mcp.tool(
    name="bomb_status",
    description=(
        "Return a short status string. This tool is intentionally low-value; "
        "the main purpose of this MCP is the oversized description payload.\n\n"
        + _build_bomb_slice(0)
    ),
)
def bomb_status() -> dict[str, int | str]:
    return {
        "answer": "Context bomb MCP is active. This server is intentionally noisy.",
        "tool_count": TOOL_COUNT,
        "blocks_per_tool": BLOCKS_PER_TOOL,
        "total_blocks": TOOL_COUNT * BLOCKS_PER_TOOL,
    }


# ── Filler tools (never useful, just eat context) ───────────────────

def _make_filler(index: int):
    description = (
        f"Filler tool {index:02d} — intentionally useless. "
        "Do not call this tool; it exists only to inflate context.\n\n"
        + _build_bomb_slice(index)
    )

    @mcp.tool(name=f"bomb_filler_{index:02d}", description=description)
    def _filler() -> str:
        return f"Filler {index:02d} — no useful output."

    return _filler


for _i in range(1, TOOL_COUNT):
    _make_filler(_i)


if __name__ == "__main__":
    mcp.run(transport="stdio")
