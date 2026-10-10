"""Budget arithmetic over amounts supplied by the user. No live prices."""

import math
import re


def _amount(name, value, errors, *, minimum=0.0, maximum=1e12):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        errors.append(f"{name} must be a number.")
        return None
    if not math.isfinite(value):
        errors.append(f"{name} must be a finite number.")
        return None
    if value < minimum:
        errors.append(f"{name} cannot be negative." if minimum == 0 else f"{name} is too small.")
        return None
    if value > maximum:
        errors.append(f"{name} is unrealistically large.")
        return None
    return float(value)


def _whole(name, value, errors, *, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        errors.append(f"{name} must be a whole number.")
        return None
    if value != int(value):
        errors.append(f"{name} must be a whole number (got {value}).")
        return None
    value = int(value)
    if not minimum <= value <= maximum:
        errors.append(f"{name} must be between {minimum} and {maximum}.")
        return None
    return value


def estimate_budget(
    total_budget: float,
    days: int,
    currency: str,
    travel_cost: float,
    stay_per_night: float,
    food_per_day: float,
    activities_cost: float = 0.0,
    local_transport_per_day: float = 0.0,
    contingency_pct: float = 10.0,
    nights: int = None,
) -> dict:
    """Add up trip costs from amounts the user supplied.

    All amounts are for the whole travelling group, in one `currency` (ISO
    4217 code such as INR, EUR, USD). `nights` defaults to days - 1; pass it
    for day trips (0) or overnight-transport trips. `contingency_pct` is an
    adjustable planning reserve, not a price estimate.
    """
    errors: list = []
    cur = currency.strip().upper() if isinstance(currency, str) else ""
    if not re.fullmatch(r"[A-Z]{3}", cur):
        errors.append("currency must be a 3-letter code such as INR, EUR or USD.")

    total = _amount("total_budget", total_budget, errors)
    d = _whole("days", days, errors, minimum=1, maximum=120)
    travel = _amount("travel_cost", travel_cost, errors)
    stay = _amount("stay_per_night", stay_per_night, errors)
    food = _amount("food_per_day", food_per_day, errors)
    acts = _amount("activities_cost", activities_cost, errors)
    local = _amount("local_transport_per_day", local_transport_per_day, errors)
    pct = _amount("contingency_pct", contingency_pct, errors, maximum=100)

    n = None
    if d is not None:
        if nights is None:
            n = d - 1
        else:
            n = _whole("nights", nights, errors, minimum=0, maximum=d)

    if errors:
        return {"status": "invalid_input", "errors": errors}

    items = [
        ("Travel to/from destination", travel, "user-provided total", "user_provided"),
        ("Accommodation", stay * n, f"{stay:,.2f} x {n} nights", "derived_from_user_input"),
        ("Food", food * d, f"{food:,.2f} x {d} days", "derived_from_user_input"),
        ("Local transport", local * d, f"{local:,.2f} x {d} days", "derived_from_user_input"),
        ("Activities and entry fees", acts, "user-provided total", "user_provided"),
    ]
    subtotal = sum(i[1] for i in items)
    reserve = subtotal * pct / 100
    required = subtotal + reserve
    remaining = total - required

    return {
        "status": "within_budget" if remaining >= 0 else "shortfall",
        "currency": cur,
        "total_budget": round(total, 2),
        "line_items": [
            {"item": i, "amount": round(a, 2), "basis": b, "source": s}
            for i, a, b, s in items
        ] + [{
            "item": f"Contingency reserve ({pct:g}%)",
            "amount": round(reserve, 2),
            "basis": "planning reserve on the subtotal (adjustable assumption)",
            "source": "assumption",
        }],
        "subtotal": round(subtotal, 2),
        "total_required": round(required, 2),
        "remaining": round(remaining, 2) if remaining >= 0 else 0.0,
        "shortfall": round(-remaining, 2) if remaining < 0 else 0.0,
        "note": (
            "Arithmetic on user-supplied figures; no live prices were retrieved. "
            "Any item left at 0 was not provided and is NOT included."
        ),
    }
