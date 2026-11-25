"""Deterministic question planner: metric x dimensions x filters x time, built from the semantic layer.

Most questions people ask a sales dashboard follow a few shapes ("top 5 products by sales in
VIC last quarter"). Answering those without an LLM is faster, free, and always correct by
construction. The planner only answers when it understands every meaningful word in the
question; anything else ("why did...", "compare X to Y") goes to the LLM agent instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from .warehouse import Warehouse, semantic

STOPWORDS = set(
    """a an the of in on for to and or by per with what what's whats which who how much many is are was were
    did do does me show give tell list our my all across each every at from during over been be has have
    had it its this that these those there their there's please can could you i we get got sold sell
    selling made make earned brought bring value values number numbers amount figure figures data total overall
    sum we're between as".split()
    """.split()
)
GLUE = {
    "top",
    "best",
    "worst",
    "highest",
    "lowest",
    "most",
    "least",
    "biggest",
    "smallest",
    "largest",
    "trend",
    "trends",
    "time",
    "breakdown",
    "ranked",
    "rank",
    "ranking",
    "performing",
    "performer",
    "performers",
    "leading",
    "led",
    "lead",
    "split",
    "compare",
    "comparison",
    "versus",
    "vs",
    "graph",
    "chart",
    "plot",
    "table",
    "so",
    "far",
    "date",
    "ytd",
    "weeks",
    "week",
    "months",
    "month",
    "quarter",
    "year",
    "latest",
    "recent",
    "last",
    "past",
    "previous",
    "this",
    "current",
    "full",
    "whole",
    "only",
    "just",
}
RANK_DESC = {"top", "best", "highest", "most", "biggest", "largest", "leading", "led", "lead"}
RANK_ASC = {"worst", "lowest", "least", "smallest", "bottom"}
NEEDS_LLM = re.compile(
    r"\b(why|because|cause|predict|forecast|should|would|correlat\w*|growth|grew|grow|change|changed|"
    r"increase|decrease|declin\w*|differen\w*|yoy|year[- ]on[- ]year|vs\.?|versus|compared?|than|"
    r"share of|percent of|proportion|ratio|average per|per store|per member|explain|recommend|anomal\w*|"
    r"outlier|unusual|spike|dip|drop|impact|effect|affect\w*)\b",
    re.I,
)
STATE_NAMES = {
    "new south wales": "NSW",
    "victoria": "VIC",
    "victorian": "VIC",
    "queensland": "QLD",
    "western australia": "WA",
    "south australia": "SA",
    "tasmania": "TAS",
    "canberra": "ACT",
    "australian capital territory": "ACT",
}
STATE_CODES = ["NSW", "VIC", "QLD", "WA", "SA", "TAS", "ACT"]
MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ],
        start=1,
    )
}
MONTHS |= {k[:3]: v for k, v in MONTHS.items()} | {"sept": 9}


def phrase_re(phrase: str) -> str:
    """Whole-phrase match that also works for phrases containing %, & or hyphens."""
    return rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])"


@dataclass
class Plan:
    metric: str
    dims: list[str] = field(default_factory=list)
    filters: dict[str, list[str]] = field(default_factory=dict)  # dimension -> allowed values
    week_from: str | None = None
    week_to: str | None = None
    time_label: str = "across all two years of data"
    limit: int | None = None
    order: str = "desc"  # desc | asc | time
    chart: str = "none"  # none | bar | line

    def describe(self) -> str:
        parts = [semantic()["metrics"][self.metric]["label"]]
        if self.dims:
            parts.append("by " + " and ".join(self.dims))
        for dim, values in self.filters.items():
            parts.append(f"{dim} = {', '.join(values)}")
        parts.append(self.time_label)
        return ", ".join(parts)


class Planner:
    def __init__(self, wh: Warehouse):
        self.wh = wh
        self.sem = semantic()
        first, last = wh.data_range()
        self.first_week = date.fromisoformat(first)
        self.last_week = date.fromisoformat(last)
        self.values = self._load_values()

    def _load_values(self) -> dict[str, dict[str, str]]:
        """Lowercase phrase -> canonical value, per filterable dimension."""
        q = lambda sql: [r[0] for r in self.wh.conn.execute(sql)]  # noqa: E731
        vals: dict[str, dict[str, str]] = {
            "category": {v.lower(): v for v in q("SELECT DISTINCT category FROM products")},
            "subcategory": {v.lower(): v for v in q("SELECT DISTINCT subcategory FROM products")},
            "brand": {v.lower(): v for v in q("SELECT DISTINCT brand FROM products") if v != "Bluegum"},
            "format": {f"{v.lower()} stores": v for v in q("SELECT DISTINCT format FROM stores")},
            "region": {v.lower(): v for v in q("SELECT DISTINCT region FROM stores")},
            "store": {s.lower(): n for s, n in self.wh.conn.execute("SELECT suburb, store_name FROM stores")},
            "season": {v.lower(): v for v in q("SELECT DISTINCT season FROM weeks")},
            "product": {n.lower(): n for n in q("SELECT product_name FROM products")},
        }
        for name in list(vals["category"]):
            vals["category"][name.replace("&", "and")] = vals["category"][name]
            vals["category"][name.split(" &")[0]] = vals["category"][name]  # "dairy" -> Dairy & Eggs
        vals["format"] |= {v.lower(): v for v in ["Supermarket", "Metro", "Local"] if v.lower() != "metro"}
        vals["own_brand"] = {
            "own brand": "Own brand",
            "own-brand": "Own brand",
            "bluegum brand": "Own brand",
            "private label": "Own brand",
            "branded": "Branded",
        }
        vals["promo_type"] = {
            "half price": "Half price",
            "price drop": "Price drop",
            "multi-buy": "Multi-buy",
            "multibuy": "Multi-buy",
        }
        return vals

    # ------------------------------------------------------------------ parsing

    def plan(self, question: str) -> tuple[Plan | None, str]:
        """Returns (plan, reason). A None plan means: hand this to the LLM."""
        q = question.strip()
        if NEEDS_LLM.search(q):
            return None, "needs reasoning beyond a single aggregate"
        text = " " + re.sub(r"[?!.,]", " ", q.lower()) + " "
        covered: list[tuple[int, int]] = []

        def take(pattern: str, flags=0) -> list[re.Match]:
            found = list(re.finditer(pattern, text, flags))
            covered.extend(m.span() for m in found)
            return found

        plan = Plan(metric="revenue")

        # Time first, so "may" or "march" aren't read as anything else.
        self._parse_time(text, take, plan)

        # Metric (longest synonym wins).
        metric_hits = []
        for name, m in self.sem["metrics"].items():
            for syn in m["synonyms"]:
                for hit in re.finditer(phrase_re(syn), text):
                    metric_hits.append((len(syn), name, hit.span()))
        if metric_hits:
            _, plan.metric, span = max(metric_hits)
            # Cover only the winning phrase's matches, so "margin %" doesn't also count as "margin".
            best_len = max(n for n, name, _ in metric_hits if name == plan.metric)
            covered.extend(s for n, name, s in metric_hits if name == plan.metric and n == best_len)
            covered.extend(s for n, name, s in metric_hits if any(a <= s[0] < b for a, b in covered))

        # Filters: state codes are matched case-sensitively in the original to avoid "act", "sa".
        states = [STATE_NAMES[m.group(1)] for m in take(r"\b(" + "|".join(map(re.escape, STATE_NAMES)) + r")\b")]
        for code in STATE_CODES:
            for m in re.finditer(rf"\b{code}\b", " " + re.sub(r"[?!.,]", " ", q) + " "):
                states.append(code)
                covered.append(m.span())
        if states:
            plan.filters["state"] = sorted(set(states))
        for dim in [
            "product",
            "store",
            "category",
            "subcategory",
            "brand",
            "format",
            "region",
            "season",
            "own_brand",
            "promo_type",
        ]:
            for phrase in sorted(self.values[dim], key=len, reverse=True):
                if any(phrase in text[a:b] for a, b in covered):
                    continue
                if take(phrase_re(phrase)):
                    plan.filters.setdefault(dim, [])
                    if self.values[dim][phrase] not in plan.filters[dim]:
                        plan.filters[dim].append(self.values[dim][phrase])

        # Dimensions to group by: "by X", "per X", "each X", "which X", "top 5 X", "X by sales".
        for name, d in self.sem["dimensions"].items():
            for syn in sorted(d["synonyms"], key=len, reverse=True):
                for hit in re.finditer(phrase_re(syn), text):
                    if any(a <= hit.start() < b for a, b in covered):
                        continue
                    covered.append(hit.span())
                    if name not in plan.dims:
                        plan.dims.append(name)
        if len(plan.dims) > 2:
            return None, "more than two breakdowns"

        # Ranking and limits.
        if m := re.search(r"\b(top|best|bottom|worst)\s+(\d{1,2})\b", text):
            plan.limit = int(m.group(2))
            covered.append(m.span())
        words = set(re.findall(r"[a-z]+", text))
        if words & RANK_ASC:
            plan.order = "asc"
        if re.search(r"\b(which|what)\b", text) and words & (RANK_DESC | RANK_ASC) and not plan.limit:
            plan.limit = 5
        if re.search(r"\b(trend|over time|weekly|monthly)\b", text) and not any(
            d in plan.dims for d in ("week", "month", "quarter", "year")
        ):
            plan.dims.append("week" if self._span_weeks(plan) <= 26 else "month")

        time_dims = [d for d in plan.dims if d in ("week", "month", "quarter", "year")]
        if time_dims:
            plan.order, plan.chart = "time", "line"
            plan.limit = None
        elif plan.dims:
            plan.chart = "bar"

        # Coverage: refuse if meaningful words are left over.
        leftovers = [
            w
            for w in re.finditer(r"[a-z0-9&'-]+", text)
            if w.group() not in STOPWORDS
            and w.group() not in GLUE
            and not w.group().isdigit()
            and not any(a <= w.start() < b for a, b in covered)
        ]
        if leftovers:
            return None, "didn't understand: " + ", ".join(sorted({w.group() for w in leftovers}))
        if not metric_hits and not plan.dims and not plan.filters:
            return None, "no metric or breakdown found"
        return plan, "ok"

    def _uplift_by_promo_type(self, plan: Plan) -> str:
        """Uplift vs each product's own non-promo baseline in the same store (a matched comparison)."""
        dims = self.sem["dimensions"]
        other = [d for d in plan.dims if d != "promo_type"]
        joins = (
            "JOIN stores ON stores.store_id = sales.store_id\nJOIN products ON products.product_id = sales.product_id\n"
        )
        joins += "JOIN weeks ON weeks.week_start = sales.week_start"
        where = _where_clauses(plan, dims)
        base_where = " AND ".join(where + ["sales.on_promo = 0"])
        promo_where = "\n  AND ".join(where + ["sales.on_promo = 1"])
        select = [f"{dims[d]['sql']} AS {d}" for d in other] + ["promotions.promo_type AS promo_type"]
        group = other + ["promo_type"]
        return (
            "WITH baseline AS (\n  SELECT sales.product_id, sales.store_id, AVG(sales.units) AS base_units\n"
            f"  FROM sales\n  {joins.replace(chr(10), chr(10) + '  ')}\n  WHERE {base_where}\n"
            "  GROUP BY sales.product_id, sales.store_id\n)\n"
            f"SELECT {', '.join(select)},\n"
            "  100.0 * (AVG(sales.units * 1.0 / NULLIF(baseline.base_units, 0)) - 1) AS value\n"
            f"FROM sales\n{joins}\n"
            "JOIN baseline ON baseline.product_id = sales.product_id AND baseline.store_id = sales.store_id\n"
            "JOIN promotions ON promotions.product_id = sales.product_id AND promotions.week_start = sales.week_start\n"
            f"WHERE {promo_where}\nGROUP BY {', '.join(group)}\nORDER BY value DESC"
        )

    def _span_weeks(self, plan: Plan) -> int:
        a = date.fromisoformat(plan.week_from) if plan.week_from else self.first_week
        b = date.fromisoformat(plan.week_to) if plan.week_to else self.last_week
        return (b - a).days // 7 + 1

    def _parse_time(self, text: str, take, plan: Plan) -> None:
        last = self.last_week
        data_end = last + timedelta(days=6)
        cur_month = (last.year, last.month)
        last_full_month = cur_month if data_end.month != last.month else _prev_month(*cur_month)
        quarter_of = lambda d: (d.year, (d.month - 1) // 3 + 1)  # noqa: E731
        q_now = quarter_of(last)
        last_full_q = q_now if quarter_of(data_end) != q_now else _prev_q(*q_now)

        def month_range(y: int, m: int, label: str) -> None:
            start = date(y, m, 1)
            end = date(y + (m == 12), m % 12 + 1, 1)
            plan.week_from, plan.week_to, plan.time_label = (
                start.isoformat(),
                (end - timedelta(days=1)).isoformat(),
                label,
            )

        if m := take(r"\blast (\d{1,3}) weeks\b") or take(r"\bpast (\d{1,3}) weeks\b"):
            n = int(m[0].group(1))
            plan.week_from = (last - timedelta(weeks=n - 1)).isoformat()
            plan.time_label = f"in the last {n} weeks"
        elif take(r"\b(last|latest|past|previous) week\b"):
            plan.week_from = plan.week_to = last.isoformat()
            plan.time_label = f"in the week starting {last:%-d %b %Y}"
        elif m := take(r"\blast (\d{1,2}) months\b") or take(r"\bpast (\d{1,2}) months\b"):
            n = int(m[0].group(1))
            y, mo = last_full_month
            for _ in range(n - 1):
                y, mo = _prev_month(y, mo)
            plan.week_from = date(y, mo, 1).isoformat()
            plan.time_label = f"over the last {n} months"
        elif take(r"\b(last|latest|past|previous) month\b"):
            month_range(*last_full_month, f"in {date(*last_full_month, 1):%B %Y}")
        elif take(r"\b(last|latest|previous) quarter\b"):
            y, qn = last_full_q
            plan.week_from = date(y, 3 * qn - 2, 1).isoformat()
            plan.week_to = (date(y + (qn == 4), (3 * qn) % 12 + 1, 1) - timedelta(days=1)).isoformat()
            plan.time_label = f"in {y}-Q{qn}"
        elif take(r"\b(this year|year to date|ytd|so far this year)\b"):
            plan.week_from = date(last.year, 1, 1).isoformat()
            plan.time_label = f"in {last.year} so far"
        elif take(r"\blast year\b"):
            plan.week_from, plan.week_to = (
                date(last.year - 1, 1, 1).isoformat(),
                date(last.year - 1, 12, 31).isoformat(),
            )
            plan.time_label = f"in {last.year - 1}"
        elif m := take(r"\b(?:q([1-4])\s*(20\d\d)|(20\d\d)\s*q([1-4]))\b"):
            qn, y = (
                (int(m[0].group(1)), int(m[0].group(2))) if m[0].group(1) else (int(m[0].group(4)), int(m[0].group(3)))
            )
            plan.week_from = date(y, 3 * qn - 2, 1).isoformat()
            plan.week_to = (date(y + (qn == 4), (3 * qn) % 12 + 1, 1) - timedelta(days=1)).isoformat()
            plan.time_label = f"in {y}-Q{qn}"
        elif m := take(r"\b(" + "|".join(MONTHS) + r")\s+(20\d\d)\b"):
            mo, y = MONTHS[m[0].group(1)], int(m[0].group(2))
            month_range(y, mo, f"in {date(y, mo, 1):%B %Y}")
        elif m := take(r"\b(?:in |during |for )?(20\d\d)\b"):
            y = int(m[0].group(1))
            plan.week_from, plan.week_to, plan.time_label = f"{y}-01-01", f"{y}-12-31", f"in {y}"

    # ------------------------------------------------------------------ SQL

    def to_sql(self, plan: Plan) -> str:
        if plan.metric == "promo_uplift" and "promo_type" in plan.dims:
            return self._uplift_by_promo_type(plan)
        metric = self.sem["metrics"][plan.metric]
        dims = self.sem["dimensions"]
        tables = {"sales"} | set(metric.get("needs", []))
        tables |= {dims[d]["table"] for d in plan.dims} | {dims[f]["table"] for f in plan.filters}
        if plan.week_from or plan.week_to:
            tables.add("sales")

        select = [f"{dims[d]['sql']} AS {d}" for d in plan.dims] + [f"{metric['sql'].strip()} AS value"]
        joins = []
        if "stores" in tables:
            joins.append("JOIN stores ON stores.store_id = sales.store_id")
        if "products" in tables:
            joins.append("JOIN products ON products.product_id = sales.product_id")
        if "weeks" in tables:
            joins.append("JOIN weeks ON weeks.week_start = sales.week_start")
        if "promotions" in tables:
            joins.append(
                "LEFT JOIN promotions ON promotions.product_id = sales.product_id "
                "AND promotions.week_start = sales.week_start"
            )

        where = _where_clauses(plan, dims)

        sql = "SELECT " + ", ".join(select) + "\nFROM sales"
        if joins:
            sql += "\n" + "\n".join(joins)
        if where:
            sql += "\nWHERE " + "\n  AND ".join(where)
        if plan.dims:
            sql += "\nGROUP BY " + ", ".join(plan.dims)
            if plan.order == "time":
                sql += "\nORDER BY " + ", ".join(plan.dims)
            else:
                sql += f"\nORDER BY value {'ASC' if plan.order == 'asc' else 'DESC'}"
        if plan.limit:
            sql += f"\nLIMIT {plan.limit}"
        return sql


def _where_clauses(plan: Plan, dims: dict) -> list[str]:
    where = []
    for dim, values in plan.filters.items():
        quoted = ", ".join("'" + v.replace("'", "''") + "'" for v in values)
        where.append(f"{dims[dim]['sql']} IN ({quoted})")
    if plan.week_from:
        where.append(f"sales.week_start >= '{plan.week_from}'")
    if plan.week_to:
        where.append(f"sales.week_start <= '{plan.week_to}'")
    return where


def _prev_month(y: int, m: int) -> tuple[int, int]:
    return (y - 1, 12) if m == 1 else (y, m - 1)


def _prev_q(y: int, q: int) -> tuple[int, int]:
    return (y - 1, 4) if q == 1 else (y, q - 1)


def fmt(value, kind: str) -> str:
    if value is None:
        return "n/a"
    if kind == "money":
        return (
            f"${value / 1e6:,.2f}M"
            if abs(value) >= 1e6
            else f"${value:,.0f}"
            if abs(value) >= 1000
            else f"${value:,.2f}"
        )
    if kind == "percent":
        return f"{value:.1f}%"
    return f"{value:,.0f}"


def narrate(plan: Plan, columns: list[str], rows: list[list]) -> str:
    """A plain-English answer built only from the result rows."""
    metric = semantic()["metrics"][plan.metric]
    label, kind = metric["label"], metric["format"]
    scope = "".join(f" for {', '.join(v)}" for v in plan.filters.values())
    if not rows or rows[0][-1] is None:
        return f"There's no data for that ({plan.describe()})."
    if not plan.dims:
        return f"{label}{scope} {plan.time_label}: {fmt(rows[0][-1], kind)}."
    if plan.order == "time":
        values = [r[-1] for r in rows if r[-1] is not None]
        hi = max(rows, key=lambda r: r[-1] or 0)
        lo = min(rows, key=lambda r: r[-1] or 0)
        name = lambda r: " / ".join(str(x) for x in r[:-1])  # noqa: E731
        return (
            f"{label}{scope} {plan.time_label} peaked at {fmt(hi[-1], kind)} ({name(hi)}) and was lowest at "
            f"{fmt(lo[-1], kind)} ({name(lo)}). Latest: {fmt(rows[-1][-1], kind)} ({name(rows[-1])}). "
            f"{len(values)} periods shown."
        )
    name = lambda r: " / ".join(str(x) for x in r[:-1])  # noqa: E731
    lead = "Lowest" if plan.order == "asc" else "Highest"
    text = f"{lead} {label.lower()}{scope} {plan.time_label}: {name(rows[0])} at {fmt(rows[0][-1], kind)}"
    if len(rows) > 1:
        text += f", then {name(rows[1])} at {fmt(rows[1][-1], kind)}"
    if len(rows) > 2:
        text += f" and {name(rows[2])} at {fmt(rows[2][-1], kind)}"
    return text + "."
