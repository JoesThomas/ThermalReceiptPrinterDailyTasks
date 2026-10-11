"""Bounded RSS parsing with entity declarations disabled."""
from defusedxml.ElementTree import fromstring
MAX_FEED_BYTES = 2_000_000

def parse_feed(content):
    if len(content) > MAX_FEED_BYTES:
        raise ValueError('News feed exceeds the supported size.')
    return fromstring(content, forbid_dtd=True, forbid_entities=True, forbid_external=True)
