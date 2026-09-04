"""
VINTAGE 1980s DAILY INFORMATION RECEIPT
NetumScan 80mm ESC/POS thermal printer

Contents:
- Date and time
- Today's Google Calendar events via iCal
- Full text of Google Doc #1
- Five random lines from Google Doc #2
- Stirchley, Birmingham weather
- Weather every 2 hours: temperature, humidity, wind and condition
- Compact black-bar temperature graph
- Daily weather summary
- Top 5 UK news headlines for the day
- Automatic paper cut

Install:
    pip install python-escpos requests icalendar recurring-ical-events pillow
"""

from datetime import datetime, date, time
from io import BytesIO
import random
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import requests
from PIL import Image, ImageDraw
from icalendar import Calendar
import recurring_ical_events
from escpos.printer import Usb

from googleapiclient.discovery import build


# ============================================================
# CONFIGURATION
# ============================================================

# Replace with your printer's actual USB IDs.
PRINTER_VENDOR_ID = 0x0416
PRINTER_PRODUCT_ID = 0x5011

# Google Calendar "Secret address in iCal format".
CALENDAR_ICAL_URL = "https://calendar.google.com/calendar/ical/joethomas1901%40gmail.com/private-fb28fd17525cc4967d24dd69f010e128/basic.ics"

# Google Docs IDs. The documents must be accessible without login.
GOOGLE_DOC_1_URL = "1VIkmwYqxB11zoMNIdV8CjNVAfUJp3_fAeBNVlBhaD3M"
GOOGLE_DOC_2_URL = "11SNp_UlxhLs6kHl0gzS5CDRL5gCsPzwBgkGXqJEhKUQ"
FOOD_SHOP_DOC_ID = "17nwmBjCyenKmzRN-Hz2rrhhEwvirVE7878SDBH_cS88"

# Stirchley, Birmingham.
LATITUDE = 52.4294
LONGITUDE = -1.92035
LOCATION_NAME = "STIRCHLEY"
LOCATION_REGION = "BIRMINGHAM, UK"

# Compact 80mm receipt width.
RECEIPT_WIDTH = 42

# Number of random lines from Google Doc #2.
RANDOM_LINES = 5

# Google News RSS feed for UK headlines.
NEWS_RSS_URL = (
    "https://news.google.com/rss?hl=en-GB&gl=GB&ceid=GB:en"
)
NEWS_HEADLINES = 5


# ============================================================
# WEATHER
# ============================================================

WEATHER_CODES = {
    0: "SUNNY",
    1: "MAINLY SUNNY",
    2: "PARTLY CLOUDY",
    3: "CLOUDY",
    45: "FOGGY",
    48: "FOGGY",
    51: "LIGHT DRIZZLE",
    53: "DRIZZLE",
    55: "HEAVY DRIZZLE",
    56: "FREEZING DRIZZLE",
    57: "FREEZING DRIZZLE",
    61: "LIGHT RAIN",
    63: "RAINY",
    65: "HEAVY RAIN",
    66: "FREEZING RAIN",
    67: "FREEZING RAIN",
    71: "LIGHT SNOW",
    73: "SNOWY",
    75: "HEAVY SNOW",
    77: "SNOW GRAINS",
    80: "RAIN SHOWERS",
    81: "RAIN SHOWERS",
    82: "HEAVY SHOWERS",
    85: "SNOW SHOWERS",
    86: "HEAVY SNOW",
    95: "THUNDERSTORM",
    96: "STORM / HAIL",
    99: "STORM / HAIL",
}


def weather_description(code):
    return WEATHER_CODES.get(code, "UNKNOWN")


def weather_graphic(code):
    if code == 0:
        return [
            r"       \  |  /",
            r"     --- ( ) ---",
            r"       /  |  \ ",
        ]

    if code in (1, 2):
        return [
            r"       \ | /",
            r"      -- O --",
            r"     .------.",
            r"    (  CLOUD  )",
        ]

    if code == 3:
        return [
            r"     .--------.",
            r"   .'          '.",
            r"  (    CLOUD     )",
            r"   '._        _.'",
        ]

    if code in (45, 48):
        return [
            "    ~ ~ ~ ~ ~ ~",
            "      F O G",
            "    ~ ~ ~ ~ ~ ~",
        ]

    if code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
        return [
            "     .--------.",
            "    (   CLOUD   )",
            "     '--------'",
            "      | | | | |",
        ]

    if code in (71, 73, 75, 77, 85, 86):
        return [
            "     .--------.",
            "    (   CLOUD   )",
            "     '--------'",
            "      * * * * *",
        ]

    if code in (95, 96, 99):
        return [
            "     .--------.",
            "    (   STORM   )",
            "     '--------'",
            "         /\\",
        ]

    return ["    WEATHER UNKNOWN"]


