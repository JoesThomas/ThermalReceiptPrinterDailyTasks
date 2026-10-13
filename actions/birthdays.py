"""Validated, private CSV birthdays shared by import, web edits and receipts."""

import csv
import hashlib
import io
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from zoneinfo import ZoneInfo
from storage import file_lock, write_bytes

FILE = Path(__file__).resolve().parents[1] / "data" / "birthdays.csv"
FIELDS = ["Name", "Year", "Month", "Day", "Link to Profile", "ID"]
MAX_BYTES = 900_000
MAX_ROWS = 5000


def today():
    return datetime.now(ZoneInfo("Europe/London")).date()


def profile_url(value):
    if not isinstance(value, str):
        raise ValueError("Enter a valid Facebook profile URL or leave it blank.")
    value = value.strip()
    if not value:
        return ""
    url = urlsplit(value)
    if (
        url.scheme != "https"
        or url.netloc.lower() not in ("facebook.com", "www.facebook.com")
        or url.fragment
        or len(value) > 250
    ):
        raise ValueError(
            "Use an HTTPS Facebook profile URL without credentials or fragments."
        )
    path = url.path.strip("/")
    if path == "profile.php":
        query = parse_qs(url.query)
        if (
            set(query) != {"id"}
            or len(query["id"]) != 1
            or not query["id"][0].isdigit()
        ):
            raise ValueError("Use a Facebook profile.php URL with one numeric id.")
        return "https://facebook.com/profile.php?id=" + query["id"][0]
    if url.query or not re.fullmatch(r"[A-Za-z0-9._-]+", path):
        raise ValueError(
            "Use a direct Facebook profile URL without tracking parameters."
        )
    return "https://facebook.com/" + path


def record(name, year, month, day, profile="", key=""):
    if (
        not isinstance(name, str)
        or not name.strip()
        or len(name) > 120
        or any(ord(c) < 32 for c in name)
    ):
        raise ValueError("Enter a name of up to 120 characters on one line.")
    if any(isinstance(value, (bool, float)) for value in (year, month, day)):
        raise ValueError("Use whole numbers for birthday dates.")
    name = name.strip()
    if name.startswith(("=", "+", "-", "@")):
        raise ValueError("Names must not begin with spreadsheet formula characters.")
    try:
        year = int(year) if str(year or "").strip() else None
        month = int(month)
        day = int(day)
        date(year or 2000, month, day)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(
            "Enter a real birthday date; leave an unknown year blank."
        ) from None
    if year is not None and (
        not 1 <= year <= today().year or date(year, month, day) > today()
    ):
        raise ValueError("A date of birth cannot be in the future.")
    profile = profile_url(profile)
    key = key or hashlib.sha256((profile or name.casefold()).encode()).hexdigest()[:32]
    if not isinstance(key, str) or not re.fullmatch(r"[a-f0-9]{32}", key):
        raise ValueError("Invalid birthday record ID.")
    return dict(id=key, name=name, year=year, month=month, day=day, profile=profile)


def validate_rows(rows):
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        raise ValueError("Store no more than 5,000 birthdays.")
    ids = set()
    identities = set()
    name_profiles = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid birthday record.")
        if (
            type(row.get("month")) is not int
            or type(row.get("day")) is not int
            or (row.get("year") is not None and type(row["year"]) is not int)
        ):
            raise ValueError(
                "Birthday date fields must be integers; unknown years must be blank."
            )
        expected = record(
            row.get("name"),
            row.get("year"),
            row.get("month"),
            row.get("day"),
            row.get("profile", ""),
            row.get("id", ""),
        )
        if row != expected:
            raise ValueError("Birthday record fields need normalization.")
        identity = (
            ("profile", row["profile"])
            if row["profile"]
            else ("name", row["name"].casefold())
        )
        if row["id"] in ids or identity in identities:
            raise ValueError("Duplicate birthday identity; edit the existing entry.")
        matches = name_profiles.get(row["name"].casefold(), set())
        if matches and (not row["profile"] or "" in matches):
            raise ValueError(
                "A matching name without a distinct profile already exists. Review it before adding a duplicate."
            )
        name_profiles.setdefault(row["name"].casefold(), set()).add(row["profile"])
        ids.add(row["id"])
        identities.add(identity)
    return rows


