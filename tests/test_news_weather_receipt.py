import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


SOURCE = ast.parse((Path(__file__).resolve().parents[1] / "services" / "live_pipeline.py").read_text())


def renderer(name, namespace):
    function = next(node for node in SOURCE.body
                    if isinstance(node, ast.FunctionDef) and node.name == name)
    exec(compile(ast.Module(body=[function], type_ignores=[]), "live_pipeline.py", "exec"), namespace)
    return namespace[name]


class NewsWeatherReceiptTests(unittest.TestCase):
    def test_local_news_omits_description(self):
        lines = []
        namespace = {"DEFAULT_LOCATION": {"local_news_label": "Birmingham"},
                     "print_line": lambda *args: None,
                     "left": lambda printer, line: lines.append(line),
                     "print_wrapped": lambda printer, line, width: lines.append(line),
                     "_news_summary_is_useful": lambda *args: True}
        namespace["_print_news_stories"] = renderer("_print_news_stories", namespace)
        print_local_news = renderer("print_local_news", namespace)
        print_local_news(SimpleNamespace(set=lambda **kwargs: None, text=lambda line: None),
                         [{"headline": "Council opens new library", "summary": "Long description"}])
        self.assertIn("1. Council opens new library", lines)
        self.assertNotIn("Long description", lines)

    def test_weather_graph_receives_all_hourly_points(self):
        graph = []
        weather = {"current": {"weather_code": 61, "temperature_2m": 10.0,
                               "apparent_temperature": 9.0, "relative_humidity_2m": 80,
                               "wind_speed_10m": 4.0, "surface_pressure": 1013,
                               "wind_direction_10m": 90},
                   "daily": {"temperature_2m_max": [12.0], "temperature_2m_min": [8.0],
                             "precipitation_probability_max": [70],
                             "sunrise": ["2026-09-28T07:00"], "sunset": ["2026-09-28T19:00"]},
                   "hourly": {"time": [f"2026-09-28T{hour:02d}:00" for hour in range(24)],
                              "temperature_2m": list(range(24)),
                              "relative_humidity_2m": [80] * 24,
                              "wind_speed_10m": [4] * 24,
                              "weather_code": [61] * 24}}
        import datetime
        namespace = {"DEFAULT_LOCATION": {"name": "Birmingham", "region": "UK"},
                     "datetime": datetime.datetime, "is_definitively_boring_weather": lambda _: False,
                     "weather_description": lambda _: "RAIN", "weather_graphic": lambda _: [],
                     "print_line": lambda *args: None, "centre": lambda *args: None,
                     "left": lambda *args: None, "print_wrapped": lambda *args, **kwargs: None,
                     "print_temperature_graph": lambda printer, readings: graph.extend(readings)}
        namespace["get_hourly_weather"] = renderer("get_hourly_weather", namespace)
        print_weather = renderer("print_weather", namespace)
        print_weather(SimpleNamespace(set=lambda **kwargs: None), weather,
                      {"name": "Birmingham", "region": "UK"})
        self.assertEqual([reading["time"] for reading in graph],
                         [f"{hour:02d}:00" for hour in range(24)])


if __name__ == "__main__":
    unittest.main()
