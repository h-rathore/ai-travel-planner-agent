"""Place discovery: per-interest search, merging, ranking, diversification.

Ranking is deliberately simple and explainable. Geoapify's Places data comes
from OpenStreetMap and has no popularity/rating field, so "relevance" here
means: matches more of the user's interests, is close to the searched
locality, is corroborated by more than one record, and is UNESCO-tagged
(`heritage.unesco` is a documented category). It cannot tell a famous
beach from an obscure one.
"""

from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from .geo import haversine_km, valid_coordinate
from .geoapify import GeoapifyClient, GeoapifyError
from .interests import GENERAL, InterestProfile, match_interests, qualifies
from .location import LocationResult, resolve_location
from .textutil import normalize, tokens

PLACES_URL = "https://api.geoapify.com/v2/places"
DEFAULT_RADIUS_M = 15000
# Geoapify charges 1 credit for <=20 places per Places request (pricing-details).
PER_QUERY_LIMIT = 20

SAME_NAME_RADIUS_M = 1000
NAME_SUBSET_RADIUS_M = 150
SPACING_KM = 1.5
SPACING_PENALTY = 0.7
AREA_PENALTY = 0.3

_BUSINESS_PREFIXES = ("commercial.", "office.", "service.", "healthcare.", "industrial.")


@dataclass
class PlaceRecord:
    name: str
    lat: float
    lon: float
    address: str
    categories: set
    interests: set
    place_ids: list
    area: str
    dist_m: float
    source_count: int = 1
    score: float = 0.0


@dataclass
class SearchDiagnostics:
    raw: int = 0
    rejected: Counter = field(default_factory=Counter)
    merged_duplicates: int = 0
    found_per_interest: Counter = field(default_factory=Counter)


def parse_place_feature(feature):
    """-> (name, lat, lon, categories, place_id, address) or (None, reason)."""
    props = feature.get("properties") if isinstance(feature, dict) else None
    if not isinstance(props, dict):
        return None, "malformed_feature"

    name = props.get("name")
    if not isinstance(name, str) or not name.strip():
        return None, "no_name"

    lat, lon = props.get("lat"), props.get("lon")
    if not valid_coordinate(lat, lon):
        coords = (feature.get("geometry") or {}).get("coordinates") or []
        if len(coords) >= 2:
            lon, lat = coords[0], coords[1]
    if not valid_coordinate(lat, lon):
        return None, "no_coordinates"

    cats = props.get("categories")
    cats = [c for c in cats if isinstance(c, str)] if isinstance(cats, list) else []
    return (
        name.strip(), float(lat), float(lon), cats,
        props.get("place_id"), props.get("formatted") or "",
    ), ""


def query_places(client, profile, lat, lon, radius_m):
    params = {
        "categories": ",".join(profile.categories),
        "filter": f"circle:{lon},{lat},{radius_m}",
        "bias": f"proximity:{lon},{lat}",
        "limit": PER_QUERY_LIMIT,
        "lang": "en",
    }
    data = client.get(PLACES_URL, params)
    features = data.get("features")
    if not isinstance(features, list):
        raise GeoapifyError("malformed", "Places response had no 'features' list.")
    return features


# ----------------------------------------------------------------- merging

def _same_place(a: PlaceRecord, b: PlaceRecord) -> bool:
    d_m = haversine_km(a.lat, a.lon, b.lat, b.lon) * 1000
    na, nb = normalize(a.name), normalize(b.name)
    if na == nb and d_m <= SAME_NAME_RADIUS_M:
        return True
    ta, tb = tokens(a.name), tokens(b.name)
    if ta and tb and (ta <= tb or tb <= ta) and d_m <= NAME_SUBSET_RADIUS_M:
        return True
    return False


def merge_places(records, diag: Optional[SearchDiagnostics] = None):
    """Merge records describing the same real-world place.

    Geoapify `place_id`s differ between the node/way/relation records OSM
    may hold for one beach, so ids alone cannot dedupe (as observed with
    "Vettakada Beach" and "Kattoor Beach"). Rule: same normalised name
    within 1 km, or one name's words contained in the other's within 150 m.
    """
    merged: list = []
    for rec in sorted(records, key=lambda r: (normalize(r.name), r.lat, r.lon)):
        for m in merged:
            if _same_place(m, rec):
                m.categories |= rec.categories
                m.interests |= rec.interests
                m.place_ids.extend(i for i in rec.place_ids if i not in m.place_ids)
                m.source_count += rec.source_count
                m.dist_m = min(m.dist_m, rec.dist_m)
                # Prefer a properly capitalised name over e.g. "kattoor beach".
                if m.name == m.name.lower() and rec.name != rec.name.lower():
                    m.name = rec.name
                if not m.address and rec.address:
                    m.address = rec.address
                if diag:
                    diag.merged_duplicates += 1
                break
        else:
            merged.append(rec)
    return merged


