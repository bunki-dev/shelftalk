"""Read-only access to the warehouse, with guardrails enforced by the database engine.

Text-to-SQL is only safe if a bad query can't do damage, so this doesn't rely on spotting
dangerous SQL with string checks. Instead:
  * the database is opened read-only;
  * SQLite's authorizer approves every operation the compiled query will perform: only reads
    of allowed tables, never personal-data columns, and no writes, PRAGMAs, ATTACH or risky
    functions, wherever they hide (subqueries, CTEs, views);
  * one statement per call, a time budget and a row cap.
The same policy maps onto a production warehouse: a read-only role, column masking policies
and statement timeouts in Snowflake.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from pathlib import Path

import yaml

MAX_ROWS = 500
TIME_BUDGET_S = 3.0
BLOCKED_FUNCTIONS = {"load_extension", "readfile", "writefile", "edit", "fts3_tokenizer", "zipfile", "sqlar_compress"}
# Low-cardinality columns whose values help a model write correct filters.
SAMPLE_VALUE_COLUMNS = {
    "stores": ["state", "region", "format"],
    "products": ["category", "brand"],
    "weeks": ["season", "year"],
    "promotions": ["promo_type"],
    "loyalty_members": ["tier"],
}


class QueryError(Exception):
    """The query was refused or failed. The message is safe to show to the user and the model."""


@dataclass
class QueryResult:
    sql: str
    columns: list[str]
    rows: list[list]
    truncated: bool = False
    elapsed_ms: float = 0.0
    notes: list[str] = field(default_factory=list)

    def to_dict(self, max_rows: int | None = None) -> dict:
        rows = self.rows if max_rows is None else self.rows[:max_rows]
        return {
            "sql": self.sql,
            "columns": self.columns,
            "rows": rows,
            "row_count": len(self.rows),
            "truncated": self.truncated or (max_rows is not None and len(self.rows) > max_rows),
            "elapsed_ms": self.elapsed_ms,
        }


@lru_cache(maxsize=1)
def semantic() -> dict:
    return yaml.safe_load(resources.files("shelftalk.data").joinpath("semantic.yml").read_text())


class Warehouse:
    def __init__(self, path: str | Path, max_rows: int = MAX_ROWS, time_budget_s: float = TIME_BUDGET_S):
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(f"No warehouse at {self.path}. Run: python -m shelftalk.generate {self.path}")
        self.max_rows = max_rows
        self.time_budget_s = time_budget_s
        self.conn = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, check_same_thread=False)
        self.allowed_tables = set(semantic()["tables"])
        # Real tables in the file. Any other name a query reads from is a CTE or subquery alias,
        # whose underlying reads are checked separately.
        self.real_tables = {
            r[0] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")
        }
        self.pii = {(t, c) for t, cols in semantic().get("pii_columns", {}).items() for c in cols}
        self._deny_reason: str | None = None

    # ---------- the policy ----------

    def _authorize(self, action, arg1, arg2, db_name, trigger) -> int:
        if action == sqlite3.SQLITE_SELECT:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ:
            table, column = arg1, arg2
            is_system = (table or "").lower().startswith("sqlite_")
            if table not in self.allowed_tables and (table in self.real_tables or is_system):
                self._deny_reason = f"Table '{table}' isn't available."
                return sqlite3.SQLITE_DENY
            if (table, column) in self.pii:
                self._deny_reason = (
                    f"'{table}.{column}' is personal information and can't be queried. "
                    "Aggregate counts and spend by tier or store are fine."
                )
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_FUNCTION:
            if (arg2 or "").lower() in BLOCKED_FUNCTIONS:
                self._deny_reason = f"The function {arg2}() isn't allowed."
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        if action == getattr(sqlite3, "SQLITE_RECURSIVE", 33):
            return sqlite3.SQLITE_OK  # recursive CTEs are fine; the time budget bounds them
        self._deny_reason = "Only read-only SELECT queries are allowed."
        return sqlite3.SQLITE_DENY

    # ---------- running queries ----------

    def query(self, sql: str) -> QueryResult:
        sql = sql.strip().rstrip(";").strip()
        if not sql:
            raise QueryError("Empty query.")
        if len(sql) > 8000:
            raise QueryError("That query is too long.")
        self._deny_reason = None
        deadline = time.monotonic() + self.time_budget_s
        self.conn.set_authorizer(self._authorize)
        self.conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 20000)
        start = time.perf_counter()
        try:
            cur = self.conn.execute(sql)
            columns = [d[0] for d in cur.description or []]
            rows = cur.fetchmany(self.max_rows + 1)
        except sqlite3.DatabaseError as e:
            msg = str(e)
            if self._deny_reason:
                raise QueryError(self._deny_reason) from e
            if "interrupted" in msg:
                raise QueryError(
                    f"The query took longer than {self.time_budget_s:g}s. Aggregate more or filter."
                ) from e
            if "one statement at a time" in msg:
                raise QueryError("Send one SELECT statement at a time.") from e
            raise QueryError(f"SQL error: {msg}") from e
        finally:
            self.conn.set_authorizer(None)
            self.conn.set_progress_handler(None, 0)
        truncated = len(rows) > self.max_rows
        clean = [[_clean(v) for v in row] for row in rows[: self.max_rows]]
        return QueryResult(
            sql=sql,
            columns=columns,
            rows=clean,
            truncated=truncated,
            elapsed_ms=round((time.perf_counter() - start) * 1000, 1),
        )

    # ---------- context for the model ----------

    @lru_cache(maxsize=1)  # noqa: B019 - one warehouse per process
    def data_range(self) -> tuple[str, str]:
        first, last = self.conn.execute("SELECT MIN(week_start), MAX(week_start) FROM sales").fetchone()
        return first, last

    @lru_cache(maxsize=1)  # noqa: B019
    def describe(self) -> str:
        """Schema, meanings, PII rules, sample values and metric definitions, as compact text."""
        sem = semantic()
        lines = [
            sem["business"].strip(),
            f"Data covers weeks starting {self.data_range()[0]} to {self.data_range()[1]}.",
            "",
        ]
        for table, info in sem["tables"].items():
            lines.append(f"TABLE {table}: {info['description']}")
            for col, meaning in info["columns"].items():
                flag = "  [PII: cannot be selected]" if (table, col) in self.pii else ""
                lines.append(f"  - {col}: {meaning}{flag}")
            for col in SAMPLE_VALUE_COLUMNS.get(table, []):
                values = [r[0] for r in self.conn.execute(f"SELECT DISTINCT {col} FROM {table} ORDER BY 1 LIMIT 15")]
                lines.append(f"    values of {col}: {', '.join(map(str, values))}")
        lines += ["", "JOINS:"] + [f"  {j}" for j in sem["joins"]]
        lines += ["", "METRIC DEFINITIONS (use these exact formulas):"]
        lines += [f"  {name}: {m['sql'].strip()}" for name, m in sem["metrics"].items()]
        return "\n".join(lines)


def _clean(v):
    if isinstance(v, float):
        return round(v, 4)
    if isinstance(v, bytes):
        return "<binary>"
    if isinstance(v, str) and len(v) > 200:
        return v[:200] + "…"
    return v


def default_db_path() -> Path:
    import os

    return Path(os.getenv("SHELFTALK_DB", Path.home() / ".cache" / "shelftalk" / "shelftalk.db"))


def open_default() -> Warehouse:
    """Open the demo warehouse, generating it on first use."""
    path = default_db_path()
    if not path.exists():
        from .generate import build

        build(path)
    return Warehouse(path)
