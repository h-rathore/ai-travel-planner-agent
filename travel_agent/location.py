"""Location resolution with explicit validation (no silent wrong coordinates).

Design notes (verified against Geoapify's Forward Geocoding docs):
- `result_type` values documented: unknown, amenity, building, street,
  suburb, district, postcode, city, county, state, country. (There is no
  "town"/"village"/"municipality"; those appear under "city".)
- `type=city` and `type=locality` request parameters exist; `filter=countrycode:xx`
  is a hard filter; `rank.confidence` is 0..1.
- The default geocoding bias is `countrycode:auto` (guessed from the caller's
  IP). On a cloud-hosted app that silently skews results, so we always send
  `bias=countrycode:none`.

Unverified: the right confidence threshold for city-level queries. The default
is a conservative guess; log real values from the integration test and tune.
"""

from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from .geo import haversine_km, valid_coordinate
from .geoapify import GeoapifyClient, GeoapifyError
from .textutil import has_phrase, normalize

GEOCODE_URL = "https://api.geoapify.com/v1/geocode/search"

AREA_TYPES = frozenset({"city", "suburb", "district", "county"})
REGION_TYPES = AREA_TYPES | {"state", "country"}

MIN_CONFIDENCE = 0.5  # TODO calibrate with real responses
AMBIGUITY_KM = 25.0
AMBIGUITY_SCORE_GAP = 0.15

_TEXT_FIELDS = (
    "formatted", "name", "city", "town", "village", "suburb", "district",
    "county", "state", "state_code", "country", "country_code",
)


@dataclass(frozen=True)
class Candidate:
    label: str
    lat: float
    lon: float
    country_code: str
    result_type: str
    confidence: Optional[float]
    hint_fraction: float
    unmatched_hints: tuple
    score: float


@dataclass
class LocationResult:
    status: str  # confirmed | ambiguous | unresolved
    query: str
    best: Optional[Candidate] = None
    alternatives: list = field(default_factory=list)
    reason: str = ""
    warnings: list = field(default_factory=list)


def _to_candidate(feature, hints, allowed_types, country_code, min_confidence, rejected):
    props = feature.get("properties") if isinstance(feature, dict) else None
    if not isinstance(props, dict):
        rejected["malformed_feature"] += 1
        return None

    lat, lon = props.get("lat"), props.get("lon")
    if not valid_coordinate(lat, lon):
        coords = (feature.get("geometry") or {}).get("coordinates") or []
        if len(coords) >= 2:
            lon, lat = coords[0], coords[1]
    if not valid_coordinate(lat, lon):
        rejected["bad_coordinates"] += 1
        return None

    rank = props.get("rank") if isinstance(props.get("rank"), dict) else {}
    result_type = normalize(props.get("result_type") or rank.get("result_type") or "")
    if result_type not in allowed_types:
        rejected[f"type_{result_type or 'missing'}"] += 1
        return None

    cc = normalize(props.get("country_code") or "")
    if country_code and cc != country_code:
        rejected["country_mismatch"] += 1
        return None

    confidence = rank.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        confidence = None
    if confidence is not None and confidence < min_confidence:
        rejected["low_confidence"] += 1
        return None

    haystack = " ".join(
        normalize(props.get(f)) for f in _TEXT_FIELDS if isinstance(props.get(f), str)
    )
    unmatched = tuple(h for h in hints if not has_phrase(haystack, h))
    fraction = 1.0 if not hints else (len(hints) - len(unmatched)) / len(hints)

    score = (confidence if confidence is not None else 0.5) + 0.3 * fraction
    label = props.get("formatted") or props.get("name") or ""
    return Candidate(
        label=label,
        lat=float(lat),
        lon=float(lon),
        country_code=cc,
        result_type=result_type,
        confidence=confidence,
        hint_fraction=fraction,
        unmatched_hints=unmatched,
        score=score,
    )


def resolve_location(
    client: GeoapifyClient,
    query: str,
    *,
    country_code: Optional[str] = None,
    allow_regions: bool = False,
    min_confidence: float = MIN_CONFIDENCE,
) -> LocationResult:
    """Resolve a place name to coordinates, or say clearly why not.

    Raises GeoapifyError for transport/auth problems (caller decides).
    """
    if not isinstance(query, str) or not query.strip():
        return LocationResult("unresolved", str(query), reason="Empty location name.")

    query = query.strip()
    parts = [p.strip() for p in query.split(",") if p.strip()]

    # Normalize the well-known Alleppey alias to its canonical city name.
    if parts and normalize(parts[0]) == "alleppey":
        parts[0] = "Alappuzha"
        if len(parts) > 1 and normalize(parts[1]) == "alappuzha":
            parts.pop(1)
        if len(parts) == 1:
            parts.extend(["Kerala", "India"])
        query = ", ".join(parts)

    hints = parts[1:]
    allowed = REGION_TYPES if allow_regions else AREA_TYPES
    attempts = [None] if allow_regions else ["city", "locality"]
    rejected: Counter = Counter()
    candidates: list = []

    for type_ in attempts:
        params = {"text": query, "limit": 5, "lang": "en", "bias": "countrycode:none"}
        if type_:
            params["type"] = type_
        if country_code:
            params["filter"] = f"countrycode:{country_code}"

        data = client.get(GEOCODE_URL, params)
        features = data.get("features")
        if not isinstance(features, list):
            raise GeoapifyError("malformed", "Geocoder response had no 'features' list.")

        for feature in features:
            cand = _to_candidate(
                feature, hints, allowed, country_code, min_confidence, rejected
            )
            if cand:
                candidates.append(cand)
        if candidates:
            break

    if not candidates:
        detail = ", ".join(f"{k}={v}" for k, v in sorted(rejected.items())) or "no results"
        return LocationResult(
            "unresolved", query,
            reason=f"No confident city/locality match for '{query}' ({detail}).",
        )

    candidates.sort(key=lambda c: c.score, reverse=True)

    distinct: list = []
    for c in candidates:
        if all(haversine_km(c.lat, c.lon, d.lat, d.lon) > 2.0 for d in distinct):
            distinct.append(c)

    best = distinct[0]
    others = distinct[1:]

    if len(parts) >= 3 and len(hints) >= 2 and best.hint_fraction == 0:
        return LocationResult(
            "unresolved", query, alternatives=distinct[:3],
            reason=(
                f"The closest match ({best.label}) does not mention any of: "
                f"{', '.join(hints)}. The name may be wrong or in another region."
            ),
        )

    rivals = [
        o for o in others
        if haversine_km(best.lat, best.lon, o.lat, o.lon) > AMBIGUITY_KM
        and o.score >= best.score - AMBIGUITY_SCORE_GAP
    ]
    if rivals:
        return LocationResult(
            "ambiguous", query, alternatives=[best] + rivals[:3],
            reason=f"'{query}' matches several distant places; ask the user which one.",
        )

    warnings = []
    if best.unmatched_hints:
        warnings.append(
            f"Resolved '{query}' as '{best.label}', but this does not mention: "
            f"{', '.join(best.unmatched_hints)}."
        )
    if best.confidence is None:
        warnings.append(f"No confidence score returned for '{query}'.")

    return LocationResult("confirmed", query, best=best, warnings=warnings)
