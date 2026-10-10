"""Thin Geoapify HTTP client: timeouts, retries, throttling, safe errors.

The API key is sent as a query parameter (as in Geoapify's GET examples).
`requests` exception messages contain the full URL *including the key*, so
this module never logs or re-raises those messages.
"""

import logging
import time
from typing import Callable, Optional

import requests

log = logging.getLogger("travel_agent.geoapify")


class GeoapifyError(Exception):
    """kind: auth | rate_limit | http | network | malformed"""

    def __init__(self, kind: str, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.kind = kind
        self.status = status


class GeoapifyClient:
    def __init__(
        self,
        api_key: str,
        *,
        session: Optional[requests.Session] = None,
        timeout=(5, 20),
        max_retries: int = 2,
        backoff: float = 0.6,
        # Free plan allows up to 5 requests/second (geoapify.com/pricing).
        min_interval: float = 0.25,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        if not api_key:
            raise ValueError("api_key is required")
        self._key = api_key
        self._session = session or requests.Session()
        self._timeout = timeout
        self._max_retries = max_retries
        self._backoff = backoff
        self._min_interval = min_interval
        self._sleep = sleep
        self._clock = clock
        self._last_call = None
        self.request_count = 0

    def _throttle(self):
        if self._last_call is not None and self._min_interval > 0:
            wait = self._min_interval - (self._clock() - self._last_call)
            if wait > 0:
                self._sleep(wait)
        self._last_call = self._clock()

    def get(self, url: str, params: dict) -> dict:
        full = {**params, "apiKey": self._key}
        endpoint = url.split("?")[0]

        for attempt in range(self._max_retries + 1):
            self._throttle()
            self.request_count += 1
            last = attempt == self._max_retries

            try:
                resp = self._session.get(url, params=full, timeout=self._timeout)
            except (requests.Timeout, requests.ConnectionError):
                log.warning("network error calling %s (attempt %d)", endpoint, attempt + 1)
                if last:
                    raise GeoapifyError("network", "Could not reach Geoapify.") from None
                self._sleep(self._backoff * 2**attempt)
                continue
            except requests.RequestException:
                raise GeoapifyError("network", "Request to Geoapify failed.") from None

            status = resp.status_code

            if status in (401, 403):
                raise GeoapifyError(
                    "auth", "Geoapify rejected the API key (check GEOAPIFY_API_KEY).", status
                )

            if status == 429 or status >= 500:
                log.warning("HTTP %s from %s (attempt %d)", status, endpoint, attempt + 1)
                if last:
                    kind = "rate_limit" if status == 429 else "http"
                    raise GeoapifyError(kind, f"Geoapify returned HTTP {status}.", status)
                delay = self._backoff * 2**attempt
                retry_after = resp.headers.get("Retry-After") if resp.headers else None
                try:
                    delay = max(delay, min(float(retry_after), 5.0))
                except (TypeError, ValueError):
                    pass
                self._sleep(delay)
                continue

            if status >= 400:
                raise GeoapifyError("http", f"Geoapify returned HTTP {status}.", status)

            try:
                data = resp.json()
            except ValueError:
                raise GeoapifyError("malformed", "Geoapify returned invalid JSON.") from None
            if not isinstance(data, dict):
                raise GeoapifyError("malformed", "Geoapify returned an unexpected payload.")
            return data

        raise GeoapifyError("network", "Could not reach Geoapify.")  # pragma: no cover
