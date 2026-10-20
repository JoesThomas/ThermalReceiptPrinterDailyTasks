from receipt.profile import COLUMNS
import ast
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import unittest
import math
from PIL import Image, ImageDraw


SOURCE = ast.parse((Path(__file__).resolve().parents[1] / "services" / "live_pipeline.py").read_text())


def renderer(name, namespace):
    function = next(node for node in SOURCE.body
                    if isinstance(node, ast.FunctionDef) and node.name == name)
    exec(compile(ast.Module(body=[function], type_ignores=[]), "live_pipeline.py", "exec"), namespace)
    return namespace[name]


class NewsWeatherReceiptTests(unittest.TestCase):
    def test_rules_reset_physical_justification_after_centred_titles(self):
        from escpos.printer import Dummy
        from receipt import output
        from receipt.capture import RecordingPrinter
        for render_line in (output.line, renderer("print_line", {})):
            for deferred in (False, True):
                with self.subTest(renderer=render_line, deferred=deferred):
                    device = Dummy()
                    printer = RecordingPrinter(device, defer=deferred)
                    output.centre(printer, "WEATHER")
                    render_line(printer, "=")
                    output.left(printer, "TODAY")
                    output.centre(printer, "LIGHT RAIN")
                    render_line(printer)
                    if deferred:
                        printer.send()
                    raw = device.output
                    # Test actual ESC/POS alignment bytes, not just the 42-column
                    # web capture which hides the physical printer's extra space.
                    reset_rule = b"\x1ba\x00" + b"-" * COLUMNS + b"\n"
                    self.assertEqual(raw.count(reset_rule), 2)
                    self.assertEqual(printer.align, "left")
                    self.assertEqual([row for row in ''.join(printer.lines).splitlines()
                                      if row.startswith('-')], ['-' * COLUMNS] * 2)
                    self.assertIn(b"\x1ba\x01", raw)

    def test_weather_rules_share_body_margin_on_wider_printer(self):
        from datetime import datetime
        from receipt.weather_renderers import print_weather, WeatherDependencies
        class WidePrinter:
            def __init__(self):
                self.align = 'left'
                self.rows = []
            def set(self, **kwargs):
                self.align = kwargs.get('align', self.align)
            def text(self, value):
                for row in value.splitlines():
                    offset = (48 - len(row)) // 2 if self.align == 'center' else 0
                    self.rows.append((row, offset))
        printer = WidePrinter()
        weather = {
            'current': {'temperature_2m': 10.7, 'weather_code': 61,
                        'apparent_temperature': 9.8, 'relative_humidity_2m': 98,
                        'wind_speed_10m': 7.6, 'surface_pressure': 997,
                        'wind_direction_10m': 69},
            'daily': {'temperature_2m_max': [11.1], 'temperature_2m_min': [9.3],
                      'precipitation_probability_max': [100],
                      'sunrise': ['2026-10-20T07:41'], 'sunset': ['2026-10-20T18:02']},
        }
        deps = WeatherDependencies(get_hourly_weather=lambda *a, **kw: [],
                                   print_temperature_graph=lambda *a: None,
                                   now=lambda: datetime(2026, 10, 20, 9))
        print_weather(printer, weather, {'name': 'Stirchley', 'region': 'Birmingham, UK'}, deps=deps)
        rules = [offset for row, offset in printer.rows if row == '-' * COLUMNS]
        self.assertGreater(len(rules), 4)
        self.assertEqual(set(rules), {0})
        self.assertTrue(all(offset == 0 for row, offset in printer.rows
                            if row.startswith(('MAX ', 'TEMP '))))
        self.assertTrue(any(row == 'WEATHER' and offset > 0 for row, offset in printer.rows))

    def test_temperature_graph_fits_receipt_and_centres_image(self):
        sizes = []
        alignment = []
        labels = []
        real_draw = ImageDraw.Draw

        class LabelledDraw:
            def __init__(self, image):
                self.draw = real_draw(image)

            def text(self, position, value, **kwargs):
                labels.append(value)
                self.draw.text(position, value, **kwargs)

            def line(self, *args, **kwargs):
                self.draw.line(*args, **kwargs)

        def capture(buffer):
            sizes.append(Image.open(BytesIO(buffer.getvalue())).size)

        printer = SimpleNamespace(image=capture,
                                  set=lambda **kwargs: alignment.append(kwargs["align"]))
        graph = renderer("print_temperature_graph", {
            "Image": Image, "ImageDraw": SimpleNamespace(Draw=LabelledDraw),
            "BytesIO": BytesIO, "math": math,
            "printer_text": lambda *args: None,
        })
        graph(printer, [{"time": f"{hour:02d}:00", "temperature": float(hour)}
                        for hour in range(24)])
        self.assertEqual(sizes, [(576, 202)])
        self.assertEqual(alignment, ["center", "left"])
        self.assertTrue({"HOUR", "00", "03", "06", "09", "12", "15",
                         "18", "21", "23"}.issubset(labels))
        self.assertTrue(any(value.endswith("C") for value in labels))

    def test_graph_uses_printable_width_and_centres_plot_with_balanced_gutters(self):
        from receipt.weather_renderers import print_temperature_graph
        lines=[]; images=[]; labels=[]
        class Draw:
            def __init__(self,image):self.draw=ImageDraw.Draw(image)
            def line(self,points,**kwargs):lines.append(points);self.draw.line(points,**kwargs)
            def text(self,position,text,**kwargs):labels.append((position,text,kwargs));self.draw.text(position,text,**kwargs)
        for width in (384,576):
            with self.subTest(width=width):
                lines.clear();images.clear();labels.clear()
                printer=SimpleNamespace(profile=SimpleNamespace(profile_data={'media':{'width':{'pixels':width}}}),
                    image=lambda buffer:images.append(Image.open(BytesIO(buffer.getvalue()))),set=lambda **kwargs:None)
                context={'Image':Image,'ImageDraw':SimpleNamespace(Draw=Draw),'BytesIO':BytesIO,
                         'math':math,'printer_text':lambda *args:None}
                print_temperature_graph(printer,[{'time':f'{hour:02d}:00','temperature':-5+hour/2} for hour in range(24)],_context=context)
                self.assertEqual(images[0].width,width)
                left,top,right,bottom=lines[1]
                self.assertEqual(left,width-right)
                self.assertGreater(right-left,width*.75)
                self.assertTrue(all(kwargs['font'] is not None for pos,label,kwargs in labels))
                self.assertEqual(next(pos[0] for pos,label,kwargs in labels if label=='HOUR'),width//2)
                # Labels retain ink inside the image; neither axis endpoint touches paper edges.
                self.assertGreater(left,0);self.assertLess(right,width)

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
                     "weather_description": lambda _: "RAIN", "print_weather_graphic": lambda *args: None,
                     "print_line": lambda *args: None, "centre": lambda *args: None,
                     "left": lambda *args: None, "print_wrapped": lambda *args, **kwargs: None,
                     "print_temperature_graph": lambda printer, readings: graph.extend(readings)}
        namespace["get_hourly_weather"] = renderer("get_hourly_weather", namespace)
        print_weather = renderer("print_weather", namespace)
        print_weather(SimpleNamespace(set=lambda **kwargs: None), weather,
                      {"name": "Birmingham", "region": "UK"})
        self.assertEqual([reading["time"] for reading in graph],
                         [f"{hour:02d}:00" for hour in range(24)])

    def test_weather_essentials_survive_all_legacy_modes_and_quiet_days(self):
        import datetime
        from services.weather_source import get_hourly_weather
        from receipt.weather_renderers import print_weather
        weather = {'current': {'weather_code':0,'temperature_2m':15.0,'apparent_temperature':15.0,
            'relative_humidity_2m':60,'wind_speed_10m':3.0,'surface_pressure':1013,'wind_direction_10m':90},
            'daily': {'temperature_2m_max':[17.0],'temperature_2m_min':[12.0],
                'precipitation_probability_max':[0],'sunrise':['2026-10-11T07:00'],'sunset':['2026-10-11T18:00']},
            'hourly': {'time':[f'2026-10-11T{h:02d}:00' for h in range(24)],
                'temperature_2m':[15.0]*24,'relative_humidity_2m':[60]*24,
                'wind_speed_10m':[3.0]*24,'weather_code':[0]*24}}
        location={'name':'Edinburgh','region':'Scotland'}
        for detail in (None,'auto','compact','full'):
            with self.subTest(detail=detail):
                text=[]; drawings=[]; graphs=[]
                context={'centre':lambda printer,line:text.append(line),
                    'left':lambda printer,line:text.append(line), 'datetime':datetime.datetime,
                    'get_hourly_weather':get_hourly_weather,
                    'is_definitively_boring_weather':lambda weather:True,
                    'print_compact_weather':lambda *args:self.fail('Weather essentials were suppressed'),
                    'print_line':lambda *args:None,
                    'print_wrapped':lambda printer,line,**kwargs:text.append(line),
                    'weather_description':lambda code:'CLEAR',
                    'print_weather_graphic':lambda printer,code:drawings.append(code),
                    'print_temperature_graph':lambda printer,rows:graphs.append(rows)}
                print_weather(SimpleNamespace(set=lambda **kwargs:None), weather, location, detail, _context=context)
                self.assertIn('EDINBURGH',text); self.assertIn('SCOTLAND',text)
                self.assertEqual([s.strip() for s in text[text.index('SCOTLAND')+1:text.index('SCOTLAND')+5]],
                    ['TODAY','MAX 17.0C  MIN 12.0C','RAIN 0%','SUNRISE/SUNSET 07:00-18:00'])
                self.assertEqual([s.strip() for s in text].count('TODAY'),1)
                self.assertIn('HOURLY WEATHER'.center(COLUMNS),text); self.assertEqual(drawings,[0])
                self.assertLess(text.index('TEMPERATURE GRAPH'.center(COLUMNS)), text.index('HOURLY WEATHER'.center(COLUMNS)))
                self.assertEqual(len(graphs[0]),24)
                for hour in range(24):
                    self.assertTrue(any(line.lstrip('>').startswith(f'{hour:02d}:00 ') for line in text))


