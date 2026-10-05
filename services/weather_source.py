"""Weather collection and hourly readings, independent of receipt rendering."""
from datetime import datetime
from receipt.location_settings import DEFAULT_LOCATION

def get_weather(latitude=DEFAULT_LOCATION["latitude"], longitude=DEFAULT_LOCATION["longitude"]):
    url = "https://api.open-meteo.com/v1/forecast"

    params = {
        "latitude": latitude,
        "longitude": longitude,
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
            "wind_gusts_10m,"
            "precipitation_probability,"
            "precipitation,"
            "visibility,"
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

    from services.public_sources import weather
    return weather(url, params)


def get_hourly_weather(
    weather,
    interval_hours=4,
):
    hourly = weather["hourly"]
    readings = []

    for i, timestamp in enumerate(
        hourly["time"]
    ):
        dt = datetime.fromisoformat(
            timestamp
        )

        if dt.hour % interval_hours != 0:
            continue

        readings.append({
            "time": dt.strftime("%H:%M"),
            "temperature": (
                hourly[
                    "temperature_2m"
                ][i]
            ),
            "humidity": (
                hourly[
                    "relative_humidity_2m"
                ][i]
            ),
            "wind": (
                hourly[
                    "wind_speed_10m"
                ][i]
            ),
            "gust": (hourly.get("wind_gusts_10m") or [0] * len(hourly["time"]))[i],
            "precip_probability": (hourly.get("precipitation_probability") or [0] * len(hourly["time"]))[i],
            "precipitation": (hourly.get("precipitation") or [0] * len(hourly["time"]))[i],
            "visibility": (hourly.get("visibility") or [99999] * len(hourly["time"]))[i],
            "code": (
                hourly[
                    "weather_code"
                ][i]
            ),
        })

    return readings
