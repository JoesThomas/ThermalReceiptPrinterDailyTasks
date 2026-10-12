"""Weather rendering; compatibility helpers are injected by the live facade."""

from dataclasses import dataclass, fields
from datetime import datetime
from io import BytesIO
import math
from typing import Callable
from PIL import Image, ImageDraw
from receipt.local_time import uk_now
from receipt import output
from receipt.weather_symbols import weather_description, weather_graphic
from receipt.profile import printable_width
from services.weather_source import get_hourly_weather


@dataclass(frozen=True)
class WeatherDependencies:
    centre: Callable = output.centre
    left: Callable = output.left
    print_line: Callable = output.line
    print_wrapped: Callable = output.wrapped
    printer_text: Callable = output.text
    weather_graphic: Callable = weather_graphic
    weather_description: Callable = weather_description
    print_weather_graphic: Callable = None
    print_temperature_graph: Callable = None
    get_hourly_weather: Callable = get_hourly_weather
    datetime: object = datetime
    now: Callable = uk_now
    BytesIO: object = BytesIO
    Image: object = Image
    ImageDraw: object = ImageDraw
    math: object = math

    @classmethod
    def from_context(cls, context):
        # Transitional adapter for existing external callers and isolated legacy tests.
        return cls(
            **{f.name: context[f.name] for f in fields(cls) if f.name in context}
        )


def print_weather_graphic(printer, code, *, deps=None, _context=None):
    deps = deps or WeatherDependencies.from_context(_context or {})
    """Preserve drawing geometry when centring different-length ASCII rows."""
    centre = deps.centre
    weather_graphic = deps.weather_graphic
    rows = weather_graphic(code)
    margin = min((len(row) - len(row.lstrip(" ")) for row in rows))
    rows = [row[margin:].rstrip() for row in rows]
    width = max((len(row) for row in rows))
    for row in rows:
        centre(printer, row.ljust(width))
    centre(printer, "")


def print_compact_weather(printer, weather, location=None, *, deps=None, _context=None):
    deps = deps or WeatherDependencies.from_context(_context or {})
    left = deps.left
    print_line = deps.print_line
    weather_description = deps.weather_description
    current = weather["current"]
    daily = weather["daily"]
    condition = weather_description(current["weather_code"])
    high = float(daily["temperature_2m_max"][0])
    low = float(daily["temperature_2m_min"][0])
    print_line(printer, "=")
    printer.set(bold=True)
    left(printer, f"WEATHER / {location['name'].upper()}")
    printer.set(bold=False)
    left(printer, f"{current['temperature_2m']:.1f}C  {condition}")
    left(printer, f"HIGH {high:.1f}C / LOW {low:.1f}C")
    left(printer, "DRY WITH LIGHT WINDS")


def print_weather(
    printer, weather, location=None, detail=None, *, deps=None, _context=None
):
    deps = deps or WeatherDependencies.from_context(_context or {})
    centre = deps.centre
    datetime = deps.datetime
    get_hourly_weather = deps.get_hourly_weather
    left = deps.left
    print_line = deps.print_line
    render_graph = deps.print_temperature_graph or (
        lambda p, r: print_temperature_graph(p, r, deps=deps)
    )
    render_graphic = deps.print_weather_graphic or (
        lambda p, c: print_weather_graphic(p, c, deps=deps)
    )
    print_wrapped = deps.print_wrapped
    weather_description = deps.weather_description
    # Weather essentials are always present, including for legacy auto/compact settings.
    current = weather["current"]
    daily = weather["daily"]
    text_readings = get_hourly_weather(weather, interval_hours=1)
    graph_readings = text_readings
    print_line(printer, "=")
    printer.set(bold=True)
    centre(printer, "WEATHER")
    printer.set(bold=False)
    centre(printer, location["name"].upper())
    centre(printer, location["region"].upper())
    print_line(printer)
    printer.set(bold=True)
    left(printer, "TODAY")
    printer.set(bold=False)
    left(
        printer,
        f"MAX {daily['temperature_2m_max'][0]:.1f}C  MIN {daily['temperature_2m_min'][0]:.1f}C",
    )
    left(printer, f"RAIN {daily['precipitation_probability_max'][0]:.0f}%")
    sunrise = datetime.fromisoformat(daily["sunrise"][0])
    sunset = datetime.fromisoformat(daily["sunset"][0])
    left(
        printer,
        f"SUNRISE/SUNSET {sunrise.strftime('%H:%M')}-{sunset.strftime('%H:%M')}",
    )
    print_line(printer)
    render_graphic(printer, current["weather_code"])
    current_temperature = current["temperature_2m"]
    current_condition = weather_description(current["weather_code"])
    printer.set(bold=True)
    centre(printer, f"{current_temperature:.1f}C  {current_condition}")
    printer.set(bold=False)
    print_line(printer)
    printer.set(bold=True)
    left(printer, "CURRENT CONDITIONS")
    printer.set(bold=False)
    left(
        printer,
        f"TEMP {current_temperature:.1f}C  FEELS {current['apparent_temperature']:.1f}C",
    )
    left(
        printer,
        f"HUM {current['relative_humidity_2m']:.0f}%  WIND {current['wind_speed_10m']:.1f}km/h",
    )
    left(
        printer,
        f"PRESS {current['surface_pressure']:.0f}hPa  DIR {current['wind_direction_10m']:.0f}deg",
    )
    print_line(printer)
    printer.set(bold=True)
    left(printer, "TEMPERATURE GRAPH")
    printer.set(bold=False)
    render_graph(printer, graph_readings)
    print_line(printer)
    printer.set(bold=True)
    left(printer, "HOURLY WEATHER")
    printer.set(bold=False)
    left(printer, "TIME  TEMP  HUM  WIND(km/h)  WEATHER")
    left(printer, "> marks the current reading hour")
    current_time = current.get("time")
    try:
        current_hour = (
            datetime.fromisoformat(current_time).strftime("%H:00")
            if current_time
            else deps.now().strftime("%H:00")
        )
    except (TypeError, ValueError):
        current_hour = deps.now().strftime("%H:00")
    for reading in text_readings:
        condition = weather_description(reading["code"])
        line = f"{reading['time']} {reading['temperature']:4.1f}C {reading['humidity']:3.0f}% {reading['wind']:4.1f} {condition}"
        print_wrapped(
            printer, (">" if reading["time"] == current_hour else "") + line, width=40
        )
    print_line(printer)


