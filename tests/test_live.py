"""Opt-in live checks against Geoapify. NOT run by default and NOT yet run.

PowerShell:
    $env:RUN_LIVE_TESTS = "1"
    python -m unittest tests.test_live -v

Uses a few credits from the free 3,000/day quota (about 10 requests).
The key is read from the environment / .env and never printed.
"""

import os
import unittest

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # python-dotenv is optional here
    pass

from travel_agent.geoapify import GeoapifyClient
from travel_agent.location import resolve_location
from travel_agent.places import run_place_search

LIVE = os.getenv("RUN_LIVE_TESTS") == "1" and bool(os.getenv("GEOAPIFY_API_KEY"))


@unittest.skipUnless(LIVE, "set RUN_LIVE_TESTS=1 and GEOAPIFY_API_KEY to run")
class LiveGeoapify(unittest.TestCase):
    def setUp(self):
        self.client = GeoapifyClient(os.environ["GEOAPIFY_API_KEY"])

    def test_alias_resolves_inside_kerala(self):
        r = resolve_location(self.client, "Alleppey, Alappuzha, Kerala, India", country_code="in")
        print("\n[calibration] Alleppey ->", r.status, r.best and (r.best.label, r.best.confidence, r.best.result_type))
        self.assertEqual(r.status, "confirmed")
        self.assertTrue(9.0 < r.best.lat < 10.0)

    def test_country_filter_blocks_kochi_japan(self):
        r = resolve_location(self.client, "Kochi", country_code="in")
        print("\n[calibration] Kochi(in) ->", r.status, r.best and (r.best.label, r.best.confidence))
        if r.best:
            self.assertEqual(r.best.country_code, "in")

    def test_bare_ambiguous_name_without_country(self):
        r = resolve_location(self.client, "Springfield")
        print("\n[calibration] Springfield ->", r.status, [c.label for c in r.alternatives])

    def test_kerala_search_has_no_duplicates_and_multiple_interests(self):
        out = run_place_search(
            self.client, "Kerala, India", "beaches, mountains, nature, scenic viewpoints",
            ["Munnar, Idukki, Kerala, India", "Varkala, Thiruvananthapuram, Kerala, India"],
            country_code="in", max_results=10,
        )
        print("\n[diagnostics]", out.get("diagnostics"))
        names = [p["name"].casefold() for p in out["places"]]
        self.assertEqual(len(names), len(set(names)))
        self.assertLessEqual(len(names), 10)
        self.assertGreaterEqual(
            len({i for p in out["places"] for i in p["matches_interests"]}), 2)
