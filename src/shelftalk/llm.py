"""Model providers that only need an HTTP POST, so the same code runs on a server and in the
browser (Pyodide). No vendor SDKs: one small adapter per API format.
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

PostJson = Callable[[str, dict, dict], Awaitable[tuple[int, dict]]]


class ModelError(Exception):
    """A model call failed (bad key, quota, network). Shown to the user."""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class Turn:
    role: str  # user | assistant | tool
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    is_error: bool = False


@dataclass
class Reply:
    text: str
    tool_calls: list[ToolCall]
    input_tokens: int = 0
    output_tokens: int = 0


async def urllib_post(url: str, headers: dict, body: dict) -> tuple[int, dict]:
    def call() -> tuple[int, dict]:
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 - fixed provider URLs
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read())
            except Exception:
                return e.code, {"error": {"message": str(e)}}

    return await asyncio.to_thread(call)


async def pyodide_post(url: str, headers: dict, body: dict) -> tuple[int, dict]:
    from pyodide.http import pyfetch  # only importable in the browser

    resp = await pyfetch(url, method="POST", headers=headers, body=json.dumps(body))
    try:
        return resp.status, await resp.json()
    except Exception:
        return resp.status, {"error": {"message": await resp.string()}}


def _error(status: int, data: dict) -> ModelError:
    if status in (401, 403):
        return ModelError("The API key was rejected. Check it in Settings.")
    if status == 429:
        return ModelError("The model provider is rate limiting or out of credit. Try again shortly.")
    err = data.get("error", {}) if isinstance(data, dict) else {}
    return ModelError(f"Model call failed ({status}): {err.get('message', data) if isinstance(err, dict) else err}")


class Anthropic:
    def __init__(self, api_key: str, model: str = "claude-sonnet-5-5", post: PostJson | None = None, browser=False):
        self.api_key, self.model = api_key, model
        self.name = f"Claude ({model})"
        self.post = post or urllib_post
        self.browser = browser

    @staticmethod
    def wire(turns: list[Turn]) -> list[dict]:
        out: list[dict] = []
        for t in turns:
            if t.role == "user":
                out.append({"role": "user", "content": t.content})
            elif t.role == "assistant":
                blocks = [{"type": "text", "text": t.content}] if t.content else []
                blocks += [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments} for c in t.tool_calls]
                out.append({"role": "assistant", "content": blocks})
            else:
                block = {
                    "type": "tool_result",
                    "tool_use_id": t.tool_call_id,
                    "content": t.content,
                    "is_error": t.is_error,
                }
                if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                    out[-1]["content"].append(block)
                else:
                    out.append({"role": "user", "content": [block]})
        return out

    async def complete(self, system: str, turns: list[Turn], tools: list[dict]) -> Reply:
        headers = {"content-type": "application/json", "x-api-key": self.api_key, "anthropic-version": "2023-06-01"}
        if self.browser:
            headers["anthropic-dangerous-direct-browser-access"] = "true"
        body = {
            "model": self.model,
            "max_tokens": 1500,
            "temperature": 0,
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "tools": [
                {"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in tools
            ],
            "messages": self.wire(turns),
        }
        status, data = await self.post("https://api.anthropic.com/v1/messages", headers, body)
        if status >= 400:
            raise _error(status, data)
        blocks = data.get("content", [])
        u = data.get("usage", {})
        return Reply(
            text="".join(b.get("text", "") for b in blocks if b.get("type") == "text"),
            tool_calls=[
                ToolCall(b["id"], b["name"], b.get("input") or {}) for b in blocks if b.get("type") == "tool_use"
            ],
            input_tokens=u.get("input_tokens", 0),
            output_tokens=u.get("output_tokens", 0),
        )


class AzureOpenAI:
    def __init__(
        self,
        api_key: str,
        endpoint: str,
        deployment: str,
        api_version: str = "2024-10-21",
        post: PostJson | None = None,
    ):
        self.api_key = api_key
        self.url = f"{endpoint.rstrip('/')}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"
        self.model = deployment
        self.name = f"Azure AI Foundry ({deployment})"
        self.post = post or urllib_post

    @staticmethod
    def wire(system: str, turns: list[Turn]) -> list[dict]:
        out: list[dict] = [{"role": "system", "content": system}]
        for t in turns:
            if t.role == "user":
                out.append({"role": "user", "content": t.content})
            elif t.role == "assistant":
                msg: dict = {"role": "assistant", "content": t.content or None}
                if t.tool_calls:
                    msg["tool_calls"] = [
                        {
                            "id": c.id,
                            "type": "function",
                            "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
                        }
                        for c in t.tool_calls
                    ]
                out.append(msg)
            else:
                out.append({"role": "tool", "tool_call_id": t.tool_call_id, "content": t.content})
        return out

    async def complete(self, system: str, turns: list[Turn], tools: list[dict]) -> Reply:
        body = {
            "max_tokens": 1500,
            "temperature": 0,
            "messages": self.wire(system, turns),
            "tools": [{"type": "function", "function": t} for t in tools],
        }
        status, data = await self.post(self.url, {"content-type": "application/json", "api-key": self.api_key}, body)
        if status >= 400:
            raise _error(status, data)
        msg = data["choices"][0]["message"]
        calls = []
        for c in msg.get("tool_calls") or []:
            try:
                args = json.loads(c["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {"_unparseable": c["function"].get("arguments")}
            calls.append(ToolCall(c["id"], c["function"]["name"], args))
        u = data.get("usage") or {}
        return Reply(msg.get("content") or "", calls, u.get("prompt_tokens", 0), u.get("completion_tokens", 0))


def from_env():
    """LLM_PROVIDER = anthropic | azure | none (default)."""
    kind = os.getenv("LLM_PROVIDER", "none").lower()
    if kind == "anthropic":
        return Anthropic(os.environ["ANTHROPIC_API_KEY"], os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5"))
    if kind in ("azure", "foundry"):
        return AzureOpenAI(
            os.environ["AZURE_OPENAI_API_KEY"],
            os.environ["AZURE_OPENAI_ENDPOINT"],
            os.environ["AZURE_OPENAI_DEPLOYMENT"],
            os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
        )
    return None
