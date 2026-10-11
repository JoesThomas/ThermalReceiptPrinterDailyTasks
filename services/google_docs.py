"""Shared Google Docs identifiers and plain-text export URLs."""

import re


def document_id(value, *, strict=False, allow_empty=False):
    value = str(value or "").strip()
    if not value:
        if allow_empty:
            return ""
        raise ValueError("Google Docs URL/ID is empty.")
    match = re.search(r"/document/d/([a-zA-Z0-9_-]+)", value)
    if match:
        return match.group(1)
    if (
        strict and not re.fullmatch(r"[a-zA-Z0-9_-]{20,}", value)
    ) or "docs.google.com" in value:
        raise ValueError("Could not find a Google Docs document ID.")
    return value


def export_url(identifier):
    return f"https://docs.google.com/document/d/{identifier}/export?format=txt"