def get_weather():
    url = "https://api.open-meteo.com/v1/forecast"

    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "current": (
            "temperature_2m,"
            "relative_humidity_2m,"
            "apparent_temperature,"
            "weather_code,"
            "surface_pressure,"
            "wind_speed_10m,"
            "wind_direction_10m"
        ),
        "hourly": (
            "temperature_2m,"
            "relative_humidity_2m,"
            "wind_speed_10m,"
            "weather_code"
        ),
        "daily": (
            "temperature_2m_max,"
            "temperature_2m_min,"
            "sunrise,"
            "sunset,"
            "precipitation_probability_max"
        ),
        "forecast_days": 1,
        "temperature_unit": "celsius",
        "wind_speed_unit": "kmh",
        "pressure_unit": "hPa",
        "timezone": "Europe/London",
    }

    response = requests.get(url, params=params, timeout=15)
    response.raise_for_status()
    return response.json()


def get_two_hour_weather(weather):
    hourly = weather["hourly"]
    readings = []

    for i, timestamp in enumerate(hourly["time"]):
        dt = datetime.fromisoformat(timestamp)

        if dt.hour % 4 != 0:
            continue

        readings.append({
            "time": dt.strftime("%H:%M"),
            "temperature": hourly["temperature_2m"][i],
            "humidity": hourly["relative_humidity_2m"][i],
            "wind": hourly["wind_speed_10m"][i],
            "code": hourly["weather_code"][i],
        })

    return readings


# ============================================================
# FOOD SHOPPING LIST
# ============================================================

def get_food_shop_from_google_doc(doc_id):
    """Fetch and clean food shopping items from a Google Doc export."""
    url = f"https://docs.google.com/document/d/{doc_id}/export?format=txt"
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()

        # .lstrip('\ufeff') cleanly strips the hidden Byte Order Mark if it exists
        raw_text = response.text.lstrip('\ufeff')

        # Clean lines and ignore empty spacing
        items = [
            line.strip()
            for line in raw_text.splitlines()
            if line.strip()
        ]
        return items
    except Exception as e:
        print(f"Error fetching food shop document: {e}")
        return []


def add_food_shop_contents(todo_text, doc_id):
    """
    If 'food shop' appears in the to-do list, insert the
    contents of the Google Doc list immediately underneath it.
    """
    items = get_food_shop_from_google_doc(doc_id)

    if not items:
        return todo_text

    output = []

    for line in todo_text.splitlines():
        output.append(line)

        if re.search(r"\bfood\s+shop\b", line, re.IGNORECASE):
            for item in items:
                output.append(f"  - {item}")

    return "\n".join(output)


# ============================================================
# GOOGLE DOCS
# ============================================================

def get_google_doc_text(url):
    # Construct the export URL to download the document as a text file
    DOCUMENT_ID = "1VIkmwYqxB11zoMNIdV8CjNVAfUJp3_fAeBNVlBhaD3M"
    url = f"https://docs.google.com/document/d/{DOCUMENT_ID}/export?format=txt"
    try:
        response = requests.get(url).text
        return str(response)
    except requests.exceptions.RequestException as e:
        return f"Error fetching document: {e}"

def get_random_lines(number_of_lines):
    DOCUMENT_ID = "11SNp_UlxhLs6kHl0gzS5CDRL5gCsPzwBgkGXqJEhKUQ"
    url = f"https://docs.google.com/document/d/{DOCUMENT_ID}/export?format=txt"

    try:
        response = requests.get(url)
        response.raise_for_status()
        full_text = response.text

        # 2. Split text into lines and strip trailing whitespace/newlines
        raw_lines = full_text.splitlines()

        # 3. Clean text by removing completely empty lines
        clean_lines = [line.strip() for line in raw_lines if line.strip()]

        # 4. Check if the document has enough content
        if len(clean_lines) < number_of_lines:
            return (
                f"The document only has {len(clean_lines)} line(s). Printing all of them:"
            )

        # 5. Pick and print random unique lines
        random_lines = random.sample(clean_lines, number_of_lines)

        allfiles = "\n".join(random_lines)
        return allfiles

    except requests.exceptions.RequestException as e:
        return f"Error fetching document: {e}"

# ============================================================
# GOOGLE CALENDAR
# ============================================================

