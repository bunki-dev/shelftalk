import pytest

from shelftalk.grounding import ungrounded
from shelftalk.planner import Planner, narrate

UNDERSTOOD = [
    "What were total sales last month?",
    "Top 5 products by revenue in Victoria last quarter",
    "Gross margin % by category",
    "Promo uplift by promo type",
    "Own brand share by state",
    "Weekly sales trend for Dairy over the last 12 weeks",
    "Which store had the lowest sales last year?",
    "units sold in QLD in March 2026",
]
HANDED_TO_LLM = [
    "Why did sales drop in August?",
    "How does VIC compare to NSW?",
    "What's the weather like?",
    "Sales of unicorn steaks",
    "Which state grew fastest?",
]


@pytest.fixture(scope="module")
def planner(wh):
    return Planner(wh)


@pytest.mark.parametrize("q", UNDERSTOOD)
def test_understood_questions_run_and_narrate_grounded_numbers(planner, wh, q):
    plan, reason = planner.plan(q)
    assert plan is not None, reason
    result = wh.query(planner.to_sql(plan))
    text = narrate(plan, result.columns, result.rows)
    assert ungrounded(text, [result.to_dict()], q) == []  # the narrator never invents numbers


@pytest.mark.parametrize("q", HANDED_TO_LLM)
def test_anything_not_fully_understood_goes_to_the_llm(planner, q):
    plan, _ = planner.plan(q)
    assert plan is None


def test_metric_precedence(planner):
    assert planner.plan("Gross margin % by category")[0].metric == "margin_pct"
    assert planner.plan("gross margin by category")[0].metric == "gross_margin"
    plan = planner.plan("Own brand share by state")[0]
    assert plan.metric == "own_brand_share" and "own_brand" not in plan.filters


def test_time_phrases_resolve_against_the_data(planner):
    assert planner.plan("sales last month")[0].week_from == "2026-10-01"
    plan = planner.plan("sales last quarter")[0]
    assert (plan.week_from, plan.week_to) == ("2026-07-01", "2026-09-30")
    assert planner.plan("sales in q2 2025")[0].week_from == "2025-04-01"


def test_state_codes_are_case_sensitive(planner):
    assert planner.plan("sales in WA by month")[0].filters == {"state": ["WA"]}
    assert planner.plan("sales by month")[0].filters == {}
