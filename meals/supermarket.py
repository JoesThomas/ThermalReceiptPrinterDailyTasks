"""Create a reviewed supermarket list and, when configured, a partner handoff."""

import hashlib
import json
import os
import re
from urllib.parse import quote, urlencode

import requests

from meals.ingredients import aggregate, parse

RETAILERS = {
    "tesco": ("Tesco", "https://www.tesco.com/shop/en-GB/search?{}", "query", "Tesco"),
    "sainsburys": (
        "Sainsbury’s",
        "https://www.sainsburys.co.uk/groceries/search?{}",
        "searchTerm",
        "Sainsbury's",
    ),
    "asda": ("Asda", "https://groceries.asda.com/search/{}", None, None),
    "morrisons": ("Morrisons", "https://groceries.morrisons.com/search?{}", "q", None),
    "waitrose": (
        "Waitrose & Partners",
        "https://www.waitrose.com/ecom/shop/search?{}",
        "searchTerm",
        None,
    ),
    "ocado": ("Ocado", "https://www.ocado.com/search?{}", "q", "Ocado"),
}
SHOPS_HOME = {
    "tesco": "https://www.tesco.com/groceries/",
    "sainsburys": "https://www.sainsburys.co.uk/groceries/",
    "asda": "https://groceries.asda.com/",
    "morrisons": "https://groceries.morrisons.com/",
    "waitrose": "https://www.waitrose.com/ecom/shop",
    "ocado": "https://www.ocado.com/",
}
TOKEN_ENV = "SAMSUNG_FOOD_SERVER_TOKEN"
TRANSFER_URL = "https://graph.whisk.com/v1/lists/transfers"
LANDING = re.compile(
    r"https://graph\.whisk\.com/v1/lists/transfers/[a-f0-9]{32}/landing"
)
MAX_LINES = 150
MAX_LINE = 300


class HandoffError(ValueError):
    pass


def search_url(retailer, term):
    _, pattern, query, _ = RETAILERS[retailer]
    return pattern.format(urlencode({query: term}) if query else quote(term, safe=""))


def available(retailer):
    return bool(RETAILERS[retailer][3] and os.environ.get(TOKEN_ENV, "").strip())


def review(visits, retailer):
    """Combine exact recipe quantities, without adding the rounded pack counts."""
    flags = {}
    ingredients = []
    for visit in visits:
        for item in visit["items"]:
            for line in item["requirements"]:
                ingredients.append(line)
                parsed = parse(line)
                key = (parsed[1], parsed[2]) if parsed else (None, line.casefold())
                flags[key] = flags.get(key, False) or item["pantry"]
    rows = []
    for line in aggregate(ingredients):
        parsed = parse(line)
        key = (parsed[1], parsed[2]) if parsed else (None, line.casefold())
        rows.append(
            dict(
                id=str(len(rows)),
                amount=line,
                pantry=flags.get(key, False),
                measured=bool(parsed and parsed[0] > 0 and parsed[1] != "handful"),
                search=search_url(retailer, parsed[3] if parsed else line)
                if retailer
                else None,
            )
        )
    fingerprint = hashlib.sha256(
        json.dumps([retailer, rows], sort_keys=True).encode()
    ).hexdigest()
    return rows, fingerprint


def transfer(retailer, lines):
    alias = RETAILERS[retailer][3]
    token = os.environ.get(TOKEN_ENV, "").strip()
    if not alias or not token:
        raise HandoffError("Basket handoff is unavailable for this supermarket.")
    if not 1 <= len(lines) <= MAX_LINES or any(
        not isinstance(line, str)
        or not line.strip()
        or len(line) > MAX_LINE
        or any(ord(c) < 32 for c in line)
        for line in lines
    ):
        raise HandoffError("Select a shorter list of ingredients to send.")
    try:
        with requests.post(
            TRANSFER_URL,
            headers={"Authorization": f"Token {token}", "Accept": "application/json"},
            json=dict(
                country="GB",
                language="en",
                allowedRetailers=[f"GB:{alias}"],
                rawItems=lines,
            ),
            timeout=(3, 8),
            allow_redirects=False,
            stream=True,
        ) as response:
            if not 200 <= response.status_code < 300:
                raise HandoffError(
                    "Samsung Food did not accept this list. You can copy it or use the shop links below."
                )
            payload = bytearray()
            for chunk in response.iter_content(4096):
                payload.extend(chunk)
                if len(payload) > 16384:
                    raise HandoffError(
                        "Samsung Food returned an unexpected response. Use the local shopping list below."
                    )
            result = json.loads(payload)
    except (requests.RequestException, UnicodeError, json.JSONDecodeError):
        raise HandoffError(
            "Could not connect to Samsung Food. Your local shopping list is still available."
        ) from None
    url = result.get("landingUrl") if isinstance(result, dict) else None
    if not isinstance(url, str) or not LANDING.fullmatch(url):
        raise HandoffError(
            "Samsung Food did not return a recognised shopping link. Use the local list below."
        )
    return url