# ----------------------------------------------------------------- ranking

def score_place(p: PlaceRecord, radius_m: float) -> float:
    s = 2.0 * len(p.interests)
    s += max(0.0, 1.0 - p.dist_m / radius_m)
    s += 0.25 * min(p.source_count, 3)
    if any(c == "heritage.unesco" for c in p.categories):
        s += 1.0
    return round(s, 3)


def select_diverse(places, profiles, max_results: int):
    """Round-robin over interests, penalising crowding and area dominance."""
    selected: list = []
    keys = [p.key for p in profiles]
    if not keys:
        return selected

    area_counts: Counter = Counter()
    while len(selected) < max_results:
        progressed = False
        for key in keys:
            if len(selected) >= max_results:
                break
            best, best_adj = None, None
            for p in places:
                if p in selected or key not in p.interests:
                    continue
                crowd = sum(
                    1 for s in selected
                    if (s.interests & p.interests)
                    and haversine_km(s.lat, s.lon, p.lat, p.lon) < SPACING_KM
                )
                adj = (
                    p.score
                    - SPACING_PENALTY * min(crowd, 2)
                    - AREA_PENALTY * area_counts[p.area]
                )
                if best_adj is None or adj > best_adj:
                    best, best_adj = p, adj
            if best is not None:
                selected.append(best)
                area_counts[best.area] += 1
                progressed = True
        if not progressed:
            break
    return selected


# ------------------------------------------------------------------ search

_FATAL = {"auth"}


