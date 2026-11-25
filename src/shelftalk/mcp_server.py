"""The warehouse as an MCP server: any MCP client gets the schema and guarded, read-only SQL.

python -m shelftalk.mcp_server
"""

from __future__ import annotations

import json

from mcp.server.mcpserver import MCPServer

from .assistant import Assistant
from .warehouse import QueryError, open_default

wh = open_default()
server = MCPServer(name="shelftalk", instructions="Bluegum Market retail warehouse. Read describe_warehouse first.")


@server.tool(description="Schema, business meanings, metric formulas and data range for the warehouse.")
def describe_warehouse() -> str:
    return wh.describe()


@server.tool(description="Run one read-only SQLite SELECT. Personal-data columns and writes are refused.")
def run_sql(sql: str) -> str:
    try:
        return json.dumps(wh.query(sql).to_dict(max_rows=100), default=str)
    except QueryError as e:
        raise ValueError(str(e)) from e


@server.tool(description="Answer a common business question with the deterministic planner (no LLM).")
async def quick_answer(question: str) -> str:
    ans = await Assistant(wh).ask(question, mode="planner")
    return json.dumps(
        {"answer": ans.text, "sql": ans.sql, "rows": (ans.result or {}).get("rows", [])[:50]}, default=str
    )


if __name__ == "__main__":
    server.run()
