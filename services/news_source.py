"""Bounded RSS collection and parsing, separate from receipt formatting."""
from datetime import datetime
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo
from services.public_sources import download

def stories(
    url,
    number=3,
    params=None,
    max_age_hours=None,
    *, sanitize, compact_summary, useful_summary,
):
    from services.safe_xml import parse_feed
    root = parse_feed(download('News feed', url, params=params))

    now = datetime.now(
        ZoneInfo("Europe/London")
    )

    stories = []

    for item in root.findall(
        "./channel/item"
    ):
        title_el = item.find("title")
        desc_el = item.find("description")
        date_el = item.find("pubDate")
        link_el = item.find("link")

        if (
            title_el is None
            or not title_el.text
        ):
            continue

        title = sanitize(
            " ".join(
                title_el.text.split()
            )
        )

        source = ""

        if " - " in title:
            title, source = title.rsplit(
                " - ",
                1,
            )

            title = title.strip()
            source = source.strip()

        # -----------------------------
        # PUBLICATION AGE
        # -----------------------------

        published = None

        if (
            date_el is not None
            and date_el.text
        ):
            try:
                published = (
                    parsedate_to_datetime(
                        date_el.text
                    )
                    .astimezone(
                        ZoneInfo(
                            "Europe/London"
                        )
                    )
                )
            except (
                TypeError,
                ValueError,
                OverflowError,
            ):
                published = None

        if (
            max_age_hours is not None
            and published is not None
        ):
            age_hours = (
                now - published
            ).total_seconds() / 3600

            if (
                age_hours < 0
                or age_hours > max_age_hours
            ):
                continue

        # -----------------------------
        # SUMMARY
        # -----------------------------

        description = (
            desc_el.text
            if (
                desc_el is not None
                and desc_el.text
            )
            else ""
        )

        summary = compact_summary(
            description
        )

        # Don't print a second copy of the
        # headline as the article body.
        if not useful_summary(
            title,
            summary,
        ):
            summary = ""

        stories.append({
            "headline": title,
            "summary": summary,
            "published": published,
            "source": source,
            "link": link_el.text.strip() if link_el is not None and link_el.text else "",
        })

        # Fetch a larger candidate pool.
        if len(stories) >= number:
            break

    return stories
