"""Deterministic production-renderer fixtures without credentials, APIs or hardware."""

import base64
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from receipt.capture import RecordingPrinter, receipt_blocks
from receipt.live_preview import VirtualPrinter
from receipt.location_settings import DEFAULT_LOCATION
from receipt.profile import COLUMNS
from receipt.weather_renderers import print_weather, WeatherDependencies
from receipt.visual_sample import example_pages
from finance.test_receipt import build, receipt

TODAY = date(2026, 10, 11)


def weather_capture():
    temperatures = [
        9,
        8.8,
        8.5,
        8.4,
        8.2,
        7.8,
        7.5,
        7.3,
        8.4,
        9.5,
        10.7,
        12.1,
        13.2,
        13.8,
        14.1,
        14.1,
        14,
        13.5,
        13,
        12.5,
        12.3,
        12.2,
        12.2,
        12.2,
    ]
    data = {
        "current": {
            "time": "2026-10-11T12:00",
            "weather_code": 3,
            "temperature_2m": 12.2,
            "apparent_temperature": 11.0,
            "relative_humidity_2m": 79,
            "wind_speed_10m": 8.6,
            "surface_pressure": 1013,
            "wind_direction_10m": 220,
        },
        "daily": {
            "temperature_2m_max": [14.1],
            "temperature_2m_min": [7.3],
            "precipitation_probability_max": [0],
            "sunrise": ["2026-10-11T07:25"],
            "sunset": ["2026-10-11T18:22"],
        },
        "hourly": {
            "time": [f"2026-10-11T{hour:02d}:00" for hour in range(24)],
            "temperature_2m": temperatures,
            "relative_humidity_2m": [79] * 24,
            "wind_speed_10m": [8.6] * 24,
            "weather_code": [3] * 24,
        },
    }
    printer = RecordingPrinter(VirtualPrinter(), defer=True)
    print_weather(
        printer,
        data,
        DEFAULT_LOCATION,
        deps=WeatherDependencies(now=lambda: datetime(2026, 10, 11, 12)),
    )
    return "".join(printer.lines), printer.images


def full_capture():
    weather, images = weather_capture()
    pages = example_pages(TODAY)
    source = {
        "valid": True,
        "cash": Decimal(2000),
        "buffer": Decimal(1000),
        "daily": Decimal(10),
        "events": [
            {"name": "Amex payment", "date": date(2026, 10, 25), "amount": Decimal(50)}
        ],
        "warnings": [],
        "amex": {"balance": Decimal(150), "scheduled": True, "full_reserved": False},
    }
    result = build(
        source,
        {
            "salary": "3000",
            "other_income": "0",
            "start": str(TODAY),
            "months": "2",
            "strategy": "amex_first",
            "save_all": "on",
        },
        TODAY,
    )
    text = (
        weather
        + "\n--- CUT ---\n"
        + pages["actions"]
        + "\n--- CUT ---\n"
        + pages["food"]
        + "\n--- CUT ---\n"
        + receipt(result, TODAY)
    )
    return text, images


def bitmap(text, images):
    blocks = receipt_blocks(text, images)
    font = ImageFont.load_default_imagefont()
    text_width = int(COLUMNS * font.getlength("0"))
    width = text_width + 48
    rows = []
    for block in blocks:
        if "text" in block:
            rows.extend(("text", line) for line in block["text"].splitlines())
        else:
            rows.append(
                (
                    "image",
                    Image.open(
                        BytesIO(base64.b64decode(block["image"].split(",", 1)[1]))
                    ).convert("1"),
                )
            )
    rows = [
        (
            kind,
            value.resize(
                (text_width, round(value.height * text_width / value.width)),
                Image.Resampling.NEAREST,
            )
            if kind == "image"
            else value,
        )
        for kind, value in rows
    ]
    height = sum(14 if kind == "text" else value.height for kind, value in rows) + 16
    image = Image.new("1", (width, height), 1)
    draw = ImageDraw.Draw(image)
    y = 8
    for kind, value in rows:
        if kind == "text":
            draw.text(((width - text_width) // 2, y), value, font=font, fill=0)
            y += 14
        else:
            image.paste(value, ((width - text_width) // 2, y))
            y += value.height
    return image
