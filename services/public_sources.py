"""Bounded public downloads with short-lived cache and explicit stale fallback."""
import json
import time
import requests
from services.source_cache import get


def download(name, url, params=None):
    deadline = time.monotonic() + 12
    from services.api_health import observed_request
    response = observed_request(name, "get", url, params=params, timeout=(3, 5), stream=True,
                            headers={'User-Agent': 'ReceiptNews/3.0'})
    try:
        response.raise_for_status()
        chunks = []; size = 0
        for chunk in response.iter_content(65536):
            size += len(chunk)
            if size > 2_000_000 or time.monotonic() > deadline:
                raise ValueError('Public source download limit reached')
            chunks.append(chunk)
        return b''.join(chunks)
    finally:
        response.close()


def cached(name, url, count, collect):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    # Never carry yesterday's headlines forward into today's receipt.
    today = datetime.now(ZoneInfo('Europe/London')).date().isoformat()
    return get(name, json.dumps([url, count, today]), collect, ttl=300, max_age=3600)


def weather(url, params):
    def collect():
        value = json.loads(download('Weather', url, params))
        if not isinstance(value, dict) or not isinstance(value.get('current'), dict) or not isinstance(value.get('hourly'), dict):
            raise ValueError('Invalid weather response')
        return [value]
    return cached('Weather', url, json.dumps(params, sort_keys=True), collect)[0]


def document(url):
    def collect():
        return [download('Google Docs', url).decode('utf-8-sig')]
    return get('Google Docs', url, collect, ttl=60, max_age=86400)[0]
