#!/usr/bin/env python3
"""Deterministic six-month revenue scorer for Countermove leaves.

The command-line interface accepts a JSON file containing ``company``, ``move``,
and ``leaf`` objects.  The score result is written to stdout; a trace event for
the sandbox boundary is written to stderr.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


MONTHS = 6
DEFAULT_ROLLBACK_FRACTION = 0.5
DEFAULT_ANNUAL_DISCOUNT_RATE = 0.10
DEFAULT_ANNUAL_DISCOUNT_UPTAKE = 0.30
C_PRIME_CONVENTION = (
    "mean of all three competitors' price_after; non-responders keep last "
    "scraped price"
)
BANDS = ("low", "mid", "high")


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(value, high))


def expand_elasticity(value: float | Mapping[str, float]) -> dict[str, float]:
    """Return the required low/mid/high own-price elasticity range."""
    if isinstance(value, Mapping):
        try:
            return {band: float(value[band]) for band in BANDS}
        except KeyError as exc:
            raise ValueError(f"elasticity range is missing {exc.args[0]!r}") from exc

    mid = float(value)
    # Decimal-looking business inputs should remain decimal-looking in emitted
    # assumptions instead of exposing binary floating-point representation.
    return {
        "low": round(mid - 0.15, 12),
        "mid": mid,
        # The spec pins "high clamped below 0": strictly negative, never 0.
        "high": min(round(mid + 0.15, 12), -0.01),
    }


def price_factor(
    current_price: float,
    resulting_price: float,
    competitor_price: float,
    competitor_price_after: float,
    elasticity: float,
    cross_elasticity: float,
) -> float:
    """Calculate demand retention, capped so price advantages add no customers."""
    if current_price <= 0 or competitor_price <= 0:
        raise ValueError("current and competitor prices must be greater than zero")
    if resulting_price <= 0 or competitor_price_after <= 0:
        raise ValueError("prices must be strictly positive")
    factor = ((resulting_price / current_price) ** elasticity) * (
        (competitor_price_after / competitor_price) ** cross_elasticity
    )
    return clamp(factor, 0.0, 1.0)


def surviving_customer_months(customers: float, monthly_churn: float, months: int) -> float:
    if customers < 0:
        raise ValueError("customers cannot be negative")
    if not 0 <= monthly_churn <= 1:
        raise ValueError("monthly churn must be between zero and one")
    return customers * sum((1.0 - monthly_churn) ** month for month in range(1, months + 1))


def _number(source: Mapping[str, Any], names: Sequence[str], default: float) -> float:
    for name in names:
        if name in source:
            return float(source[name])
    return default


def counter_terms(move: Mapping[str, Any], leaf: Mapping[str, Any], customers: float, months: int) -> tuple[float, float, dict]:
    """Return resulting own price, once-per-segment cost, and resolved parameters."""
    assumptions = leaf.get("assumptions") or {}
    counter_assumptions = assumptions.get("counter") or {}
    if not isinstance(counter_assumptions, Mapping):
        raise ValueError("leaf assumptions.counter must be an object")

    choice = leaf.get("choice", "hold")
    old_price = float(move["from"])
    moved_price = float(move["to"])
    if choice == "hold":
        return moved_price, 0.0, {"choice": choice}
    if choice == "partial_rollback":
        fraction = _number(
            counter_assumptions,
            ("rollback_fraction", "fraction"),
            _number(assumptions, ("rollback_fraction", "partial_rollback_fraction"), DEFAULT_ROLLBACK_FRACTION),
        )
        if not 0 <= fraction <= 1:
            raise ValueError("rollback fraction must be between zero and one")
        return (moved_price + fraction * (old_price - moved_price), 0.0,
                {"choice": choice, "rollback_fraction": fraction})
    if choice == "annual_discount":
        rate = _number(
            counter_assumptions,
            ("annual_discount_rate", "discount_rate"),
            _number(assumptions, ("annual_discount_rate", "discount_rate"), DEFAULT_ANNUAL_DISCOUNT_RATE),
        )
        uptake = _number(
            counter_assumptions,
            ("annual_discount_uptake", "uptake"),
            _number(assumptions, ("annual_discount_uptake", "uptake"), DEFAULT_ANNUAL_DISCOUNT_UPTAKE),
        )
        if rate < 0 or not 0 <= uptake <= 1:
            raise ValueError("discount rate must be nonnegative and uptake between zero and one")
        cost = (rate * moved_price * months) * (uptake * customers)
        return moved_price, cost, {"choice": choice, "discount_rate": rate, "uptake": uptake}
    raise ValueError(f"unsupported counter choice: {choice!r}")


def _mean(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("at least one competitor price is required")
    return math.fsum(values) / len(values)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def competitor_prices(company: Mapping[str, Any], move: Mapping[str, Any], leaf: Mapping[str, Any]) -> tuple[float, float]:
    """Resolve C and C' from visible leaf assumptions or its response reference."""
    competitors = company.get("competitors") or []
    before_by_name = {str(item["name"]): float(item["price"]) for item in competitors}
    before = _mean(list(before_by_name.values()))
    assumptions = leaf.get("assumptions") or {}

    c = _number(assumptions, ("c", "competitor_average_before", "competitor_price"), before)
    for container in (assumptions, leaf):
        for key in ("c_prime", "competitor_average_after", "competitor_price_after"):
            if key in container:
                return c, float(container[key])
        prices = container.get("competitor_prices_after")
        if isinstance(prices, Mapping):
            return c, _mean([float(value) for value in prices.values()])
        if isinstance(prices, list):
            return c, _mean([float(value) for value in prices])

    response = leaf.get("competitor_response")
    if isinstance(response, Mapping):
        response_name = str(response["name"])
        after_by_name = dict(before_by_name)
        after_by_name[response_name] = float(response["price_after"])
        return c, _mean(list(after_by_name.values()))

    # Frozen fixture leaves point to response nodes by this stable id convention.
    parent = str(leaf.get("parent", ""))
    for name, old_price in before_by_name.items():
        prefix = f"resp-{_slug(name)}-"
        if parent.startswith(prefix):
            choice = parent[len(prefix):]
            moved_price = float(move["to"])
            response_prices = {
                "undercut": moved_price * 0.95,
                "match": moved_price,
                "ignore": old_price,
                "raise": old_price * 1.05,
            }
            if choice in response_prices:
                after_by_name = dict(before_by_name)
                after_by_name[name] = response_prices[choice]
                return c, _mean(list(after_by_name.values()))
    raise ValueError(
        "leaf carries no competitor price resolution: expected assumptions overrides "
        "or a parent id of the form resp-<competitor>-<choice>"
    )