def parse_csv(raw):
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise ValueError("Birthday CSV exceeds the 900 KB limit.")
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
        if (
            not reader.fieldnames
            or not set(FIELDS[:5]) <= set(reader.fieldnames)
            or len(reader.fieldnames) != len(set(reader.fieldnames))
            or set(reader.fieldnames) - set(FIELDS)
        ):
            raise ValueError(
                "Use Name, Year, Month, Day, Link to Profile and optional ID columns."
            )
        rows = []
        blank = 0
        duplicates = 0
        identities = {}
        for number, item in enumerate(reader, 2):
            if number > MAX_ROWS + 2:
                raise ValueError("CSV contains too many rows.")
            if not any(str(value or "").strip() for value in item.values()):
                blank += 1
                continue
            if None in item or any(value is None for value in item.values()):
                raise ValueError(f"CSV row {number} has the wrong number of columns.")
            try:
                row = record(
                    item["Name"],
                    item["Year"],
                    item["Month"],
                    item["Day"],
                    item["Link to Profile"],
                    item.get("ID", ""),
                )
            except ValueError as error:
                raise ValueError(f"CSV row {number}: {error}") from None
            identity = row["profile"] or row["name"].casefold()
            previous = identities.get(identity)
            if previous is not None:
                if previous == row:
                    duplicates += 1
                    continue
                raise ValueError(
                    f"CSV row {number} conflicts with an earlier birthday. Review it before importing."
                )
            identities[identity] = row
            rows.append(row)
        validate_rows(rows)
        return rows, dict(blank=blank, duplicates=duplicates)
    except (UnicodeError, csv.Error):
        raise ValueError("Use a valid UTF-8 birthday CSV.") from None


def csv_bytes(rows):
    validate_rows(rows)
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    for row in sorted(
        rows, key=lambda item: (item["month"], item["day"], item["name"].casefold())
    ):
        # Avoid spreadsheet formula execution when names are opened in a spreadsheet.
        name = row["name"]
        if name.startswith(("=", "+", "-", "@")):
            raise ValueError(
                "Names must not begin with spreadsheet formula characters."
            )
        writer.writerow(
            dict(
                zip(
                    FIELDS,
                    [
                        name,
                        row["year"] or "",
                        row["month"],
                        row["day"],
                        row["profile"],
                        row["id"],
                    ],
                )
            )
        )
    raw = output.getvalue().encode("utf-8")
    if len(raw) > MAX_BYTES:
        raise ValueError("Birthday CSV exceeds the 900 KB limit.")
    return raw


def load():
    try:
        with FILE.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
    except FileNotFoundError:
        return []
    rows, _ = parse_csv(raw)
    return rows


def import_csv(raw):
    incoming, report = parse_csv(raw)
    with file_lock(FILE):
        existing = load()
        by_id = {row["id"]: row for row in existing}
        # Re-imports never overwrite a person's web edits. Conflicts need review.
        existing_identity = {
            (row["profile"] or row["name"].casefold()): row for row in existing
        }
        added = 0
        for row in incoming:
            old = by_id.get(row["id"]) or existing_identity.get(
                row["profile"] or row["name"].casefold()
            )
            if old:
                if old != row:
                    raise ValueError(
                        "An imported birthday differs from a saved entry. Edit the saved record or review the CSV first."
                    )
                continue
            by_id[row["id"]] = row
            added += 1
        write_bytes(FILE, csv_bytes(list(by_id.values())))
    return dict(report, added=added, total=len(by_id))


def update(name="", year="", month="", day="", profile="", key="", remove=False):
    with file_lock(FILE):
        rows = load()
        if key and key not in {row["id"] for row in rows}:
            raise ValueError("Birthday changed; refresh before editing.")
        if remove:
            if not key:
                raise ValueError("Choose a birthday to remove.")
            result = [row for row in rows if row["id"] != key]
        else:
            value = record(name, year, month, day, profile, key)
            result = [row for row in rows if row["id"] != value["id"]] + [value]
            if not key and len(result) == len(rows):
                raise ValueError("Birthday already exists; use its edit form.")
        write_bytes(FILE, csv_bytes(result))


def upcoming(rows=None, day=None, days=7):
    day = day or today()
    rows = load() if rows is None else validate_rows(rows)
    result = []
    for row in rows:
        for offset in range(days + 1):
            stamp = day + timedelta(days=offset)
            if (stamp.month, stamp.day) == (row["month"], row["day"]):
                result.append(
                    dict(
                        row,
                        date=stamp.isoformat(),
                        when="Today"
                        if offset == 0
                        else "Tomorrow"
                        if offset == 1
                        else stamp.strftime("%a %d %b"),
                        age=stamp.year - row["year"]
                        if row["year"] is not None
                        else None,
                    )
                )
    return sorted(result, key=lambda item: (item["date"], item["name"].casefold()))


def receipt_lines(day=None):
    rows = upcoming(day=day)
    lines = []
    for row in rows[:10]:
        age = f" ({row['age']})" if row["age"] is not None else ""
        lines.append(row["when"] + ": " + row["name"] + age)
    if len(rows) > 10:
        lines.append(f"{len(rows) - 10} more birthdays; check the web list.")
    return lines
