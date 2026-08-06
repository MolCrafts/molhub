"""Shared JSON-over-HTTP helper for drivers that resolve through a REST API."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from molhub.registry.errors import BadStatus

_USER_AGENT = "molhub/0.1 (+https://github.com/MolCrafts/molhub)"
_MAX_BYTES = 8 * 1024 * 1024


def fetch_json(url: str, *, user_agent: str = _USER_AGENT) -> Any:
    """GET *url* and decode the response as JSON.

    Args:
        url: Endpoint to read.
        user_agent: Value sent as ``User-Agent``.

    Returns:
        The decoded payload.

    Raises:
        BadStatus: If the response status is not 200, or the body is not JSON.
            A 404 usually means a pinned version does not exist.
    """
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(request) as response:
            if response.status != 200:
                raise BadStatus(f"{url} returned HTTP {response.status}, expected 200.")
            body = response.read(_MAX_BYTES)
    except urllib.error.HTTPError as error:
        raise BadStatus(f"{url} returned HTTP {error.code}, expected 200.") from error
    try:
        return json.loads(body)
    except json.JSONDecodeError as error:
        raise BadStatus(f"{url} did not return JSON: {error}") from error
