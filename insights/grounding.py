"""Checks that recommendations are grounded in the account's actual data.

LLMs can sound confident about numbers they made up. This check pulls every number
out of a recommendation's `evidence` text and looks for it in the computed stats
(lifts, rates, post counts, reach...). It also checks that the format exists in the
data and that any post IDs it says it's based on are real posts.

It is deliberately simple - a sanity check, not a proof - but it catches the
failure that matters most for this product: invented statistics.
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Set, Tuple

NUM_RE = re.compile(r"(?<![\w.])(\d+(?:,\d{3})*(?:\.\d+)?)\s*(x|%)?", re.I)


def _walk(obj, key: str = "") -> Iterable[Tuple[str, object]]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk(v, k)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v, key)
    else:
        yield key, obj


def known_values(stats: Dict) -> Tuple[Set[float], Set[float], Set[float]]:
    """Returns (multipliers, percentages, plain numbers) present in the stats.

    "1.33x" may only match a lift (a real multiplier), never an arbitrary number
    that happens to be 1.33 - otherwise any invented multiplier could slip through."""
    mult, pct, plain = set(), set(), set()
    for key, v in _walk(stats):
        if isinstance(v, bool) or v is None:
            continue
        if isinstance(v, (int, float)):
            f = float(v)
            plain.add(f)
            if "lift" in key:
                mult.add(round(f, 2))
            if "rate" in key or "change" in key:
                for g in (f, abs(f)):  # abs: "down 6%" cites a change stored as -0.0613
                    pct.add(round(g * 100, 2))  # stored as fractions
            pct.add(round(f, 2))
        elif isinstance(v, str):  # labels like "evening (18-22)", "3-6", dates
            for m in NUM_RE.finditer(v):
                plain.add(float(m.group(1).replace(",", "")))
    return mult, pct, plain


def _matches(value: float, unit: str, known: Tuple[Set[float], Set[float], Set[float]]) -> bool:
    mult, pct, plain = known
    if unit == "x":
        return any(abs(value - k) <= 0.011 for k in mult)
    if unit == "%":
        # accept rounding to 0 or 1 decimal places (e.g. 5.63% cited as 5.6% or 6%)
        return any(abs(value - k) <= 0.51 for k in pct) if value == int(value) else any(abs(value - k) <= 0.051 for k in pct)
    return any(abs(value - k) <= 0.51 for k in plain)


def check_text(text: str, known) -> Tuple[int, List[str]]:
    """Returns (numbers cited, numbers not found in the data) for any free text."""
    cited, unmatched = 0, []
    for m in NUM_RE.finditer(text or ""):
        raw, unit = m.group(1), (m.group(2) or "").lower()
        cited += 1
        if not _matches(float(raw.replace(",", "")), unit, known):
            unmatched.append(raw + unit)
    return cited, unmatched


def check_recommendation(rec: Dict, stats: Dict, known=None) -> Dict:
    known = known or known_values(stats)
    cited, unmatched = check_text(rec.get("evidence", ""), known)

    real_posts = {p["id"] for p in stats.get("top_posts", []) + stats.get("bottom_posts", [])}
    bad_posts = [pid for pid in rec.get("based_on_posts", []) if pid not in real_posts]
    formats = {s["segment"] for s in stats.get("by_format", [])}
    format_ok = rec.get("format") in formats or not formats

    return {
        "numbers_cited": cited,
        "numbers_matched": cited - len(unmatched),
        "unmatched_numbers": unmatched,
        "unknown_posts": bad_posts,
        "format_in_data": format_ok,
        "grounded": cited > 0 and not unmatched and not bad_posts and format_ok,
    }


def check_all(recs: Dict, stats: Dict) -> Dict:
    """Adds a `grounding` block to each recommendation and a summary to `recs`."""
    known = known_values(stats)
    items: List[Dict] = recs.get("recommendations", [])
    for rec in items:
        rec["grounding"] = check_recommendation(rec, stats, known)
    ok = sum(r["grounding"]["grounded"] for r in items)
    # Also check the free text around the recommendations: summary and improvement evidence.
    texts = [recs.get("summary", "")] + [u.get("evidence", "") for u in recs.get("underperforming", [])]
    cited, unmatched = 0, []
    for t in texts:
        c, u = check_text(t, known)
        cited, unmatched = cited + c, unmatched + u
    recs["grounding_summary"] = {"verified": ok, "total": len(items),
                                 "other_numbers_cited": cited, "other_numbers_unmatched": unmatched}
    return recs
