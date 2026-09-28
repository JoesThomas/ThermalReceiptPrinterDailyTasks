"""Keep BBC feed selections limited to recent, substantive article links."""
from __future__ import annotations

from urllib.parse import urlparse
import re

BBC_LOCAL_FEED = "https://feeds.bbci.co.uk/news/england/birmingham_and_black_country/rss.xml"
BBC_SPORT_FEED = "https://feeds.bbci.co.uk/sport/rss.xml"

# Headlines that lead to a hub, live blog, preview or promotional feature.
NON_ARTICLE_HEADLINE = re.compile(
    r"^(?:watch|listen|live|latest|in pictures|photo(?:s)?|video|quiz|"
    r"what's on|things to do|your pictures|have your say|as it happened|"
    r"preview|how to watch|how to follow)\b",
    re.IGNORECASE,
)


def is_bbc_article(story, section):
    title = str(story.get("headline", "")).strip()
    link = str(story.get("link", "")).strip()
    published = story.get("published")
    if not title or len(title.split()) < 4 or NON_ARTICLE_HEADLINE.search(title):
        return False
    if published is None:  # A dated receipt must not silently carry an old item.
        return False
    parsed = urlparse(link)
    if parsed.scheme != "https" or parsed.hostname not in {
        "www.bbc.co.uk", "www.bbc.com", "feeds.bbci.co.uk"
    }:
        return False
    path = parsed.path.lower().rstrip("/")
    if any(segment in path.split("/") for segment in ("live", "videos", "video", "av")):
        return False
    if section == "local":
        # The dedicated regional feed establishes location. Require an article,
        # not its category landing page or a BBC Sport item.
        return bool(re.match(
            r"^/news/(?:articles/[a-z0-9]+|"
            r"uk-(?:england|scotland|wales|northern-ireland)-[a-z0-9-]+-[0-9]{5,}|"
            r"(?:england|scotland|wales|northern_ireland)/[a-z0-9_]+/articles/[a-z0-9]+)$",
            path,
        ))
    if section == "sport":
        return bool(re.match(
            r"^/sport/(?:[a-z-]+/)?(?:articles/[a-z0-9]+|[0-9]{5,})$",
            path,
        ))
    raise ValueError(f"Unknown BBC feed section: {section}")


def select_bbc_articles(stories, section, number):
    selected = []
    seen = set()
    for story in stories:
        if not is_bbc_article(story, section):
            continue
        key = story["link"].split("?")[0].rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        selected.append(story)
    # BBC RSS is normally newest first; explicitly sort when feeds reorder.
    selected.sort(key=lambda item: item["published"], reverse=True)
    return selected[:max(0, number)]
