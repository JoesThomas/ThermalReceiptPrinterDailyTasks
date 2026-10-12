"""Weather condition labels and small ASCII illustrations."""

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
            r"     '------'",
        ]

    if code == 3:
        return [
            r"     .--------.",
            r"   .'          '.",
            r"  (    CLOUD     )",
            r"   '._        _.'",
            r"      '------'",
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