def get_calendar_events(ical_url):
    response = requests.get(ical_url, timeout=15)
    response.raise_for_status()

    calendar = Calendar.from_ical(response.content)

    today = date.today()

    start_of_day = datetime.combine(today, time.min)
    end_of_day = datetime.combine(today, time.max)

    events = recurring_ical_events.of(calendar).between(
        start_of_day,
        end_of_day,
    )

    results = []

    for event in events:
        summary = str(event.get("SUMMARY", "UNTITLED EVENT"))
        start = event.get("DTSTART")
        end = event.get("DTEND")

        if start is None:
            continue

        start_value = start.dt
        end_value = end.dt if end is not None else None

        if (
            isinstance(start_value, date)
            and not isinstance(start_value, datetime)
        ):
            time_string = "ALL DAY"
        else:
            time_string = start_value.strftime("%H:%M")

            if isinstance(end_value, datetime):
                time_string += "-" + end_value.strftime("%H:%M")

        results.append({
            "time": time_string,
            "title": summary,
        })

    results.sort(key=lambda item: item["time"])
    return results


# ============================================================
# NEWS
# ============================================================


def get_top_news_headlines(number=5):
    """Get the leading Google News UK RSS headlines for today."""
    response = requests.get(
        NEWS_RSS_URL,
        timeout=15,
        headers={"User-Agent": "Mozilla/5.0 (compatible; ReceiptNews/1.0)"},
    )
    response.raise_for_status()

    root = ET.fromstring(response.content)
    today = datetime.now(ZoneInfo("Europe/London")).date()

    today_items = []
    other_items = []

    for item in root.findall("./channel/item"):
        title_element = item.find("title")
        date_element = item.find("pubDate")

        if title_element is None or not title_element.text:
            continue

        title = " ".join(title_element.text.split())
        published = None

        if date_element is not None and date_element.text:
            try:
                published = parsedate_to_datetime(
                    date_element.text
                ).astimezone(ZoneInfo("Europe/London"))
            except (TypeError, ValueError, OverflowError):
                published = None

        if published is not None and published.date() == today:
            today_items.append(title)
        else:
            other_items.append(title)

        if len(today_items) >= number:
            break

    # Usually there will be more than five current-day stories. If
    # there are not, use the next feed entries as a fallback.
    headlines = today_items[:number]

    if len(headlines) < number:
        for title in other_items:
            if title not in headlines:
                headlines.append(title)
            if len(headlines) >= number:
                break

    return headlines


def print_news(printer, headlines):
    """Print five compact news headlines on the receipt."""
    print_line(printer, "=")

    printer.set(bold=True)
    left(printer, "TOP 5 NEWS HEADLINES")
    printer.set(bold=False)

    if not headlines:
        left(printer, "NO HEADLINES AVAILABLE")
        return

    for number, headline in enumerate(headlines[:NEWS_HEADLINES], 1):
        print_wrapped(
            printer,
            f"{number}. {headline}",
            width=40,
        )


# ============================================================
# COMPACT PRINTER HELPERS
# ============================================================


def setup_printer(printer):
    """Use compact standard ESC/POS text throughout."""
    printer.hw("init")
    printer.set(
        font="a",
        bold=False,
        double_height=False,
        double_width=False,
        align="left",
    )


def print_line(printer, character="-"):
    printer.text(character * RECEIPT_WIDTH + "\n")


def centre(printer, text):
    printer.set(align="center")
    printer.text(text + "\n")


def left(printer, text):
    printer.set(align="left")
    printer.text(text + "\n")


def boxed_line(printer, text):
    """Compact boxed line with no unnecessary padding."""
    available = RECEIPT_WIDTH - 2
    text = text.replace("\n", " ")[:available]
    printer.text("|" + text.ljust(available) + "|\n")


def print_wrapped(printer, text, width=40):
    """Wrap text to fit the compact receipt width."""
    words = text.split()
    line = ""

    for word in words:
        if len(line) + len(word) + 1 > width:
            if line:
                left(printer, line)
            line = word
        else:
            line = f"{line} {word}".strip()

    if line:
        left(printer, line)


# ============================================================
# COMPACT TEMPERATURE GRAPH
# ============================================================


