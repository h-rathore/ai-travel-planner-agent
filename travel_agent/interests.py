"""Interest -> Geoapify category profiles.

Every category key below appears in Geoapify's published category list
(apidocs.geoapify.com/docs/places/#categories) as of this writing. Several
things users ask for have NO matching category (e.g. waterfalls, trails,
nightlife, shopping streets); those are reported as `unmapped` instead of
being silently dropped or approximated by a broad tag.
"""

import re
from dataclasses import dataclass

from .textutil import has_phrase, normalize


@dataclass(frozen=True)
class InterestProfile:
    key: str
    label: str
    keywords: tuple
    categories: tuple  # queried (OR semantics) and also used to qualify results
    note: str = ""


PROFILES = (
    InterestProfile(
        "beaches", "beaches",
        ("beach", "beaches", "seaside", "coast", "coastal", "shore"),
        ("beach", "natural.coastal"),
    ),
    InterestProfile(
        "mountains", "mountains & hills",
        ("mountain", "mountains", "hill", "hills", "hill station", "hill stations",
         "peak", "peaks", "trekking", "trek", "hiking", "hike"),
        ("natural.mountain.peak", "natural.mountain.hill",
         "natural.mountain.volcano", "natural.mountain.glacier"),
        note="Hiking/trekking is approximated by peaks and hills; trails are not searched.",
    ),
    InterestProfile(
        "nature", "nature & wildlife",
        ("nature", "wildlife", "forest", "forests", "jungle", "national park",
         "national parks", "sanctuary", "sanctuaries", "nature reserve", "safari"),
        ("national_park", "natural.protected_area",
         "leisure.park.nature_reserve", "natural.forest"),
    ),
    InterestProfile(
        "viewpoints", "scenic viewpoints",
        ("viewpoint", "viewpoints", "view point", "view points", "scenic",
         "scenery", "panoramic", "sunset", "sunsets", "lookout"),
        ("tourism.attraction.viewpoint",),
    ),
    InterestProfile(
        "gardens", "parks & gardens",
        ("garden", "gardens", "botanical", "park", "parks"),
        ("leisure.park.garden",),
        note="'Parks' is approximated by gardens; generic city parks are not searched.",
    ),
    InterestProfile(
        "heritage", "history & heritage",
        ("history", "historical", "historic", "heritage", "fort", "forts",
         "castle", "castles", "monument", "monuments", "unesco",
         "archaeology", "archaeological", "ruins", "culture", "cultural"),
        ("heritage", "building.historic", "tourism.sights.castle",
         "tourism.sights.fort", "tourism.sights.archaeological_site",
         "tourism.sights.ruines", "tourism.sights.memorial.monument"),
    ),
    InterestProfile(
        "museums", "museums",
        ("museum", "museums", "science", "culture", "cultural"),
        ("entertainment.museum",),
    ),
    InterestProfile(
        "art", "art & galleries",
        ("art", "arts", "gallery", "galleries", "art gallery"),
        ("entertainment.culture.gallery", "entertainment.culture.arts_centre"),
    ),
    InterestProfile(
        "religious", "temples & religious sites",
        ("temple", "temples", "church", "churches", "mosque", "mosques",
         "shrine", "shrines", "monastery", "monasteries", "spiritual",
         "place of worship"),
        ("tourism.sights.place_of_worship", "tourism.sights.monastery"),
    ),
    InterestProfile(
        "animals", "zoos & aquariums",
        ("zoo", "zoos", "aquarium", "aquariums"),
        ("entertainment.zoo", "entertainment.aquarium"),
    ),
    InterestProfile(
        "food", "food",
        ("food", "restaurant", "restaurants", "cuisine", "street food",
         "local food", "cafe", "cafes", "dining"),
        ("catering.restaurant", "catering.cafe"),
        note="Food places are meal stops, not sights; pick them near the day's route.",
    ),
)

GENERAL = InterestProfile(
    "general", "general sightseeing", (),
    ("tourism.attraction", "tourism.sights"),
    note="No specific interest recognised; generic tourism categories are broad and noisy.",
)

_SPLIT = re.compile(r"[,;/&]|\band\b|\bor\b|\n")


def match_interests(interests: str):
    """Return (profiles, unmapped_segments).

    Matching is per comma/'and'-separated segment and uses whole words, so
    "heart" never matches "art" and "parking" never matches "park".
    """
    if not isinstance(interests, str):
        return [], []

    matched: dict = {}
    unmapped: list = []

    for raw in _SPLIT.split(interests):
        segment = normalize(raw)
        if not segment:
            continue
        hit = False
        for profile in PROFILES:
            if any(has_phrase(segment, kw) for kw in profile.keywords):
                matched[profile.key] = profile
                hit = True
        if not hit:
            unmapped.append(raw.strip())

    return list(matched.values()), unmapped


def qualifies(place_categories, profile: InterestProfile) -> bool:
    """True if any returned category equals or is a child of a profile category."""
    for actual in place_categories:
        for wanted in profile.categories:
            if actual == wanted or actual.startswith(wanted + "."):
                return True
    return False
