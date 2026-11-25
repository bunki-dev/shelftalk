import asyncio

from shelftalk.assistant import Assistant
from shelftalk.llm import Anthropic, AzureOpenAI, ModelError, Reply, ToolCall, Turn


class ScriptedLLM:
    name = "scripted"

    def __init__(self, *replies):
        self.replies = list(replies)
        self.seen = []

    async def complete(self, system, turns, tools):
        self.seen.append((system, list(turns)))
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def ask(assistant, q, mode="auto"):
    return asyncio.run(assistant.ask(q, mode))


def test_planner_answers_without_calling_the_model(wh):
    llm = ScriptedLLM()
    ans = ask(Assistant(wh, llm), "Sales by state in 2025")
    assert ans.source == "planner" and ans.chart["type"] == "bar" and not llm.seen


def test_agent_recovers_from_a_refusal_and_is_grounded(wh):
    llm = ScriptedLLM(
        Reply("", [ToolCall("1", "run_sql", {"sql": "SELECT email FROM loyalty_members"})]),
        Reply("", [ToolCall("2", "run_sql", {"sql": "SELECT tier, COUNT(*) AS n FROM loyalty_members GROUP BY tier"})]),
        Reply("", [ToolCall("3", "answer", {"text": "There are 3 tiers; Gold is the smallest.", "chart": "bar"})]),
    )
    ans = ask(Assistant(wh, llm), "Why do gold members spend more?")
    assert ans.source == "llm" and ans.ungrounded == []
    assert "personal information" in ans.steps[0]["error"]
    tool_result = llm.seen[1][1][-1]
    assert tool_result.role == "tool" and tool_result.is_error  # the refusal went back to the model
    assert ans.chart == {"type": "bar", "x": "tier", "y": "n"}


def test_invented_numbers_are_flagged(wh):
    llm = ScriptedLLM(
        Reply("", [ToolCall("1", "run_sql", {"sql": "SELECT SUM(units) FROM sales"})]),
        Reply("", [ToolCall("2", "answer", {"text": "We sold 12,345,678 units, up 7.5%."})]),
    )
    ans = ask(Assistant(wh, llm), "How many units did we sell, and why?")
    assert ans.ungrounded == ["12,345,678", "7.5%"]


def test_model_errors_are_reported_not_raised(wh):
    ans = ask(Assistant(wh, ScriptedLLM(ModelError("The API key was rejected."))), "Why did sales dip?")
    assert ans.source == "none" and "rejected" in ans.text


def test_without_a_model_it_explains_what_it_can_do(wh):
    ans = ask(Assistant(wh), "Why did sales dip in August?")
    assert ans.source == "none" and "Try:" in ans.text


def test_follow_ups_carry_context_to_the_model(wh):
    llm = ScriptedLLM(Reply("", [ToolCall("1", "answer", {"text": "Sure."})]))
    a = Assistant(wh, llm)
    ask(a, "Sales by state in 2025")
    ask(a, "Why is NSW first?")
    turns = llm.seen[0][1]
    assert [t.role for t in turns[:3]] == ["user", "assistant", "user"]


def test_wire_formats():
    turns = [
        Turn("user", "hi"),
        Turn("assistant", "", [ToolCall("a", "run_sql", {"sql": "x"})]),
        Turn("tool", "{}", tool_call_id="a"),
    ]
    wire = Anthropic.wire(turns)
    assert [w["role"] for w in wire] == ["user", "assistant", "user"]
    assert wire[2]["content"][0]["tool_use_id"] == "a"
    az = AzureOpenAI.wire("sys", turns)
    assert az[0]["role"] == "system" and az[-1] == {"role": "tool", "tool_call_id": "a", "content": "{}"}


def test_browser_flag_adds_direct_access_header():
    seen = {}

    async def post(url, headers, body):
        seen.update(headers)
        return 200, {"content": [{"type": "text", "text": "ok"}], "usage": {}}

    asyncio.run(Anthropic("k", post=post, browser=True).complete("s", [Turn("user", "hi")], []))
    assert seen["anthropic-dangerous-direct-browser-access"] == "true"