def print_temperature_graph(printer, readings):
    """Print a compact monochrome bitmap temperature graph."""
    if not readings:
        return

    temperatures = [r["temperature"] for r in readings]

    graph_min = int(min(temperatures)) - 1
    graph_max = int(max(temperatures)) + 1

    if graph_min == graph_max:
        graph_max += 1

    image_width = 500
    image_height = 150

    image = Image.new(
        "1",
        (image_width, image_height),
        1,
    )

    draw = ImageDraw.Draw(image)

    left_margin = 38
    right_margin = 10
    top_margin = 8
    bottom_margin = 28

    graph_width = image_width - left_margin - right_margin
    graph_height = image_height - top_margin - bottom_margin

    x_axis = top_margin + graph_height

    # Axes.
    draw.line(
        (left_margin, top_margin, left_margin, x_axis),
        fill=0,
        width=1,
    )

    draw.line(
        (left_margin, x_axis, image_width - right_margin, x_axis),
        fill=0,
        width=1,
    )

    # Light horizontal reference lines.
    for step in range(4):
        value = graph_min + (graph_max - graph_min) * step / 3
        y = int(x_axis - graph_height * step / 3)

        draw.line(
            (
                left_margin,
                y,
                image_width - right_margin,
                y,
            ),
            fill=0,
            width=1,
        )

        draw.text(
            (3, y - 5),
            f"{value:.0f}",
            fill=0,
        )

    count = len(readings)

    if count == 1:
        spacing = graph_width
    else:
        spacing = graph_width / (count - 1)

    # Black bars.
    for index, reading in enumerate(readings):
        temperature = reading["temperature"]

        normalized = (temperature - graph_min) / (graph_max - graph_min)
        bar_height = int(normalized * graph_height)

        x = int(left_margin + index * spacing)
        bar_top = x_axis - bar_height

        draw.rectangle(
            (
                x - 4,
                bar_top,
                x + 4,
                x_axis,
            ),
            fill=0,
        )

        # Hour labels.
        draw.text(
            (x - 7, x_axis + 6),
            reading["time"][:2],
            fill=0,
        )

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)

    printer.image(buffer)
    printer.text("\n")


# ============================================================
# RECEIPT SECTIONS
# ============================================================


def print_header(printer):
    """Compact vintage machine-style header."""
    printer.set(
        align="center",
        font="a",
        bold=True,
        double_height=False,
        double_width=False,
    )

    printer.text("DAILY INFORMATION / DATA LOG\n")
    printer.set(bold=False)

    now = datetime.now()

    printer.text(now.strftime("%a %d %b %Y  %H:%M:%S").upper() + "\n")
    printer.text(f"{LOCATION_NAME} / {LOCATION_REGION}\n")
    print_line(printer, "=")


def print_calendar(printer, events):
    print_line(printer, "=")

    printer.set(bold=True)
    left(printer, "TODAY'S CALENDAR")
    printer.set(bold=False)

    if not events:
        left(printer, "NO EVENTS TODAY")
        return

    for event in events:
        print_wrapped(
            printer,
            f"{event['time']}  {event['title']}",
            width=40,
        )


def print_google_doc(printer, text):
    print_line(printer, "=")

    printer.set(bold=True)
    left(printer, "TO DO")
    printer.set(bold=False)

    for line in text.splitlines():
        line = line.lstrip("\ufeff")

        if line:
            print_wrapped(printer, line, width=40)
        else:
            # Keep only a single compact blank line.
            left(printer, "")


def print_random_document_lines(printer, text):
    print_line(printer, "=")

    printer.set(bold=True)
    left(printer, "EXERCISES TO DO")
    printer.set(bold=False)

    words = get_random_lines(RANDOM_LINES).split()

    for number, word in enumerate(words, start=1):
        print_wrapped(
            printer,
            f"{number}. {word}",
            width=40,
        )