def _plan(company: Mapping[str, Any], plan_id: str) -> Mapping[str, Any]:
    for plan in company.get("plans", []):
        if plan.get("id") == plan_id:
            return plan
    raise ValueError(f"company has no plan {plan_id!r}")


def _elasticities(segment: Mapping[str, Any], leaf: Mapping[str, Any]) -> dict[str, float]:
    assumptions = leaf.get("assumptions") or {}
    supplied = assumptions.get("eps", segment.get("elasticity"))
    if isinstance(supplied, Mapping) and segment.get("id") in supplied:
        supplied = supplied[segment["id"]]
    if supplied is None:
        raise ValueError(f"segment {segment.get('id')!r} has no elasticity")
    return expand_elasticity(supplied)


def score_leaf(company: Mapping[str, Any], move: Mapping[str, Any], leaf: Mapping[str, Any], months: int = MONTHS) -> dict[str, Any]:
    """Score one leaf at each elasticity band and return the contract shape."""
    if months <= 0:
        raise ValueError("months must be positive")
    plan = _plan(company, str(move["plan"]))
    current_price = float(move["from"])
    if not math.isclose(float(plan["price"]), current_price):
        raise ValueError("move.from must equal the company's current plan price")
    c, c_prime = competitor_prices(company, move, leaf)
    totals = {band: 0.0 for band in BANDS}
    baseline_revenue = 0.0
    ranges: dict[str, dict[str, float]] = {}
    etas: dict[str, float] = {}

    for segment in plan.get("segments", []):
        segment_id = str(segment["id"])
        customers = float(segment["customers"])
        churn = float(segment["monthly_churn"])
        eta = float((leaf.get("assumptions") or {}).get("eta", segment.get("cross_elasticity", 0.4)))
        etas[segment_id] = eta
        eps = _elasticities(segment, leaf)
        ranges[segment_id] = eps
        organic_customer_months = surviving_customer_months(customers, churn, months)
        baseline_revenue += organic_customer_months * current_price
        resulting_price, move_cost, counter_params = counter_terms(move, leaf, customers, months)
        for band in BANDS:
            factor = price_factor(current_price, resulting_price, c, c_prime, eps[band], eta)
            totals[band] += organic_customer_months * factor * resulting_price - move_cost

    scores = {band: totals[band] - baseline_revenue for band in BANDS}
    assumptions_out: dict[str, Any] = {
        "eps": next(iter(ranges.values())) if len(ranges) == 1 else ranges,
        # Displayed eta mirrors the per-segment values actually used in the loop.
        "eta": next(iter(etas.values())) if len(etas) == 1 else etas,
        "c_prime_convention": C_PRIME_CONVENTION,
        "competitor_average_before": c,
        "competitor_average_after": c_prime,
        "months": months,
        "counter": counter_params,
    }
    result: dict[str, Any] = {"leaf_id": str(leaf["id"])}
    for band in BANDS:
        result[band] = scores[band]
        result[f"{band}_pct"] = "n/a" if baseline_revenue == 0 else 100.0 * scores[band] / baseline_revenue
    result["assumptions"] = assumptions_out
    return result


def trace_event(input_data: Mapping[str, Any], output: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "actor": "scorer",
        "column": "did",
        "text": "scored a pricing response in the sandbox",
        "tool": "trueforge.sandbox.exec",
        "detail": {"input": input_data, "output": output},
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: python3 score.py <input.json>", file=sys.stderr)
        return 2
    try:
        input_data = json.loads(Path(args[0]).read_text(encoding="utf-8"))
        result = score_leaf(input_data["company"], input_data["move"], input_data["leaf"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"score.py: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    print(json.dumps(trace_event(input_data, result), separators=(",", ":"), sort_keys=True), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
