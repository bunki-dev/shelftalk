"""Ask questions in the terminal: `shelftalk` (set LLM_PROVIDER for the AI agent)."""

from __future__ import annotations

import argparse
import asyncio

from .assistant import Assistant
from .llm import from_env
from .warehouse import open_default


def show(ans) -> None:
    print(f"\n{ans.text}")
    for flag in ans.ungrounded:
        print(f"  ! couldn't trace {flag} to the query results")
    if ans.result and ans.result["rows"]:
        cols = ans.result["columns"]
        print("\n  " + " | ".join(cols))
        for row in ans.result["rows"][:12]:
            print("  " + " | ".join(f"{v:,.2f}" if isinstance(v, float) else str(v) for v in row))
    for sql in ans.sql:
        print("\n  SQL: " + sql.replace("\n", "\n       "))
    print(f"\n  [{ans.source} · {ans.model or '-'} · {ans.latency_ms:.0f} ms]\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="ShelfTalk")
    parser.add_argument("question", nargs="*")
    parser.add_argument("--mode", choices=["auto", "planner", "llm"], default="auto")
    args = parser.parse_args()
    assistant = Assistant(open_default(), from_env())
    if args.question:
        show(asyncio.run(assistant.ask(" ".join(args.question), args.mode)))
        return
    print("ShelfTalk: ask about Bluegum Market's sales. Ctrl+C to quit.")
    try:
        while True:
            q = input("> ").strip()
            if q:
                show(asyncio.run(assistant.ask(q, args.mode)))
    except (KeyboardInterrupt, EOFError):
        print()


if __name__ == "__main__":
    main()