def print_weather(printer, weather):
    current = weather["current"]
    daily = weather["daily"]
    readings = get_two_hour_weather(weather)

    print_line(printer, "=")

    printer.set(bold=True)
    centre(printer, "WEATHER STATION")
    printer.set(bold=False)

    centre(printer, LOCATION_NAME)
    centre(printer, LOCATION_REGION)

    print_line(printer)

    for line in weather_graphic(current["weather_code"]):
        centre(printer, line)

    current_temperature = current["temperature_2m"]
    current_condition = weather_description(current["weather_code"])

    printer.set(bold=True)

    centre(
        printer,
        f"{current_temperature:.1f}C  {current_condition}",
    )

    printer.set(bold=False)

    print_line(printer)

    printer.set(bold=True)
    left(printer, "CURRENT CONDITIONS")
    printer.set(bold=False)

    left(
        printer,
        f"TEMP {current_temperature:.1f}C"
        f"  FEELS {current['apparent_temperature']:.1f}C",
    )

    left(
        printer,
        f"HUM {current['relative_humidity_2m']:.0f}%"
        f"  WIND {current['wind_speed_10m']:.1f}km/h",
    )

    left(
        printer,
        f"PRESS {current['surface_pressure']:.0f}hPa"
        f"  DIR {current['wind_direction_10m']:.0f}deg",
    )

    print_line(printer)

    printer.set(bold=True)
    left(printer, "2-HOURLY WEATHER")
    printer.set(bold=False)

    for reading in readings:
        condition = weather_description(reading["code"])

        line = (
            f"{reading['time']} "
            f"{reading['temperature']:4.1f}C "
            f"{reading['humidity']:3.0f}% "
            f"{reading['wind']:4.1f}k "
            f"{condition}"
        )

        print_wrapped(
            printer,
            line,
            width=40,
        )

    print_line(printer)

    printer.set(bold=True)
    left(printer, "TEMPERATURE GRAPH")
    printer.set(bold=False)

    print_temperature_graph(
        printer,
        readings,

)
    print_line(printer)

    printer.set(bold=True)
    left(printer, "TODAY")
    printer.set(bold=False)

    left(
        printer,
        f"MAX {daily['temperature_2m_max'][0]:.1f}C"
        f"  MIN {daily['temperature_2m_min'][0]:.1f}C",
    )

    left(
        printer,
        f"RAIN {daily['precipitation_probability_max'][0]:.0f}%",
    )

    sunrise = datetime.fromisoformat(daily["sunrise"][0])
    sunset = datetime.fromisoformat(daily["sunset"][0])

    left(
        printer,
        f"SUN {sunrise.strftime('%H:%M')}" f"-{sunset.strftime('%H:%M')}",
    )


def print_footer(printer):
    print_line(printer, "=")
    printer.text("\n\n\n")


# ============================================================
# MAIN
# ============================================================


# ============================================================
# MAIN
# ============================================================


def main():
    print("Connecting to thermal printer...")

    printer = Usb(
        PRINTER_VENDOR_ID,
        PRINTER_PRODUCT_ID,
    )

    setup_printer(printer)
    print_header(printer)

    # 1. Google Calendar
    try:
        print("Downloading Google Calendar...")
        events = get_calendar_events(CALENDAR_ICAL_URL)
        print_calendar(printer, events)

    except Exception as error:
        print("Calendar error:", error)
        print_line(printer, "=")
        printer.set(bold=True)
        left(printer, "CALENDAR ERROR")
        printer.set(bold=False)
        left(printer, "DATA UNAVAILABLE")

    # 2. News Headlines
    try:
        print("Downloading today's news headlines...")
        headlines = get_top_news_headlines(NEWS_HEADLINES)
        print_news(printer, headlines)

    except Exception as error:
        print("News error:", error)
        print_line(printer, "=")
        printer.set(bold=True)
        left(printer, "NEWS ERROR")
        printer.set(bold=False)
        left(printer, "HEADLINES UNAVAILABLE")

    # 3. Google Doc #1 (To-Do List) & Food Shopping List
    try:
        print("Downloading Google Doc #1...")
        document_1 = get_google_doc_text(GOOGLE_DOC_1_URL)

        # We pass the content through the modifier function to inject the shopping list
        print("Processing To-Do text and linking Food Shop Doc...")
        document_1 = add_food_shop_contents(document_1, FOOD_SHOP_DOC_ID)

        print_google_doc(printer, document_1)

    except Exception as error:
        print("Document 1 error:", error)
        print_line(printer, "=")
        printer.set(bold=True)
        left(printer, "DOCUMENT 1 ERROR")
        printer.set(bold=False)

    # 4. Google Doc #2 (Exercises)
    try:
        print("Downloading Google Doc #2...")
        document_2 = get_google_doc_text(GOOGLE_DOC_2_URL)
        print_random_document_lines(printer, document_2)

    except Exception as error:
        print("Document 2 error:", error)
        print_line(printer, "=")
        printer.set(bold=True)
        left(printer, "DOCUMENT 2 ERROR")
        printer.set(bold=False)

    # 5. Weather Station
    try:
        print("Downloading Stirchley weather...")
        weather = get_weather()
        print_weather(printer, weather)

    except Exception as error:
        print("Weather error:", error)
        print_line(printer, "=")
        printer.set(bold=True)
        left(printer, "WEATHER ERROR")
        printer.set(bold=False)
        left(printer, "DATA UNAVAILABLE")

    # Finalize printing layout and feed
    print_footer(printer)

    # Trigger automatic cutter hardware loop
    printer.cut()
    print("Receipt printed successfully.")


if __name__ == "__main__":
    try:
        main()

    except KeyboardInterrupt:
        print("\nPrinting cancelled.")

    except Exception as error:
        print("\nFatal printer error:")
        print(error)
