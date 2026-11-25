"""Bridge for running ShelfTalk in the browser (Pyodide). Exchanges JSON strings with the page."""

from __future__ import annotations

import json

from .assistant import SUGGESTIONS, Assistant
from .llm import Anthropic, AzureOpenAI, pyodide_post
from .warehouse import Warehouse

_assistant: Assistant | None = None


def _llm(settings: dict):
    key = (settings.get("api_key") or "").strip()
    if settings.get("provider") == "anthropic" and key:
        return Anthropic(key, settings.get("model") or "claude-sonnet-5-5", post=pyodide_post, browser=True)
    if settings.get("provider") == "azure" and key and settings.get("endpoint") and settings.get("deployment"):
        return AzureOpenAI(
            key,
            settings["endpoint"],
            settings["deployment"],
            settings.get("api_version") or "2024-10-21",
            post=pyodide_post,
        )
    return None


def init(db_path: str) -> str:
    global _assistant
    _assistant = Assistant(Warehouse(db_path))
    first, last = _assistant.wh.data_range()
    return json.dumps({"suggestions": SUGGESTIONS, "first_week": first, "last_week": last})


async def ask(question: str, settings_json: str) -> str:
    assert _assistant is not None, "call init first"
    _assistant.llm = _llm(json.loads(settings_json or "{}"))
    ans = await _assistant.ask(question)
    return json.dumps(ans.to_dict(), default=str)


def schema() -> str:
    assert _assistant is not None
    return _assistant.wh.describe()
