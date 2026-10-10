"""Fakes and builders for mocked Geoapify responses."""

from travel_agent.geoapify import GeoapifyError


class FakeClient:
    """Stands in for GeoapifyClient. handler(url, params) -> dict | Exception."""

    def __init__(self, handler):
        self.handler = handler
        self.calls = []
        self.request_count = 0

    def get(self, url, params):
        self.calls.append((url, dict(params)))
        self.request_count += 1
        out = self.handler(url, params)
        if isinstance(out, Exception):
            raise out
        return out


def geo_feature(name, lat, lon, *, cc="in", rtype="city", confidence=1.0,
                state="Kerala", county=None, country="India", formatted=None):
    props = {
        "name": name, "city": name, "lat": lat, "lon": lon,
        "country_code": cc, "country": country, "state": state,
        "result_type": rtype, "rank": {"confidence": confidence},
        "formatted": formatted or f"{name}, {state}, {country}",
    }
    if county:
        props["county"] = county
    return {"type": "Feature", "properties": props,
            "geometry": {"type": "Point", "coordinates": [lon, lat]}}


def place_feature(name, lat, lon, categories, place_id=None):
    props = {
        "name": name, "lat": lat, "lon": lon, "categories": categories,
        "formatted": f"{name}, India",
    }
    if place_id:
        props["place_id"] = place_id
    return {"type": "Feature", "properties": props,
            "geometry": {"type": "Point", "coordinates": [lon, lat]}}


def fc(*features):
    return {"type": "FeatureCollection", "features": list(features)}


def err(kind, status=None):
    return GeoapifyError(kind, f"{kind} error", status)
