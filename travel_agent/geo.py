"""Pure geometry helpers (no network)."""

import math


def is_number(value) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def valid_coordinate(lat, lon) -> bool:
    return (
        is_number(lat)
        and is_number(lon)
        and -90 <= lat <= 90
        and -180 <= lon <= 180
    )


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    """Great-circle ("straight line") distance. NOT a road distance."""
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
