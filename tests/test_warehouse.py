import pytest

from shelftalk.warehouse import QueryError

ATTACKS = {
    "pii column": "SELECT email FROM loyalty_members",
    "pii via star": "SELECT * FROM loyalty_members",
    "pii in subquery": (
        "SELECT tier FROM loyalty_members "
        "WHERE member_id IN (SELECT member_id FROM loyalty_members WHERE phone LIKE '04%')"
    ),
    "pii in materialised cte": "WITH x AS MATERIALIZED (SELECT first_name FROM loyalty_members) SELECT count(*) FROM x",
    "delete": "DELETE FROM sales",
    "update": "UPDATE products SET regular_price = 0",
    "drop": "DROP TABLE sales",
    "stacked statements": "SELECT 1; DROP TABLE sales",
    "pragma": "PRAGMA table_info(sales)",
    "attach": "ATTACH DATABASE 'x.db' AS x",
    "system table": "SELECT sql FROM sqlite_master",
    "extension": "SELECT load_extension('evil')",
    "runaway recursion": "WITH RECURSIVE r(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM r) SELECT count(*) FROM r",
    "cross join bomb": "SELECT count(*) FROM sales a, sales b",
}


@pytest.mark.parametrize("sql", ATTACKS.values(), ids=ATTACKS.keys())
def test_attacks_are_refused(wh, sql):
    with pytest.raises(QueryError):
        wh.query(sql)
    assert wh.query("SELECT COUNT(*) FROM sales").rows[0][0] > 200_000  # data untouched


def test_refusal_messages_are_helpful(wh):
    with pytest.raises(QueryError, match="personal information"):
        wh.query("SELECT email FROM loyalty_members")


def test_aggregates_over_the_pii_table_are_allowed(wh):
    rows = wh.query("SELECT tier, COUNT(*) FROM loyalty_members GROUP BY tier").rows
    assert {r[0] for r in rows} == {"Bronze", "Silver", "Gold"}


def test_ctes_and_bounded_recursion_work(wh):
    assert wh.query("WITH x AS (SELECT store_id FROM sales GROUP BY 1) SELECT COUNT(*) FROM x").rows == [[28]]
    assert wh.query(
        "WITH RECURSIVE r(i) AS (SELECT 1 UNION ALL SELECT i+1 FROM r WHERE i < 4) SELECT SUM(i) FROM r"
    ).rows == [[10]]


def test_row_cap(wh):
    result = wh.query("SELECT * FROM sales")
    assert len(result.rows) == wh.max_rows and result.truncated


def test_schema_context_marks_pii_and_lists_values(wh):
    text = wh.describe()
    assert "email: PII  [PII: cannot be selected]" in text
    assert "values of state:" in text and "promo_uplift:" in text
