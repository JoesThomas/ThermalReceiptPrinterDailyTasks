"""Location inputs shared by receipt settings and the live collectors."""
from __future__ import annotations

import math
import re

DEFAULT_LOCATION = {
    "name": "Stirchley",
    "region": "Birmingham, UK",
    "latitude": 52.4294,
    "longitude": -1.92035,
    "local_news_label": "Birmingham & Black Country",
    "local_news_feed": "https://feeds.bbci.co.uk/news/england/birmingham_and_black_country/rss.xml",
}

BBC_LOCAL_RSS = re.compile(
    r"https://feeds\.bbci\.co\.uk/news/"
    r"(?:england|scotland|wales|northern_ireland)/"
    r"(?:[a-z0-9_]+/)?rss\.xml\Z"
)


def validate_location(values):
    """Return safe receipt labels, valid coordinates and a BBC local RSS URL."""
    result = {}
    for key, max_length in (("name", 18), ("region", 19), ("local_news_label", 35)):
        value = str(values.get(key, "")).strip()
        if not value or len(value) > max_length or any(ord(c) < 32 for c in value):
            raise ValueError(f"Enter a valid {key.replace('_', ' ')} (up to {max_length} characters).")
        result[key] = value
    for key, minimum, maximum in (("latitude", -90, 90), ("longitude", -180, 180)):
        try:
            value = float(values.get(key, ""))
        except (TypeError, ValueError) as error:
            raise ValueError(f"Enter a valid {key}.") from error
        if not math.isfinite(value) or not minimum <= value <= maximum:
            raise ValueError(f"Enter a valid {key}.")
        result[key] = value
    feed = str(values.get("local_news_feed", "")).strip().lower()
    if not BBC_LOCAL_RSS.fullmatch(feed):
        raise ValueError("Use a BBC local RSS URL from feeds.bbci.co.uk/news/.")
    result["local_news_feed"] = feed
    return result
