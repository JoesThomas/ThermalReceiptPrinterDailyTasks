"""Weather rendering; compatibility helpers are injected by the live facade."""

def print_weather_graphic(printer, code, *, _context):
    """Preserve drawing geometry when centring different-length ASCII rows."""
    centre = _context.get('centre')
    weather_graphic = _context.get('weather_graphic')
    rows = weather_graphic(code)
    margin = min((len(row) - len(row.lstrip(' ')) for row in rows))
    rows = [row[margin:].rstrip() for row in rows]
    width = max((len(row) for row in rows))
    for row in rows:
        centre(printer, row.ljust(width))
    centre(printer, '')

def print_compact_weather(printer, weather, location=None, *, _context):
    left = _context.get('left')
    print_line = _context.get('print_line')
    weather_description = _context.get('weather_description')
    current = weather['current']
    daily = weather['daily']
    condition = weather_description(current['weather_code'])
    high = float(daily['temperature_2m_max'][0])
    low = float(daily['temperature_2m_min'][0])
    print_line(printer, '=')
    printer.set(bold=True)
    left(printer, f"WEATHER / {location['name'].upper()}")
    printer.set(bold=False)
    left(printer, f"{current['temperature_2m']:.1f}C  {condition}")
    left(printer, f'HIGH {high:.1f}C / LOW {low:.1f}C')
    left(printer, 'DRY WITH LIGHT WINDS')

def print_weather(printer, weather, location=None, detail=None, *, _context):
    centre = _context.get('centre')
    datetime = _context.get('datetime')
    get_hourly_weather = _context.get('get_hourly_weather')
    is_definitively_boring_weather = _context.get('is_definitively_boring_weather')
    left = _context.get('left')
    print_compact_weather = _context.get('print_compact_weather')
    print_line = _context.get('print_line')
    print_temperature_graph = _context.get('print_temperature_graph')
    print_weather_graphic = _context.get('print_weather_graphic')
    print_wrapped = _context.get('print_wrapped')
    weather_description = _context.get('weather_description')
    if detail == 'compact' or (detail != 'full' and is_definitively_boring_weather(weather)):
        print_compact_weather(printer, weather, location)
        return
    current = weather['current']
    daily = weather['daily']
    text_readings = get_hourly_weather(weather, interval_hours=4)
    graph_readings = get_hourly_weather(weather, interval_hours=1)
    print_line(printer, '=')
    printer.set(bold=True)
    centre(printer, 'WEATHER')
    printer.set(bold=False)
    centre(printer, location['name'].upper())
    centre(printer, location['region'].upper())
    print_line(printer)
    print_weather_graphic(printer, current['weather_code'])
    current_temperature = current['temperature_2m']
    current_condition = weather_description(current['weather_code'])
    printer.set(bold=True)
    centre(printer, f'{current_temperature:.1f}C  {current_condition}')
    printer.set(bold=False)
    print_line(printer)
    printer.set(bold=True)
    left(printer, 'CURRENT CONDITIONS')
    printer.set(bold=False)
    left(printer, f"TEMP {current_temperature:.1f}C  FEELS {current['apparent_temperature']:.1f}C")
    left(printer, f"HUM {current['relative_humidity_2m']:.0f}%  WIND {current['wind_speed_10m']:.1f}km/h")
    left(printer, f"PRESS {current['surface_pressure']:.0f}hPa  DIR {current['wind_direction_10m']:.0f}deg")
    print_line(printer)
    printer.set(bold=True)
    left(printer, '4-HOURLY WEATHER')
    printer.set(bold=False)
    for reading in text_readings:
        condition = weather_description(reading['code'])
        line = f"{reading['time']} {reading['temperature']:4.1f}C {reading['humidity']:3.0f}% {reading['wind']:4.1f}k {condition}"
        print_wrapped(printer, line, width=40)
    print_line(printer)
    printer.set(bold=True)
    left(printer, 'TEMPERATURE GRAPH')
    printer.set(bold=False)
    print_temperature_graph(printer, graph_readings)
    print_line(printer)
    printer.set(bold=True)
    left(printer, 'TODAY')
    printer.set(bold=False)
    left(printer, f"MAX {daily['temperature_2m_max'][0]:.1f}C  MIN {daily['temperature_2m_min'][0]:.1f}C")
    left(printer, f"RAIN {daily['precipitation_probability_max'][0]:.0f}%")
    sunrise = datetime.fromisoformat(daily['sunrise'][0])
    sunset = datetime.fromisoformat(daily['sunset'][0])
    left(printer, f"SUNSET/SUNRISE {sunrise.strftime('%H:%M')}-{sunset.strftime('%H:%M')}")

def print_temperature_graph(printer, readings, *, _context):
    """
    Print a compact monochrome stepped-line temperature graph.

    The hourly readings are connected using horizontal
    steps with vertical transitions. This gives the receipt a
    vintage weather-station / chart-recorder appearance while
    remaining a bitmap, so no Unicode graph characters are sent
    to the ESC/POS printer.
    """
    BytesIO = _context.get('BytesIO')
    Image = _context.get('Image')
    ImageDraw = _context.get('ImageDraw')
    math = _context.get('math')
    printer_text = _context.get('printer_text')
    if not readings:
        return
    temperatures = [r['temperature'] for r in readings]
    span = max(temperatures) - min(temperatures)
    magnitude = 10 ** math.floor(math.log10(max(span / 4, 0.1)))
    tick = next((magnitude * value for value in (1, 2, 5, 10) if magnitude * value >= span / 4))
    graph_min = math.floor(min(temperatures) / tick) * tick
    graph_max = math.ceil(max(temperatures) / tick) * tick
    if graph_min == graph_max:
        graph_max += tick
    image_width = 440
    image_height = 160
    image = Image.new('1', (image_width, image_height), 1)
    draw = ImageDraw.Draw(image)
    left_margin = 38
    right_margin = 10
    top_margin = 8
    bottom_margin = 32
    graph_width = image_width - left_margin - right_margin
    graph_height = image_height - top_margin - bottom_margin
    x_axis = top_margin + graph_height
    draw.line((left_margin, top_margin, left_margin, x_axis), fill=0, width=1)
    draw.line((left_margin, x_axis, image_width - right_margin, x_axis), fill=0, width=1)
    tick_count = round((graph_max - graph_min) / tick)
    for step in range(tick_count + 1):
        value = graph_min + tick * step
        y = int(x_axis - graph_height * step / tick_count)
        for x in range(left_margin, image_width - right_margin, 8):
            draw.line((x, y, min(x + 3, image_width - right_margin), y), fill=0, width=1)
        draw.text((2, y - 5), f'{value:g}C', fill=0)
    count = len(readings)
    if count == 1:
        spacing = graph_width
    else:
        spacing = graph_width / (count - 1)
    points = []
    for index, reading in enumerate(readings):
        temperature = reading['temperature']
        normalized = (temperature - graph_min) / (graph_max - graph_min)
        x = int(left_margin + index * spacing)
        y = int(x_axis - normalized * graph_height)
        points.append((x, y))
        hour = int(reading['time'][:2])
        if hour % 3 == 0 or index == count - 1:
            draw.text((max(0, min(x - 7, image_width - 16)), x_axis + 5), reading['time'][:2], fill=0)
    draw.text((image_width // 2 - 11, image_height - 10), 'HOUR', fill=0)
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
    image.save(buffer, format='PNG')
    buffer.seek(0)
    printer.set(align='center')
    printer.image(buffer)
    printer.set(align='left')
    printer_text(printer, '\n')
