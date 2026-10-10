"""Tool functions exposed to the ADK agent (no ADK imports, so testable)."""

import os
from typing import Optional

from .budget import estimate_budget as _estimate_budget
from .geoapify import GeoapifyClient
from .places import DEFAULT_RADIUS_M, run_place_search


def search_places(
    destination: str,
    interests: str,
    search_areas: Optional[list[str]] = None,
    country_code: Optional[str] = None,
    max_results: int = 12,
) -> dict:
    """Find real named places for the user's interests near specific towns.

    Args:
        destination: Overall destination, e.g. "Kerala, India".
        interests: Comma-separated interests in English, e.g.
            "beaches, mountains, heritage, food".
        search_areas: Specific towns/localities, each as "Town, District/State,
            Country". Needed when destination is a state, region or country.
        country_code: ISO 3166-1 alpha-2 code ("in", "jp") when the user stated
            or clearly implied the country. Leave empty otherwise.
        max_results: How many places to return (1-30). Fewer, diverse places
            are better than long lists.

    Returns a dict. Check `status` first: "needs_clarification" means ask the
    user (see `message`/`alternatives`); "partial" means some areas failed
    (see `areas` and `warnings`) and you must say so.
    """
    api_key = os.getenv("GEOAPIFY_API_KEY")
    if not api_key:
        return {
            "status": "error",
            "message": "Place search unavailable: GEOAPIFY_API_KEY is not set.",
        }
    client = GeoapifyClient(api_key)
    return run_place_search(
        client, destination, interests, search_areas,
        country_code=country_code, max_results=max_results,
        radius_m=DEFAULT_RADIUS_M,
    )


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
    nights: Optional[int] = None,
) -> dict:
    """Add up trip costs from figures the user supplied (never invented).

    All amounts are for the whole group in one currency (ISO code, e.g. INR).
    `nights` defaults to days - 1. Returns a dict with line items, each tagged
    with its source (user_provided / derived_from_user_input / assumption).
    Ask the user for any cost you do not have rather than guessing.
    """
    return _estimate_budget(
        total_budget, days, currency, travel_cost, stay_per_night,
        food_per_day, activities_cost, local_transport_per_day,
        contingency_pct, nights,
    )
