import json
import os
import unittest
from unittest import mock

import requests

from travel_agent import tools
from travel_agent.budget import estimate_budget
from travel_agent.geoapify import GeoapifyClient, GeoapifyError
from travel_agent.interests import match_interests
from travel_agent.location import GEOCODE_URL, resolve_location
from travel_agent.places import (
    PLACES_URL, PlaceRecord, merge_places, run_place_search,
    score_place, select_diverse,
)
from travel_agent.textutil import has_phrase, normalize

from .helpers import FakeClient, err, fc, geo_feature, place_feature


# --------------------------------------------------------------- text/interests
class TextAndInterests(unittest.TestCase):
    def test_whole_word_matching(self):
        self.assertFalse(has_phrase(normalize("heart of the party"), "art"))
        self.assertFalse(has_phrase(normalize("parking lot"), "park"))
        self.assertTrue(has_phrase(normalize("street food tour"), "street food"))

    def test_substring_bug_fixed(self):
        # Old code: "art" in "heart and research" -> art galleries; "sea" in "research".
        profiles, unmapped = match_interests("heart surgery research")
        self.assertEqual(profiles, [])

    def test_multi_interest_and_unmapped(self):
        profiles, unmapped = match_interests(
            "beaches, mountains, nature, scenic viewpoints, waterfalls and nightlife")
        keys = {p.key for p in profiles}
        self.assertEqual(keys, {"beaches", "mountains", "nature", "viewpoints"})
        self.assertEqual(unmapped, ["waterfalls", "nightlife"])

    def test_culture_maps_to_two_profiles(self):
        keys = {p.key for p in match_interests("culture")[0]}
        self.assertEqual(keys, {"heritage", "museums"})


# ------------------------------------------------------------------- location
class Location(unittest.TestCase):
    def client(self, features):
        return FakeClient(lambda url, p: fc(*features))

    def test_confirmed_and_bias_none_and_type(self):
        c = self.client([geo_feature("Munnar", 10.089, 77.059, county="Idukki")])
        r = resolve_location(c, "Munnar, Idukki, Kerala, India", country_code="in")
        self.assertEqual(r.status, "confirmed")
        _, params = c.calls[0]
        self.assertEqual(params["bias"], "countrycode:none")  # avoid IP-based bias
        self.assertEqual(params["filter"], "countrycode:in")
        self.assertEqual(params["type"], "city")
        self.assertEqual(r.warnings, [])

    def test_alias_is_resolved_via_hints(self):
        c = self.client([geo_feature("Alappuzha", 9.49, 76.33, county="Alappuzha")])
        r = resolve_location(c, "Alleppey, Alappuzha, Kerala, India", country_code="in")
        self.assertEqual(r.status, "confirmed")

    def test_country_mismatch_rejected(self):
        c = self.client([geo_feature("Kochi", 33.5, 133.5, cc="jp", country="Japan", state="Kochi")])
        r = resolve_location(c, "Kochi", country_code="in")
        self.assertEqual(r.status, "unresolved")
        self.assertIn("country_mismatch", r.reason)

    def test_non_locality_types_rejected(self):
        c = self.client([geo_feature("Hill Top Cafe", 10.0, 77.0, rtype="amenity")])
        self.assertEqual(resolve_location(c, "Hill Top Cafe, Kerala, India").status, "unresolved")

    def test_low_confidence_rejected(self):
        c = self.client([geo_feature("Munnar", 10.0, 77.0, confidence=0.2)])
        r = resolve_location(c, "Munnar")
        self.assertEqual(r.status, "unresolved")
        self.assertIn("low_confidence", r.reason)

    def test_ambiguous_distant_matches(self):
        c = self.client([
            geo_feature("Springfield", 39.8, -89.6, cc="us", country="United States", state="Illinois"),
            geo_feature("Springfield", 42.1, -72.6, cc="us", country="United States", state="Massachusetts"),
        ])
        r = resolve_location(c, "Springfield", country_code="us")
        self.assertEqual(r.status, "ambiguous")
        self.assertEqual(len(r.alternatives), 2)

    def test_hints_disambiguate(self):
        c = self.client([
            geo_feature("Springfield", 39.8, -89.6, cc="us", country="United States", state="Illinois"),
            geo_feature("Springfield", 42.1, -72.6, cc="us", country="United States", state="Massachusetts"),
        ])
        r = resolve_location(c, "Springfield, Massachusetts, United States", country_code="us")
        self.assertEqual(r.status, "confirmed")
        self.assertAlmostEqual(r.best.lat, 42.1)

    def test_no_hint_match_is_unresolved(self):
        c = self.client([geo_feature("Munnar", 10.0, 77.0)])
        r = resolve_location(c, "Munnar, Atlantis, Narnia")
        self.assertEqual(r.status, "unresolved")

    def test_partial_hint_mismatch_warns(self):
        c = self.client([geo_feature("Munnar", 10.0, 77.0)])
        r = resolve_location(c, "Munnar, Tamil Nadu, India")
        self.assertEqual(r.status, "confirmed")
        self.assertTrue(any("Tamil Nadu" in w for w in r.warnings))

    def test_falls_back_to_locality_type(self):
        def handler(url, p):
            return fc() if p.get("type") == "city" else fc(geo_feature("Idukki", 9.85, 76.97, rtype="district"))
        c = FakeClient(handler)
        self.assertEqual(resolve_location(c, "Idukki, Kerala, India").status, "confirmed")
        self.assertEqual([p["type"] for _, p in c.calls], ["city", "locality"])

    def test_malformed_response(self):
        c = FakeClient(lambda u, p: {"unexpected": 1})
        with self.assertRaises(GeoapifyError) as cm:
            resolve_location(c, "Munnar")
        self.assertEqual(cm.exception.kind, "malformed")

    def test_empty_query(self):
        self.assertEqual(resolve_location(FakeClient(lambda u, p: fc()), "  ").status, "unresolved")