def print_temperature_graph(printer, readings, *, deps=None, _context=None):
    deps = deps or WeatherDependencies.from_context(_context or {})
    """
    Print a compact monochrome stepped-line temperature graph.

    The hourly readings are connected using horizontal
    steps with vertical transitions. This gives the receipt a
    vintage weather-station / chart-recorder appearance while
    remaining a bitmap, so no Unicode graph characters are sent
    to the ESC/POS printer.
    """
    BytesIO = deps.BytesIO
    Image = deps.Image
    ImageDraw = deps.ImageDraw
    math = deps.math
    printer_text = deps.printer_text
    if not readings:
        return
    temperatures = [r["temperature"] for r in readings]
    span = max(temperatures) - min(temperatures)
    magnitude = 10 ** math.floor(math.log10(max(span / 4, 0.1)))
    tick = next(
        (magnitude * value for value in (1, 2, 5, 10) if magnitude * value >= span / 4)
    )
    graph_min = math.floor(min(temperatures) / tick) * tick
    graph_max = math.ceil(max(temperatures) / tick) * tick
    if graph_min == graph_max:
        graph_max += tick
    from PIL import ImageFont

    image_width = printable_width(printer)
    image_height = max(160, min(260, round(image_width * 0.35)))
    font = ImageFont.load_default(size=14)
    tick_count = round((graph_max - graph_min) / tick)
    tick_labels = [f"{graph_min + tick * step:g}C" for step in range(tick_count + 1)]
    label_width = max(
        font.getbbox(label)[2] - font.getbbox(label)[0] for label in tick_labels
    )
    image = Image.new("1", (image_width, image_height), 1)
    draw = ImageDraw.Draw(image)
    # Centre the plotting area, reserving the same minimal label gutter on each side.
    left_margin = right_margin = label_width + 12
    top_margin = 12
    bottom_margin = 42
    graph_width = image_width - left_margin - right_margin
    graph_height = image_height - top_margin - bottom_margin
    x_axis = top_margin + graph_height
    draw.line((left_margin, top_margin, left_margin, x_axis), fill=0, width=1)
    draw.line(
        (left_margin, x_axis, image_width - right_margin, x_axis), fill=0, width=1
    )
    for step in range(tick_count + 1):
        y = int(x_axis - graph_height * step / tick_count)
        for x in range(left_margin, image_width - right_margin, 8):
            draw.line(
                (x, y, min(x + 3, image_width - right_margin), y), fill=0, width=1
            )
        draw.text(
            (left_margin - 6, y), tick_labels[step], fill=0, font=font, anchor="rm"
        )
    count = len(readings)
    if count == 1:
        spacing = graph_width
    else:
        spacing = graph_width / (count - 1)
    points = []
    for index, reading in enumerate(readings):
        temperature = reading["temperature"]
        normalized = (temperature - graph_min) / (graph_max - graph_min)
        x = image_width // 2 if count == 1 else int(left_margin + index * spacing)
        y = int(x_axis - normalized * graph_height)
        points.append((x, y))
        hour = int(reading["time"][:2])
        if hour % 3 == 0 or index == count - 1:
            draw.text(
                (x, x_axis + 8), reading["time"][:2], fill=0, font=font, anchor="mt"
            )
    draw.text(
        (image_width // 2, image_height - 4), "HOUR", fill=0, font=font, anchor="mb"
    )
    if len(points) == 1:
        x, y = points[0]
        draw.line((x - 8, y, x + 8, y), fill=0, width=3)
    else:
        for index in range(len(points) - 1):
            x1, y1 = points[index]
            x2, y2 = points[index + 1]
            draw.line((x1, y1, x2, y1), fill=0, width=3)
            draw.line((x2, y1, x2, y2), fill=0, width=3)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    printer.set(align="center")
    printer.image(buffer)
    printer.set(align="left")
    printer_text(printer, "\n")