class WeatherIllustrationTests(unittest.TestCase):
    def test_complete_outlines_and_same_width_rows_for_every_condition(self):
        rows = []
        namespace = {'centre': lambda printer, text: rows.append(text)}
        graphic = renderer('weather_graphic', namespace)
        draw = renderer('print_weather_graphic', namespace)
        for code in (0, 1, 2, 3, 45, 48, 51, 61, 71, 85, 95, 99, -1):
            with self.subTest(code=code):
                rows.clear()
                draw(None, code)
                self.assertEqual(len(rows), len(graphic(code)) + 1)
                self.assertEqual(rows[-1], '')
                self.assertEqual(len({len(row) for row in rows[:-1]}), 1)
                self.assertTrue(all(len(row) <= COLUMNS for row in rows))
                self.assertEqual(rows[-2].strip(), graphic(code)[-1].strip())
                if code in (1, 2, 3):
                    self.assertEqual(rows[-2].strip(), "'------'")

    def test_capture_keeps_closing_row_and_gap_before_caption(self):
        from receipt.capture import RecordingPrinter
        class Printer:
            def set(self, **kwargs): pass
            def text(self, text): pass
        recorder = RecordingPrinter(Printer())
        namespace = {'centre': lambda printer, text: (printer.set(align='center'), printer.text(text+'\n'))}
        renderer('weather_graphic', namespace)
        draw = renderer('print_weather_graphic', namespace)
        draw(recorder, 3)
        namespace['centre'](recorder, '12.0C CLOUDY')
        lines = ''.join(recorder.lines).splitlines()
        self.assertEqual(lines[-3].strip(), "'------'")
        self.assertEqual(lines[-2].strip(), '')
        self.assertEqual(lines[-1].strip(), '12.0C CLOUDY')


if __name__ == "__main__":
    unittest.main()