def run_place_search(
    client: GeoapifyClient,
    destination: str,
    interests: str,
    search_areas: Optional[list] = None,
    country_code: Optional[str] = None,
    max_results: int = 12,
    radius_m: int = DEFAULT_RADIUS_M,
) -> dict:
    if not isinstance(destination, str) or not destination.strip():
        return {"status": "invalid_input", "message": "Please provide a destination."}
    if not isinstance(interests, str) or not interests.strip():
        return {"status": "invalid_input", "message": "Please provide travel interests."}
    if isinstance(max_results, bool) or not isinstance(max_results, int) or not 1 <= max_results <= 30:
        return {"status": "invalid_input", "message": "max_results must be an integer from 1 to 30."}
    if isinstance(radius_m, bool) or not isinstance(radius_m, int) or not 1000 <= radius_m <= 50000:
        return {"status": "invalid_input", "message": "radius_m must be between 1000 and 50000."}

    if country_code is not None:
        cc = normalize(country_code)
        if len(cc) != 2 or not cc.isalpha():
            return {"status": "invalid_input",
                    "message": "country_code must be a 2-letter ISO 3166-1 code, e.g. 'in'."}
        country_code = cc

    profiles, unmapped = match_interests(interests)
    notes: list = []
    if not profiles:
        profiles = [GENERAL]
        notes.append(GENERAL.note)
    notes.extend(p.note for p in profiles if p.note)

    result: dict = {
        "destination": destination.strip(),
        "interests_searched": [p.label for p in profiles],
        "unmapped_interests": unmapped,
        "warnings": [],
        "notes": notes,
    }
    if unmapped:
        result["warnings"].append(
            "These interests have no matching Geoapify category and were NOT "
            f"searched: {', '.join(unmapped)}."
        )

    try:
        # --- country ---------------------------------------------------
        if not country_code:
            dest = resolve_location(client, destination, allow_regions=True)
            if dest.status != "confirmed":
                result.update(
                    status="needs_clarification",
                    message=dest.reason or "Could not identify the destination country.",
                    alternatives=[c.label for c in dest.alternatives],
                )
                return result
            country_code = dest.best.country_code
            result["warnings"].extend(dest.warnings)
        result["country_code"] = country_code

        # --- areas -----------------------------------------------------
        areas = list(dict.fromkeys(
            a.strip() for a in (search_areas or [destination]) if isinstance(a, str) and a.strip()
        ))
        if not areas:
            return {**result, "status": "invalid_input", "message": "No valid search areas."}

        diag = SearchDiagnostics()
        area_reports: list = []
        records: list = []
        resolved_areas: list = []
        stop = False

        for area in areas:
            if stop:
                break
            report = {"query": area}
            area_reports.append(report)
            try:
                loc: LocationResult = resolve_location(client, area, country_code=country_code)
            except GeoapifyError as e:
                if e.kind in _FATAL:
                    raise
                report.update(status="failed", reason=str(e))
                if e.kind == "rate_limit":
                    stop = True
                continue

            report["status"] = loc.status
            report["warnings"] = loc.warnings
            if loc.status != "confirmed":
                report["reason"] = loc.reason
                report["alternatives"] = [c.label for c in loc.alternatives]
                continue

            best = loc.best
            report.update(
                resolved_as=best.label, lat=best.lat, lon=best.lon,
                confidence=best.confidence,
            )
            resolved_areas.append((area, best))

            for profile in profiles:
                try:
                    features = query_places(client, profile, best.lat, best.lon, radius_m)
                except GeoapifyError as e:
                    if e.kind in _FATAL:
                        raise
                    result["warnings"].append(
                        f"Search for '{profile.label}' near '{area}' failed: {e}"
                    )
                    if e.kind == "rate_limit":
                        stop = True
                        break
                    continue

                for feature in features:
                    diag.raw += 1
                    parsed, reason = parse_place_feature(feature)
                    if parsed is None:
                        diag.rejected[reason] += 1
                        continue
                    name, lat, lon, cats, pid, address = parsed

                    if profile is GENERAL:
                        if any(c.startswith(_BUSINESS_PREFIXES) for c in cats):
                            diag.rejected["business_category"] += 1
                            continue
                    elif not qualifies(cats, profile):
                        diag.rejected["no_matching_category"] += 1
                        continue

                    records.append(PlaceRecord(
                        name=name, lat=lat, lon=lon, address=address,
                        categories=set(cats), interests={profile.key},
                        place_ids=[pid] if pid else [], area=area,
                        dist_m=haversine_km(best.lat, best.lon, lat, lon) * 1000,
                    ))
                    diag.found_per_interest[profile.key] += 1

    except GeoapifyError as e:
        if e.kind == "auth":
            return {**result, "status": "error", "message": str(e)}
        return {**result, "status": "error", "message": f"Place search failed: {e}"}

    merged = merge_places(records, diag)
    for p in merged:
        p.score = score_place(p, radius_m)
    merged.sort(key=lambda p: (-p.score, normalize(p.name)))
    chosen = select_diverse(merged, profiles, max_results)

    label_of = {p.key: p.label for p in profiles}
    result["places"] = [
        {
            "name": p.name,
            "lat": round(p.lat, 5),
            "lon": round(p.lon, 5),
            "area": p.area,
            "distance_from_area_centre_km": round(p.dist_m / 1000, 1),
            "matches_interests": sorted(label_of[k] for k in p.interests),
            "address": p.address or None,
            "place_id": p.place_ids[0] if p.place_ids else None,
            "score": p.score,
        }
        for p in chosen
    ]

    result["areas"] = area_reports
    result["straight_line_km_between_areas"] = [
        {
            "from": a[0], "to": b[0],
            "km": round(haversine_km(a[1].lat, a[1].lon, b[1].lat, b[1].lon), 1),
        }
        for i, a in enumerate(resolved_areas)
        for b in resolved_areas[i + 1:]
    ]
    result["distance_note"] = (
        "Distances above are straight-line, not road distance or travel time."
    )
    result["diagnostics"] = {
        "raw_listings": diag.raw,
        "rejected": dict(diag.rejected),
        "duplicates_merged": diag.merged_duplicates,
        "unique_places": len(merged),
        "returned": len(chosen),
        "found_per_interest": dict(diag.found_per_interest),
        "api_requests": client.request_count,
    }

    failed = [r for r in area_reports if r.get("status") != "confirmed"]
    if not resolved_areas:
        result["status"] = "needs_clarification"
        result["message"] = (
            "None of the search areas could be resolved confidently. Ask the user "
            "for specific towns (name, state/province, country)."
        )
    elif failed or stop:
        result["status"] = "partial"
    else:
        result["status"] = "ok"

    if not chosen and resolved_areas:
        result["warnings"].append("No suitable named places were found for these interests.")

    result["data_note"] = (
        "Place data comes from OpenStreetMap via Geoapify. It contains no ratings, "
        "opening hours, prices or availability here; do not state any."
    )
    return result