# ------------------------------------------------------------- merge / ranking
def rec(name, lat, lon, interest="beaches", cats=("beach",), pid=None, area="A", dist=1000.0):
    return PlaceRecord(name, lat, lon, "", set(cats), {interest},
                       [pid] if pid else [], area, dist)


class MergeAndRank(unittest.TestCase):
    def test_vettakada_style_duplicates_merge_despite_different_ids(self):
        recs = [
            rec("Vettakada Beach", 8.7400, 76.7000, "viewpoints", ("tourism.attraction.viewpoint",), "id1"),
            rec("Vettakada Beach", 8.7401, 76.7001, "beaches", ("beach",), "id2"),
        ]
        merged = merge_places(recs)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].interests, {"viewpoints", "beaches"})
        self.assertEqual(merged[0].place_ids, ["id1", "id2"])

    def test_kattoor_style_case_variants_merge(self):
        recs = [rec("kattoor beach", 9.60, 76.30), rec("Kattoor Beach", 9.6001, 76.3001),
                rec("Kattoor Beach", 9.6002, 76.3002)]
        merged = merge_places(recs)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].name, "Kattoor Beach")
        self.assertEqual(merged[0].source_count, 3)

    def test_same_name_far_apart_not_merged(self):
        recs = [rec("Beach Road Park", 9.0, 76.0), rec("Beach Road Park", 10.0, 77.0)]
        self.assertEqual(len(merge_places(recs)), 2)

    def test_name_subset_only_merges_when_very_close(self):
        near = merge_places([rec("Odayam Beach", 8.7, 76.7), rec("Odayam Beach cliff", 8.7005, 76.7)])
        far = merge_places([rec("Odayam Beach", 8.7, 76.7), rec("Odayam Beach cliff", 8.75, 76.7)])
        self.assertEqual((len(near), len(far)), (1, 2))

    def test_multi_interest_scores_higher(self):
        a = rec("A", 1, 1); b = rec("B", 1, 1); b.interests.add("viewpoints")
        self.assertGreater(score_place(b, 15000), score_place(a, 15000))

    def test_diversity_beats_one_interest_flooding(self):
        beaches = [rec(f"Beach {i}", 9 + i * 0.1, 76, "beaches") for i in range(10)]
        nature = [rec("Reserve X", 10.5, 77, "nature", ("national_park",)),
                  rec("Park Y", 10.6, 77.1, "nature", ("national_park",))]
        for p in beaches + nature:
            p.score = score_place(p, 15000)
        from travel_agent.interests import PROFILES
        profiles = [p for p in PROFILES if p.key in ("beaches", "nature")]
        chosen = select_diverse(beaches + nature, profiles, 6)
        names = {p.name for p in chosen}
        self.assertTrue({"Reserve X", "Park Y"} <= names)
        self.assertEqual(len(chosen), 6)

    def test_crowding_penalty_spreads_results(self):
        close = [rec(f"Close {i}", 9.0, 76.0 + i * 0.0001, "beaches") for i in range(3)]
        farther = rec("Far", 9.0, 76.5, "beaches")
        for p in close + [farther]:
            p.score = 3.0
        from travel_agent.interests import PROFILES
        chosen = select_diverse(close + [farther], [PROFILES[0]], 2)
        self.assertIn("Far", {p.name for p in chosen})


