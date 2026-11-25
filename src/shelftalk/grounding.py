"""Numeric grounding: every number in a model's answer must be traceable to the query results.

LLMs are good at writing about data and bad at copying numbers exactly. This check pulls every
number out of the answer ("$7.9M", "14.3%", "42,105") and looks for a matching value in the
results, allowing for the rounding a person would do. Anything it can't trace is flagged in the
UI and counted in the evals.
"""

from __future__ import annotations

import re

NUMBER = re.compile(
    r"(?<![\w.])(-?\$?\s?\d[\d,]*(?:\.\d+)?)\s*(%|k\b|m\b|mn\b|million|b\b|bn\b|billion|thousand)?",
    re.I,
)
SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9}


def numbers_in(text: str) -> list[tuple[str, float, int]]:
    """(as written, value, decimals shown) for each number in the text."""
    out = []
    for m in NUMBER.finditer(text):
        raw, unit = m.group(1), (m.group(2) or "").lower()
        digits = raw.replace("$", "").replace(",", "").strip()
        try:
            value = float(digits)
        except ValueError:
            continue
        decimals = len(digits.split(".")[1]) if "." in digits else 0
        value *= SCALE.get(unit, 1)
        # Precision shown: "$7.92M" is precise to $10,000, so its effective decimals are 2 - 6 = -4.
        exponent = len(str(int(SCALE[unit]))) - 1 if unit in SCALE else 0
        out.append((m.group(0).strip(), value, decimals - exponent))
    return out


def _matches(claim: float, shown_decimals: int, candidates: list[float]) -> bool:
    for c in candidates:
        if c == 0:
            if claim == 0:
                return True
            continue
        # Exact after the rounding the writer applied, or within 0.5% (e.g. $7.92M for 7,918,233).
        step = 10.0 ** (-shown_decimals)
        if abs(claim - c) <= step / 2 + 1e-9 or abs(claim - c) / abs(c) <= 0.005:
            return True
    return False


def ungrounded(answer: str, result_sets: list[dict], question: str = "") -> list[str]:
    """Numbers in the answer that don't match any value in any result (or the question)."""
    candidates: list[float] = []
    for rs in result_sets:
        for row in rs.get("rows", []):
            for v in row:
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    candidates.append(float(v))
                elif isinstance(v, str):
                    candidates.extend(n for _, n, _ in numbers_in(v))
    candidates += [n for _, n, _ in numbers_in(question)]
    flagged = []
    for raw, value, decimals in numbers_in(answer):
        if 1990 <= value <= 2100 and decimals == 0:  # years
            continue
        if value == int(value) and 0 <= value <= 12 and decimals == 0:  # counts like "top 5", months
            continue
        if not _matches(value, decimals, candidates):
            flagged.append(raw)
    return flagged
