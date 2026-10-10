import os
import re
import unicodedata
from typing import Optional

import requests
from google.adk.agents import Agent


GEOCODING_URL = "https://api.geoapify.com/v1/geocode/search"
PLACES_URL = "https://api.geoapify.com/v2/places"

REQUEST_TIMEOUT = 20
SEARCH_RADIUS_METERS = 15000
MAX_RESULTS_PER_AREA = 30
MAX_FINAL_RESULTS = 35


# ---------------------------------------------------------
# TEXT NORMALIZATION
# ---------------------------------------------------------

def normalize(value: str) -> str:
    """Normalize text for matching and deduplication."""
    value = unicodedata.normalize("NFKC", value).casefold().strip()
    value = re.sub(r"[^\w\s]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def contains_phrase(text: str, phrase: str) -> bool:
    """Match a phrase without matching it inside unrelated words."""
    return bool(
        re.search(
            rf"\b{re.escape(phrase.casefold())}\b",
            text.casefold(),
        )
    )


# ---------------------------------------------------------
# INTEREST -> GEOAPIFY CATEGORIES
# ---------------------------------------------------------

def get_interest_categories(interests: str) -> list[str]:
    """
    Map interests to specific Geoapify categories.
    Avoid broad tourism categories wherever possible.
    """
    text = normalize(interests)
    categories = []

    if any(
        term in text
        for term in [
            "beach", "beaches", "coast", "coastal",
            "sea", "seaside",
        ]
    ):
        categories.extend([
            "beach",
            "natural.coastal",
        ])

    if any(
        term in text
        for term in [
            "mountain", "mountains", "hill", "hills",
            "forest", "nature", "wildlife", "hiking",
            "trekking", "waterfall", "national park",
            "sanctuary",
        ]
    ):
        categories.extend([
            "natural.forest",
            "natural.mountain",
            "natural.protected_area",
            "national_park",
            "leisure.park.nature_reserve",
        ])

    if any(
        term in text
        for term in ["park", "parks", "garden", "gardens"]
    ):
        categories.extend([
            "leisure.park.garden",
            "leisure.park.nature_reserve",
        ])

    if any(
        term in text
        for term in [
            "viewpoint", "view point", "scenic",
            "sunset", "landscape",
        ]
    ):
        categories.append("tourism.attraction.viewpoint")

    if any(
        term in text
        for term in [
            "history", "historical", "heritage",
            "fort", "monument", "architecture",
            "unesco", "culture",
        ]
    ):
        categories.extend([
            "building.historic",
            "heritage",
            "entertainment.museum",
            "tourism.sights.castle",
            "tourism.sights.memorial",
            "tourism.sights.ruines",
        ])

    if any(
        term in text
        for term in ["museum", "science", "technology"]
    ):
        categories.append("entertainment.museum")

    if any(
        term in text
        for term in ["art", "gallery", "artwork"]
    ):
        categories.append("entertainment.culture.gallery")

    if any(
        term in text
        for term in [
            "food", "restaurant", "cuisine",
            "street food", "local food",
        ]
    ):
        categories.extend([
            "catering.restaurant",
            "catering.cafe",
            "catering.food_court",
        ])

    # Generic tourism categories are only a fallback.
    if not categories:
        categories = [
            "tourism.attraction",
            "tourism.sights",
            "entertainment.museum",
        ]

    return list(dict.fromkeys(categories))


# ---------------------------------------------------------
# LOCATION VALIDATION
# ---------------------------------------------------------

def get_location_constraints(
    area: str,
    destination: str,
) -> tuple[Optional[str], Optional[str]]:
    """Extract requested country and Indian state."""
    combined = normalize(f"{area}, {destination}")

    country_aliases = {
        "india": "india",
        "japan": "japan",
        "canada": "canada",
        "australia": "australia",
        "united states": "united states",
        "usa": "united states",
        "united kingdom": "united kingdom",
        "uk": "united kingdom",
        "france": "france",
        "germany": "germany",
        "italy": "italy",
        "spain": "spain",
        "singapore": "singapore",
        "thailand": "thailand",
        "indonesia": "indonesia",
        "malaysia": "malaysia",
        "nepal": "nepal",
        "sri lanka": "sri lanka",
        "uae": "united arab emirates",
        "united arab emirates": "united arab emirates",
    }

    requested_country = None

    for alias, canonical in country_aliases.items():
        if contains_phrase(combined, alias):
            requested_country = canonical
            break

    indian_states = [
        "andhra pradesh", "arunachal pradesh", "assam",
        "bihar", "chhattisgarh", "goa", "gujarat",
        "haryana", "himachal pradesh", "jharkhand",
        "karnataka", "kerala", "madhya pradesh",
        "maharashtra", "manipur", "meghalaya",
        "mizoram", "nagaland", "odisha", "punjab",
        "rajasthan", "sikkim", "tamil nadu",
        "telangana", "tripura", "uttar pradesh",
        "uttarakhand", "west bengal",
    ]

    area_normalized = normalize(area)

    requested_state = next(
        (
            state
            for state in indian_states
            if contains_phrase(area_normalized, state)
        ),
        None,
    )

    return requested_country, requested_state


def geocode_area(
    area: str,
    api_key: str,
    destination: str,
):
    """
    Resolve an area to a geographic locality.
    Prefer cities/localities over individual businesses.
    """
    requested_country, requested_state = (
        get_location_constraints(area, destination)
    )

    # Try the full address first, then a simpler locality query.
    queries = [area]

    parts = [part.strip() for part in area.split(",") if part.strip()]
    if len(parts) >= 2:
        simplified = ", ".join(parts[:1] + parts[-2:])
        if normalize(simplified) != normalize(area):
            queries.append(simplified)

    seen_coordinates = set()
    candidates = []

    for query in queries:
        response = requests.get(
            GEOCODING_URL,
            params={
                "text": query,
                "limit": 10,
                "lang": "en",
                "apiKey": api_key,
            },
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()

        features = response.json().get("features", [])

        for feature in features:
            properties = feature.get("properties", {})
            rank = properties.get("rank", {})

            country = normalize(properties.get("country", ""))
            state = normalize(properties.get("state", ""))
            formatted = properties.get("formatted", "")
            formatted_normalized = normalize(formatted)

            result_type = normalize(
                properties.get("result_type", "")
                or rank.get("result_type", "")
            )

            coordinates = (
                feature.get("geometry", {}).get("coordinates", [])
            )

            if len(coordinates) < 2:
                continue

            longitude, latitude = coordinates[:2]

            if not isinstance(longitude, (int, float)):
                continue
            if not isinstance(latitude, (int, float)):
                continue

            if requested_country and requested_country not in country:
                continue

            # Some providers return abbreviations in the state field.
            # Check the formatted address as well.
            if requested_state:
                if (
                    requested_state not in state
                    and requested_state not in formatted_normalized
                ):
                    continue

            # Avoid selecting individual businesses as city centres.
            locality_types = {
                "city",
                "town",
                "village",
                "municipality",
                "suburb",
                "district",
                "county",
            }

            if result_type not in locality_types:
                continue

            coords_key = (round(longitude, 4), round(latitude, 4))
            if coords_key in seen_coordinates:
                continue
            seen_coordinates.add(coords_key)

            # Prefer an exact locality-name match.
            requested_name = normalize(parts[0]) if parts else normalize(area)
            formatted_name = normalize(
                properties.get("city")
                or properties.get("town")
                or properties.get("village")
                or properties.get("name")
                or ""
            )

            score = 0
            if formatted_name == requested_name:
                score += 10
            elif requested_name and requested_name in formatted_normalized:
                score += 5

            if result_type in {"city", "town", "village"}:
                score += 3

            candidates.append(
                (
                    score,
                    float(longitude),
                    float(latitude),
                    formatted or area,
                )
            )

        if candidates:
            break

    if not candidates:
        return None, None, None

    candidates.sort(key=lambda item: item[0], reverse=True)
    _, longitude, latitude, label = candidates[0]

    return longitude, latitude, label


# ---------------------------------------------------------
# RESULT FILTERING
# ---------------------------------------------------------

def looks_like_irrelevant_business(
    name: str,
    categories: list[str],
) -> bool:
    """Reject obvious businesses and service listings."""
    normalized_name = normalize(name)
    category_text = " ".join(categories).casefold()

    unwanted_terms = [
        "pharmacy", "chemist", "courier",
        "automobile", "auto land", "motor",
        "spare parts", "industrial area",
        "district office", "revenue divisional office",
        "agricultural office", "press club",
        "chamber of commerce", "police station",
        "hospital", "clinic", "medical store",
        "bank", "atm", "post office", "warehouse",
        "government office", "service centre",
        "service center", "sports industries",
    ]

    if any(term in normalized_name for term in unwanted_terms):
        return True

    unwanted_category_prefixes = (
        "commercial.",
        "office.",
        "healthcare.",
        "service.",
        "industrial.",
    )

    # Do not reject a genuine attraction simply because it also
    # has a building category.
    has_attraction_category = any(
        category == "beach"
        or category.startswith("natural.")
        or category.startswith("national_park")
        or category.startswith("leisure.park.")
        or category.startswith("tourism.attraction.viewpoint")
        or category.startswith("building.historic")
        or category.startswith("heritage")
        or category.startswith("entertainment.museum")
        or category.startswith("tourism.sights.")
        for category in categories
    )

    if not has_attraction_category and any(
        category.startswith(unwanted_category_prefixes)
        for category in categories
    ):
        return True

    return False


def has_relevant_category(
    result_categories: list[str],
    requested_categories: list[str],
) -> bool:
    """Require a category match rather than a generic tourism tag."""
    for requested in requested_categories:
        for actual in result_categories:
            if actual == requested or actual.startswith(requested + "."):
                return True

    return False


def relevance_score(
    name: str,
    categories: list[str],
    requested_categories: list[str],
) -> int:
    """Rank exact category matches above broad matches."""
    score = 0
    name_normalized = normalize(name)

    for requested in requested_categories:
        if requested in categories:
            score += 5
        elif any(
            actual.startswith(requested + ".")
            for actual in categories
        ):
            score += 2

    useful_name_terms = [
        "beach", "waterfall", "viewpoint", "view point",
        "national park", "wildlife", "forest", "mountain",
        "fort", "palace", "museum", "garden", "lake",
        "dam", "sanctuary", "reserve",
    ]

    if any(term in name_normalized for term in useful_name_terms):
        score += 2

    return score


# ---------------------------------------------------------
# PLACE SEARCH
# ---------------------------------------------------------

def search_places(
    destination: str,
    interests: str,
    search_areas: Optional[list[str]] = None,
) -> str:
    """
    Search Geoapify for relevant named places worldwide.
    Use full geographic names in search_areas.
    """
    api_key = os.getenv("GEOAPIFY_API_KEY")

    if not api_key:
        return (
            "Place search unavailable: GEOAPIFY_API_KEY is missing."
        )

    if not destination or not destination.strip():
        return "Please provide a destination."

    if not interests or not interests.strip():
        return "Please provide travel interests."

    areas = search_areas or [destination]
    areas = list(dict.fromkeys(
        area.strip()
        for area in areas
        if area and area.strip()
    ))

    if not areas:
        return "Please provide valid search areas."

    categories = get_interest_categories(interests)
    unique_places = {}
    searched_areas = []
    warnings = []

    raw_count = 0
    rejected_count = 0
    duplicate_count = 0

    try:
        for area in areas:
            try:
                longitude, latitude, resolved_label = geocode_area(
                    area,
                    api_key,
                    destination,
                )
            except requests.RequestException:
                warnings.append(f"Geocoding request failed for: {area}")
                continue

            if longitude is None or latitude is None:
                warnings.append(
                    f"Skipped '{area}': no verified city/locality "
                    "result was found. Try a simpler locality name "
                    "with state/province and country."
                )
                continue

            searched_areas.append(
                f"{area} (resolved as {resolved_label})"
            )

            response = requests.get(
                PLACES_URL,
                params={
                    "categories": ",".join(categories),
                    "filter": (
                        f"circle:{longitude},{latitude},"
                        f"{SEARCH_RADIUS_METERS}"
                    ),
                    "bias": f"proximity:{longitude},{latitude}",
                    "limit": MAX_RESULTS_PER_AREA,
                    "lang": "en",
                    "apiKey": api_key,
                },
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()

            features = response.json().get("features", [])

            for feature in features:
                raw_count += 1
                properties = feature.get("properties", {})

                name = properties.get("name")
                if not isinstance(name, str) or not name.strip():
                    rejected_count += 1
                    continue

                address = properties.get("formatted") or "Address unavailable"
                result_categories = properties.get("categories") or []

                if not has_relevant_category(
                    result_categories,
                    categories,
                ):
                    rejected_count += 1
                    continue

                if looks_like_irrelevant_business(
                    name,
                    result_categories,
                ):
                    rejected_count += 1
                    continue

                place_id = properties.get("place_id")
                place_lon = properties.get("lon")
                place_lat = properties.get("lat")

                # Stable ID first; normalized name + rounded coordinates
                # as a fallback for records with different addresses.
                if place_id:
                    key = f"id:{place_id}"
                elif (
                    isinstance(place_lon, (int, float))
                    and isinstance(place_lat, (int, float))
                ):
                    key = (
                        f"{normalize(name)}|"
                        f"{round(place_lon, 3)}|{round(place_lat, 3)}"
                    )
                else:
                    key = f"{normalize(name)}|{normalize(address)}"

                score = relevance_score(
                    name,
                    result_categories,
                    categories,
                )

                if key in unique_places:
                    duplicate_count += 1

                    # Keep whichever record has the better category match.
                    if score > unique_places[key]["score"]:
                        unique_places[key] = {
                            "name": name.strip(),
                            "address": address,
                            "categories": result_categories,
                            "area": area,
                            "score": score,
                        }
                    continue

                unique_places[key] = {
                    "name": name.strip(),
                    "address": address,
                    "categories": result_categories,
                    "area": area,
                    "score": score,
                }

    except requests.HTTPError as error:
        status = (
            error.response.status_code
            if error.response is not None
            else None
        )

        if status == 401:
            return (
                "Geoapify rejected the API key. "
                "Check GEOAPIFY_API_KEY in .env."
            )

        if status == 429:
            return (
                "Geoapify request limit reached. "
                "Please try again later."
            )

        return (
            "Geoapify returned an HTTP error. "
            f"Status: {status or 'unknown'}."
        )

    except requests.RequestException:
        return "Place search failed due to a network or API error."

    except (ValueError, KeyError, IndexError, TypeError):
        return "The place service returned an unexpected response."

    ranked_places = sorted(
        unique_places.values(),
        key=lambda place: place["score"],
        reverse=True,
    )[:MAX_FINAL_RESULTS]

    output = [
        f"Place results for: {destination}",
        f"Interests: {interests}",
        f"Areas successfully searched: {len(searched_areas)}",
        f"Resolved search areas: {', '.join(searched_areas) or 'None'}",
        f"Categories searched: {', '.join(categories)}",
        f"Raw listings received: {raw_count}",
        f"Listings rejected: {rejected_count}",
        f"Duplicate listings removed: {duplicate_count}",
        f"Unique places retained: {len(unique_places)}",
        f"Places returned after ranking: {len(ranked_places)}",
        "",
    ]

    if not ranked_places:
        output.append(
            "No suitable named places found. Try different interests "
            "or more specific search areas."
        )

    for place in ranked_places:
        output.append(
            f"- {place['name']}\n"
            f"  Address: {place['address']}\n"
            f"  Search area: {place['area']}\n"
            f"  Categories: {', '.join(place['categories'])}"
        )

    if warnings:
        output.extend(["", "Search warnings:"])
        output.extend(f"- {warning}" for warning in warnings)

    output.extend([
        "",
        "Note: verify opening hours, fees, safety, and availability "
        "before visiting. Listings are not live confirmations.",
    ])

    return "\n".join(output)


# ---------------------------------------------------------
# BUDGET CALCULATOR
# ---------------------------------------------------------

def estimate_budget(
    total_budget: float,
    days: int,
    travel_cost: float,
    stay_per_night: float,
    food_per_day: float,
) -> str:
    """Calculate a basic budget from user-provided amounts."""
    if days < 1:
        return "Trip duration must be at least one day."

    if min(
        total_budget,
        travel_cost,
        stay_per_night,
        food_per_day,
    ) < 0:
        return "Budget and cost values cannot be negative."

    nights = max(days - 1, 0)
    stay_cost = stay_per_night * nights
    food_cost = food_per_day * days

    remaining = (
        total_budget
        - travel_cost
        - stay_cost
        - food_cost
    )

    output = [
        "Budget estimate based on your supplied figures:",
        f"Total budget: ₹{total_budget:,.0f}",
        f"Travel cost: ₹{travel_cost:,.0f}",
        f"Accommodation ({nights} nights): ₹{stay_cost:,.0f}",
        f"Food ({days} days): ₹{food_cost:,.0f}",
    ]

    if remaining < 0:
        output.append(f"Budget shortfall: ₹{abs(remaining):,.0f}")
    else:
        output.append(
            "Remaining for activities and local transport: "
            f"₹{remaining:,.0f}"
        )

    output.append(
        "This is a calculation, not a live quote. "
        "Verify actual prices separately."
    )

    return "\n".join(output)


# ---------------------------------------------------------
# GOOGLE ADK AGENT
# ---------------------------------------------------------

root_agent = Agent(
    name="travel_agent",
    model="gemini-3.6-flash",
    instruction="""
You are a personal travel planning assistant for destinations worldwide.

Understand the destination, trip duration, budget, interests, and
preferences before planning.

When calling search_places:
- Use complete geographic names including state/province and country.
- Avoid ambiguous city names.
- Keep search areas within the requested destination.
- For broad regions, search multiple relevant localities.
- If an area is skipped, do not pretend it was searched successfully.
- Recommend only places returned by the search tool.
- Prioritize attractions matching the user's interests.
- Do not repeat the same attraction in multiple itinerary days.
- Do not claim a place is open, safe, available, or free unless verified.

Use estimate_budget when all required cost inputs are available.
Never invent actual fares, hotel prices, ticket prices, or opening hours.
Ask for missing essential inputs or label estimates clearly.

Create a practical day-wise itinerary. Group nearby attractions together.
Consider arrival/departure locations, travel distances, transport and
available time. Do not combine distant destinations without explaining
the travel involved. If exact route distances or travel times are not
available, say so rather than inventing them.
""",
    tools=[search_places, estimate_budget],
)