# ------------------------------------------------------------ end-to-end search
def kerala_handler(fail_area=None, fail_places_for=None):
    towns = {
        "Munnar": (10.0889, 77.0595), "Varkala": (8.7379, 76.7163),
    }

    def handler(url, params):
        if url == GEOCODE_URL:
            if params.get("filter") is None:  # destination -> country
                return fc(geo_feature("Kerala", 10.5, 76.5, rtype="state"))
            for t, (la, lo) in towns.items():
                if t in params["text"]:
                    if fail_area == t:
                        return err("network")
                    return fc(geo_feature(t, la, lo))
            return fc()
        if url == PLACES_URL:
            cats = params["categories"]
            lon, lat = params["filter"].split(":")[1].split(",")[:2]
            if fail_places_for and fail_places_for in cats:
                return err("http", 500)
            if "beach" in cats and float(lat) < 9:
                return fc(
                    place_feature("Varkala Beach", 8.7330, 76.7060, ["beach"], "b1"),
                    place_feature("Varkala Beach", 8.7331, 76.7061, ["beach", "tourism"], "b2"),
                )
            if "viewpoint" in cats and float(lat) > 10:
                return fc(
                    place_feature("Hill Top View Point", 10.06, 77.04,
                                  ["tourism", "tourism.attraction", "tourism.attraction.viewpoint"], "v1"),
                    place_feature("Some Pharmacy", 10.07, 77.05, ["commercial.health_and_beauty.pharmacy"], "x"),
                    {"properties": {"categories": ["beach"]}},  # no name, no coords
                )
            return fc()
        raise AssertionError(url)
    return handler


