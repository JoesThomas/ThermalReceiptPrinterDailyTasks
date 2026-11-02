"""Automatic address matching, with UK postcode fallback and visible accuracy notes."""

import re
from services.day_travel import point

POSTCODE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b", re.I)


def postcode(value):
    found = POSTCODE.search(value)
    return re.sub(r"\s", "", found[1]).upper() if found else ""


def variants(address):
    result = [address]
    parts = [p.strip() for p in address.split(",") if p.strip()]
    street = next(
        (i for i, p in enumerate(parts) if re.match(r"^\d+[A-Za-z]?\s", p)), None
    )
    if street is not None and street > 0:
        result.append(", ".join(parts[street:]))
    pc = POSTCODE.search(address)
    if pc:
        if street is not None:
            result.append(parts[street] + ", " + pc[1])
        result.append(pc[1])
    return list(dict.fromkeys(result))[:4]


def tokens(value):
    value = re.sub(
        r"\b(rd|st|ln|ave)\b",
        lambda m: dict(rd="road", st="street", ln="lane", ave="avenue")[m[0]],
        value.lower(),
    )
    return set(re.findall(r"[a-z0-9]+", value)) - {
        "the",
        "of",
        "uk",
        "united",
        "kingdom",
    }


def select(address, choices):
    expected = postcode(address)
    number = re.search(r"\b(\d+[A-Za-z]?)\s+[A-Za-z]", address)
    ranked = []
    for c in choices:
        props = c.get("match", {})
        candidate_postcode = postcode(props.get("postcode", "") or c.get("label", ""))
        candidate_number = str(props.get("housenumber", "")).strip().casefold()
        if expected:
            if candidate_postcode != expected:
                continue
            if number and candidate_number and number[1].casefold() != candidate_number:
                continue
            score = 100 + (10 if candidate_number else 0)
            approximate = bool(number and not candidate_number)
        else:
            required = tokens(address)
            overlap = len(required & tokens(c.get("label", ""))) / max(1, len(required))
            if len(required) < 2 or overlap < 0.75:
                continue
            score = overlap * 100
            approximate = False
        ranked.append((score, c, approximate))
    ranked.sort(key=lambda x: x[0], reverse=True)
    if not ranked:
        return None
    _, c, approximate = ranked[0]
    if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
        a, b = ranked[0][1]["point"], ranked[1][1]["point"]
        if abs(a[0] - b[0]) + abs(a[1] - b[1]) > 0.01:
            return None
    return dict(
        point=point(c["point"]),
        confirmed=True,
        source="Automatic address match",
        accuracy="Approximate street/postcode point; check the map."
        if approximate
        else "Matched address; check the map if it looks wrong.",
    )
