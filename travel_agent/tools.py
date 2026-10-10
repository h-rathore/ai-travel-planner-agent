
"""Validated tool functions exposed to the ADK agent."""

import os
import re
from typing import Optional

from .budget import estimate_budget as _estimate_budget
from .geoapify import GeoapifyClient
from .places import DEFAULT_RADIUS_M, run_place_search


MAX_DESTINATION_LENGTH = 200
MAX_INTERESTS_LENGTH = 500
MAX_SEARCH_AREAS = 8
MAX_SEARCH_AREA_LENGTH = 160
MAX_RESULTS = 30

COUNTRY_CODE_PATTERN = re.compile(r"^[a-zA-Z]{2}$")


def _invalid(message: str) -> dict:
    return {
        "status": "invalid_input",
        "message": message,
    }


def search_places(
    destination: str,
    interests: str,
    search_areas: Optional[list[str]] = None,
    country_code: Optional[str] = None,
    max_results: int = 12,
) -> dict:
    """Find real named places for the user's interests.

    Args:
        destination: Destination name, for example "Kerala, India".
        interests: Comma-separated travel interests.
        search_areas: Optional list of specific towns/localities.
        country_code: Optional two-letter country code.
        max_results: Number of places requested, from 1 to 30.

    Returns:
        A structured result with status, places, warnings, and diagnostics.
    """

    # Validate before reading credentials or making external requests.
    if not isinstance(destination, str) or not destination.strip():
        return _invalid("Please provide a destination.")

    destination = destination.strip()

    if len(destination) > MAX_DESTINATION_LENGTH:
        return _invalid(
            f"Destination must be at most {MAX_DESTINATION_LENGTH} characters."
        )

    if not isinstance(interests, str) or not interests.strip():
        return _invalid("Please provide travel interests.")

    interests = interests.strip()

    if len(interests) > MAX_INTERESTS_LENGTH:
        return _invalid(
            f"Interests must be at most {MAX_INTERESTS_LENGTH} characters."
        )

    if (
        isinstance(max_results, bool)
        or not isinstance(max_results, int)
        or not 1 <= max_results <= MAX_RESULTS
    ):
        return _invalid(
            f"max_results must be an integer from 1 to {MAX_RESULTS}."
        )

    if search_areas is not None:
        if not isinstance(search_areas, list):
            return _invalid("search_areas must be a list of town names.")

        if len(search_areas) > MAX_SEARCH_AREAS:
            return _invalid(
                f"Provide no more than {MAX_SEARCH_AREAS} search areas per request."
            )

        cleaned_areas = []

        for area in search_areas:
            if not isinstance(area, str) or not area.strip():
                return _invalid(
                    "Every search area must be a non-empty string."
                )

            area = area.strip()

            if len(area) > MAX_SEARCH_AREA_LENGTH:
                return _invalid(
                    "Each search area must be at most "
                    f"{MAX_SEARCH_AREA_LENGTH} characters."
                )

            cleaned_areas.append(area)

        search_areas = list(dict.fromkeys(cleaned_areas))

    if country_code is not None:
        if not isinstance(country_code, str):
            return _invalid("country_code must be a two-letter country code.")

        country_code = country_code.strip().lower()

        if not COUNTRY_CODE_PATTERN.fullmatch(country_code):
            return _invalid(
                "country_code must contain exactly two letters, "
                "for example 'in' or 'jp'."
            )

    api_key = os.getenv("GEOAPIFY_API_KEY")

    if not api_key:
        return {
            "status": "error",
            "message": "Place search unavailable: GEOAPIFY_API_KEY is not set.",
        }

    client = GeoapifyClient(api_key)

    return run_place_search(
        client,
        destination,
        interests,
        search_areas,
        country_code=country_code,
        max_results=max_results,
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
    """Calculate a budget using supplied figures, never invented prices."""

    # budget.py performs numeric, range, duration, and currency-format checks.
    return _estimate_budget(
        total_budget,
        days,
        currency,
        travel_cost,
        stay_per_night,
        food_per_day,
        activities_cost,
        local_transport_per_day,
        contingency_pct,
        nights,
    )