class SearchEndToEnd(unittest.TestCase):
    AREAS = ["Munnar, Idukki, Kerala, India", "Varkala, Thiruvananthapuram, Kerala, India"]

    def run_search(self, client=None, **kw):
        client = client or FakeClient(kerala_handler())
        return run_place_search(client, "Kerala, India", "beaches, scenic viewpoints",
                                self.AREAS, **kw), client

    def test_happy_path(self):
        out, c = self.run_search()
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["country_code"], "in")
        names = [p["name"] for p in out["places"]]
        self.assertEqual(names.count("Varkala Beach"), 1)  # merged
        self.assertNotIn("Some Pharmacy", names)
        self.assertEqual(out["diagnostics"]["duplicates_merged"], 1)
        self.assertEqual(out["diagnostics"]["rejected"]["no_matching_category"], 1)
        self.assertEqual(out["diagnostics"]["rejected"]["no_name"], 1)
        km = out["straight_line_km_between_areas"][0]["km"]
        self.assertAlmostEqual(km, 154.9, delta=1.0)  # haversine of the two fixture points
        self.assertIn("straight-line", out["distance_note"])
        for p in out["places"]:
            self.assertIn("lat", p); self.assertIn("lon", p)

    def test_country_filter_used_for_areas(self):
        _, c = self.run_search()
        geocodes = [p for u, p in c.calls if u == GEOCODE_URL and p.get("filter")]
        self.assertTrue(all(p["filter"] == "countrycode:in" for p in geocodes))

    def test_one_area_failing_keeps_the_rest(self):
        c = FakeClient(kerala_handler(fail_area="Munnar"))
        out, _ = self.run_search(c)
        self.assertEqual(out["status"], "partial")
        self.assertTrue(any(p["name"] == "Varkala Beach" for p in out["places"]))
        self.assertEqual(out["areas"][0]["status"], "failed")

    def test_one_interest_query_failing_is_reported(self):
        c = FakeClient(kerala_handler(fail_places_for="viewpoint"))
        out, _ = self.run_search(c)
        self.assertTrue(any("scenic viewpoints" in w for w in out["warnings"]))
        self.assertTrue(out["places"])

    def test_auth_error_aborts_with_message_and_no_key_leak(self):
        real = GeoapifyError("auth", "Geoapify rejected the API key (check GEOAPIFY_API_KEY).", 401)
        c = FakeClient(lambda u, p: real)
        out, _ = self.run_search(c, country_code="in")
        self.assertEqual(out["status"], "error")
        self.assertIn("API key", out["message"])

    def test_rate_limit_stops_but_returns_partial(self):
        def handler(url, params):
            if url == GEOCODE_URL and params.get("filter") is None:
                return fc(geo_feature("Kerala", 10.5, 76.5, rtype="state"))
            if url == GEOCODE_URL:
                return fc(geo_feature("Munnar", 10.0889, 77.0595))
            return err("rate_limit", 429)
        out, _ = self.run_search(FakeClient(handler))
        self.assertEqual(out["status"], "partial")
        self.assertEqual(out["places"], [])

    def test_unmapped_interest_reported(self):
        out = run_place_search(FakeClient(kerala_handler()), "Kerala, India",
                               "beaches, waterfalls", self.AREAS, country_code="in")
        self.assertEqual(out["unmapped_interests"], ["waterfalls"])
        self.assertTrue(any("waterfalls" in w for w in out["warnings"]))

    def test_unresolvable_areas_need_clarification(self):
        c = FakeClient(lambda u, p: fc())
        out = run_place_search(c, "Nowhere", "beaches", ["Nowhere, Nowhere"], country_code="in")
        self.assertEqual(out["status"], "needs_clarification")

    def test_ambiguous_destination_asks_user(self):
        def handler(url, params):
            return fc(
                geo_feature("Paris", 48.85, 2.35, cc="fr", country="France", state="Ile-de-France"),
                geo_feature("Paris", 33.66, -95.55, cc="us", country="United States", state="Texas"),
            )
        out = run_place_search(FakeClient(handler), "Paris", "museums", ["Paris"])
        self.assertEqual(out["status"], "needs_clarification")
        self.assertEqual(len(out["alternatives"]), 2)

    def test_input_validation(self):
        c = FakeClient(kerala_handler())
        for kwargs in (
            dict(destination="", interests="beaches"),
            dict(destination="X", interests=" "),
            dict(destination="X", interests="beaches", max_results=0),
            dict(destination="X", interests="beaches", max_results=True),
            dict(destination="X", interests="beaches", country_code="india"),
        ):
            self.assertEqual(run_place_search(c, **kwargs)["status"], "invalid_input", kwargs)
        self.assertEqual(c.calls, [])

    def test_wrapper_rejects_oversized_inputs(self):
        cases = (
            ("A" * 201, "nature"),
            ("Jaipur", "A" * 501),
        )
        for destination, interests in cases:
            with self.subTest(
                destination_length=len(destination),
                interests_length=len(interests),
            ):
                out = tools.search_places(destination, interests)
                self.assertEqual(out["status"], "invalid_input")

    def test_wrapper_rejects_excessive_search_areas(self):
        out = tools.search_places(
            "Jaipur",
            "nature",
            search_areas=["Area"] * 9,
        )
        self.assertEqual(out["status"], "invalid_input")
        self.assertIn("8", out["message"])

    def test_wrapper_rejects_invalid_limits_and_country_codes(self):
        cases = (
            {"max_results": 31},
            {"country_code": "IND"},
        )
        for extra in cases:
            with self.subTest(extra=extra):
                out = tools.search_places("Jaipur", "nature", **extra)
                self.assertEqual(out["status"], "invalid_input")

    def test_missing_api_key(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            out = tools.search_places("Kerala, India", "beaches")
        self.assertEqual(out["status"], "error")
        self.assertIn("GEOAPIFY_API_KEY", out["message"])

    def test_output_is_json_serialisable(self):
        out, _ = self.run_search()
        json.dumps(out)


# --------------------------------------------------------------------- client
class FakeResponse:
    def __init__(self, status=200, payload=None, headers=None, bad_json=False):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.headers = headers or {}
        self._bad = bad_json

    def json(self):
        if self._bad:
            raise ValueError("bad json")
        return self._payload


class FakeSession:
    def __init__(self, *items):
        self.items = list(items)
        self.calls = 0

    def get(self, url, params=None, timeout=None):
        self.calls += 1
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def make_client(*items, **kw):
    sleeps = []
    s = FakeSession(*items)
    c = GeoapifyClient("SECRET123", session=s, sleep=sleeps.append, min_interval=0, **kw)
    return c, s, sleeps


class Client(unittest.TestCase):
    def test_retries_429_then_succeeds(self):
        c, s, sleeps = make_client(FakeResponse(429, headers={"Retry-After": "1"}),
                                   FakeResponse(200, {"ok": 1}))
        self.assertEqual(c.get("https://x/y", {}), {"ok": 1})
        self.assertEqual(s.calls, 2)
        self.assertTrue(sleeps and sleeps[0] >= 1)

    def test_gives_up_after_retries_with_rate_limit_kind(self):
        c, s, _ = make_client(*[FakeResponse(429)] * 3)
        with self.assertRaises(GeoapifyError) as cm:
            c.get("https://x/y", {})
        self.assertEqual((cm.exception.kind, s.calls), ("rate_limit", 3))

    def test_401_not_retried(self):
        c, s, _ = make_client(FakeResponse(401))
        with self.assertRaises(GeoapifyError) as cm:
            c.get("https://x/y", {})
        self.assertEqual((cm.exception.kind, s.calls), ("auth", 1))

    def test_timeout_retried_and_error_hides_key(self):
        boom = requests.Timeout("GET https://x/y?apiKey=SECRET123 timed out")
        c, s, _ = make_client(boom, boom, boom)
        with self.assertRaises(GeoapifyError) as cm:
            c.get("https://x/y", {})
        self.assertEqual(cm.exception.kind, "network")
        self.assertNotIn("SECRET123", str(cm.exception))
        self.assertIsNone(cm.exception.__cause__)

    def test_invalid_json_and_non_dict(self):
        c, _, _ = make_client(FakeResponse(200, bad_json=True))
        with self.assertRaises(GeoapifyError) as cm:
            c.get("https://x/y", {})
        self.assertEqual(cm.exception.kind, "malformed")
        c, _, _ = make_client(FakeResponse(200, payload=[1, 2]))
        with self.assertRaises(GeoapifyError):
            c.get("https://x/y", {})

    def test_other_4xx_not_retried(self):
        c, s, _ = make_client(FakeResponse(400))
        with self.assertRaises(GeoapifyError) as cm:
            c.get("https://x/y", {})
        self.assertEqual((cm.exception.kind, s.calls), ("http", 1))


# --------------------------------------------------------------------- budget
def base(**over):
    args = dict(total_budget=50000, days=4, currency="inr", travel_cost=10000,
                stay_per_night=3000, food_per_day=1000)
    args.update(over)
    return estimate_budget(**args)


class Budget(unittest.TestCase):
    def test_within_budget_math(self):
        r = base(activities_cost=2000, local_transport_per_day=500, contingency_pct=10)
        # 10000 + 3000*3 + 1000*4 + 500*4 + 2000 = 27000; +10% = 29700
        self.assertEqual(r["subtotal"], 27000.0)
        self.assertEqual(r["total_required"], 29700.0)
        self.assertEqual(r["remaining"], 20300.0)
        self.assertEqual((r["status"], r["currency"]), ("within_budget", "INR"))
        sources = {i["source"] for i in r["line_items"]}
        self.assertIn("assumption", sources)

    def test_shortfall(self):
        r = base(total_budget=10000)
        self.assertEqual(r["status"], "shortfall")
        self.assertGreater(r["shortfall"], 0)
        self.assertEqual(r["remaining"], 0.0)

    def test_nights_override_for_day_trip(self):
        self.assertEqual(base(days=1, nights=0)["line_items"][1]["amount"], 0.0)
        self.assertEqual(base(days=1)["line_items"][1]["amount"], 0.0)

    def test_invalid_inputs_all_reported(self):
        r = base(days=2.5, total_budget=float("nan"), travel_cost=float("inf"),
                 stay_per_night=-1, food_per_day=True, currency="₹")
        self.assertEqual(r["status"], "invalid_input")
        text = " ".join(r["errors"])
        for needle in ("days", "total_budget", "travel_cost", "stay_per_night",
                       "food_per_day", "currency"):
            self.assertIn(needle, text)

    def test_integer_valued_float_days_accepted(self):
        self.assertEqual(base(days=3.0)["status"], "within_budget")

    def test_bounds(self):
        self.assertEqual(base(days=0)["status"], "invalid_input")
        self.assertEqual(base(days=500)["status"], "invalid_input")
        self.assertEqual(base(nights=9)["status"], "invalid_input")
        self.assertEqual(base(contingency_pct=150)["status"], "invalid_input")
        self.assertEqual(base(total_budget="50000")["status"], "invalid_input")


if __name__ == "__main__":
    unittest.main()
