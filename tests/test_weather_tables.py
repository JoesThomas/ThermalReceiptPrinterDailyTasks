"""Receipt layout and emphasis checks for compact weather tables."""
from datetime import datetime
import unittest
from receipt.profile import COLUMNS
from receipt.weather_renderers import print_weather, WeatherDependencies
from receipt import news_renderers
from services.local_gigs import print_receipt


class Printer:
    def __init__(self):
        self.bold = False
        self.rows = []
    def set(self, **kwargs):
        self.bold = kwargs.get('bold', self.bold)
    def text(self, text):
        self.rows.extend((line, self.bold) for line in text.splitlines())


class WeatherTablesTests(unittest.TestCase):
    def test_columns_wrap_and_only_current_hour_is_bold(self):
        for current_time in ('2026-10-20T09:30', None, 'invalid'):
            with self.subTest(current_time=current_time):
                printer = Printer()
                weather = {'current': {'time': current_time, 'temperature_2m': -10.9,
                    'weather_code': 61, 'apparent_temperature': -11.3,
                    'relative_humidity_2m': 100, 'wind_speed_10m': 105.3},
                    'daily': {'temperature_2m_max': [10.9], 'temperature_2m_min': [-9.1],
                        'precipitation_probability_max': [100],
                        'sunrise': ['2026-10-20T07:41'], 'sunset': ['2026-10-20T18:02']}}
                readings = [{'time': f'{hour:02d}:00', 'temperature': -10.9,
                    'humidity': 100, 'wind': 105.3, 'code': 61} for hour in (8, 9, 10)]
                deps = WeatherDependencies(now=lambda: datetime(2026, 10, 20, 9),
                    get_hourly_weather=lambda *a, **kw: readings,
                    print_weather_graphic=lambda *a: None,
                    print_temperature_graph=lambda *a: None,
                    weather_description=lambda *a: 'VERY HEAVY FREEZING RAIN')
                print_weather(printer, weather, {'name': 'Stirchley', 'region': 'Birmingham, UK'}, deps=deps)
                text = [row for row, bold in printer.rows]
                self.assertTrue(all(len(row) <= COLUMNS for row in text))
                self.assertIn('Weather - Stirchley, Birmingham'.center(COLUMNS), text)
                self.assertFalse(any('marks the' in row or row.startswith('>') for row in text))
                today = text.index('TODAY'.center(COLUMNS))
                self.assertEqual(text[today+3], '-' * COLUMNS)
                for label, value in [('Maximum','10.9C'),('Minimum','-9.1C'),('Rain','100%'),('Sunrise','07:41'),('Sunset','18:02')]:
                    self.assertEqual(text[today+1].index(label), text[today+2].index(value))
                current = text.index('CURRENT CONDITIONS'.center(COLUMNS))
                self.assertEqual(text[current+3], '-' * COLUMNS)
                for label, value in [('Temperature','-10.9C'),('Feels like','-11.3C'),('Humidity','100%'),('Wind','105.3km/h')]:
                    self.assertEqual(text[current+1].index(label), text[current+2].index(value))
                hourly = text.index('HOURLY WEATHER'.center(COLUMNS))
                header = text[hourly+1]
                for row, bold in printer.rows[hourly+2:-1]:
                    if row.lstrip().startswith(('08:00', '09:00', '10:00')):
                        self.assertEqual(bold, row.lstrip().startswith('09:00'))
                        for label, value in [('Temp','-10.9C'),('Humidity','100%'),('Wind','105.3km/h'),('Weather','VERY')]:
                            self.assertEqual(header.index(label), row.index(value))
                continuation = next(i for i, (row, bold) in enumerate(printer.rows) if row.lstrip().startswith('09:00'))+1
                self.assertTrue(printer.rows[continuation][1])
                self.assertFalse(printer.bold)

    def test_optional_current_measurements_align_and_omit_invalid_values(self):
        from unittest.mock import patch
        from receipt import weather_renderers as weather
        for columns in (20,30,48):
            with self.subTest(columns=columns), patch.object(weather,'COLUMNS',columns):
                rows=list(weather._extra_current_rows({'surface_pressure':1013.2,'wind_direction_10m':220}))
                self.assertTrue(all(len(row)<=columns for row in rows))
                self.assertIn('1013 hPa',' '.join(rows))
                self.assertIn('SW (220 deg)',' '.join(rows))
                if columns==48:
                    self.assertEqual(len(rows),2)
                    self.assertEqual(rows[0].index('Air pressure'),rows[1].index('1013'))
                    self.assertEqual(rows[0].index('Wind direction'),rows[1].index('SW'))
        for direction in (0,360,359.9):
            self.assertIn('N (0 deg)',' '.join(weather._extra_current_rows({'wind_direction_10m':direction})))
        for value in (None,float('nan'),float('inf'),True,-1,'invalid'):
            self.assertEqual(list(weather._extra_current_rows({'surface_pressure':value,'wind_direction_10m':value})),[])
        self.assertEqual(list(weather._extra_current_rows({})),[])

    def test_gigs_heading_matches_standard_section_and_empty_gigs_print_nothing(self):
        printer = Printer()
        result = {'events': [], 'status': 'not_configured', 'location': 'Birmingham', 'radius': 25, 'truncated': False}
        print_receipt(printer, result)
        self.assertEqual(printer.rows[:3], [('-'*COLUMNS,False), ('GIGS TODAY'.center(COLUMNS),True), ('-'*COLUMNS,False)])
        printer.rows.clear()
        print_receipt(printer, {**result, 'status': 'ok'})
        self.assertEqual(printer.rows, [])

    def test_sports_prints_headlines_without_description(self):
        printer = Printer()
        from receipt import output
        context = {'left': output.left, 'print_line': output.line, 'print_wrapped': output.wrapped,
                   '_news_summary_is_useful': lambda *a: True}
        context['_print_news_stories'] = lambda *a, **kw: news_renderers._print_news_stories(*a, **kw, _context=context)
        news_renderers.print_sport_news(printer, [{'headline': 'A sporting headline', 'summary': 'Extra match information'}], _context=context)
        self.assertIn(('1. A sporting headline', False), printer.rows)
        self.assertFalse(any('Extra match' in row for row, bold in printer.rows))
