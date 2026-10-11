import ast
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from receipt.location_settings import DEFAULT_LOCATION, validate_location
from receipt_settings import DEFAULT_SETTINGS, load_receipt_settings

ROOT = Path(__file__).resolve().parents[1]


def renderer(name, **namespace):
    """Load a pure renderer without importing the live API clients."""
    source = ast.parse((ROOT / 'services/live_pipeline.py').read_text(encoding='utf-8'))
    function = next(node for node in source.body if isinstance(node, ast.FunctionDef)
                    and node.name == name)
    namespace['DEFAULT_LOCATION'] = DEFAULT_LOCATION
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(ROOT), 'exec'), namespace)
    return namespace[name]


class LocationSettingsTests(unittest.TestCase):
    def test_default_location_is_available_to_existing_settings(self):
        self.assertEqual(DEFAULT_SETTINGS['location'], DEFAULT_LOCATION)
        with TemporaryDirectory() as directory:
            settings_file = Path(directory) / 'receipt_settings.json'
            settings_file.write_text(json.dumps({'features': {'weather': False}}), encoding='utf-8')
            with patch('receipt_settings.SETTINGS_FILE', settings_file):
                self.assertEqual(load_receipt_settings()['location'], DEFAULT_LOCATION)
                self.assertFalse(load_receipt_settings()['features']['weather'])

    def test_coordinates_and_bbc_feed_are_validated(self):
        location = dict(DEFAULT_LOCATION, name='Liverpool', region='Merseyside, UK',
                        latitude='53.4072', longitude='-2.9916',
                        local_news_label='Merseyside',
                        local_news_feed='https://feeds.bbci.co.uk/news/england/merseyside/rss.xml')
        self.assertEqual(validate_location(location)['latitude'], 53.4072)
        for invalid in ('https://example.com/news/england/merseyside/rss.xml',
                        'https://feeds.bbci.co.uk.evil.test/news/england/merseyside/rss.xml'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_location(dict(location, local_news_feed=invalid))
        with self.assertRaises(ValueError):
            validate_location(dict(location, latitude='NaN'))

    def test_configured_weather_coordinates_and_header(self):
        requests = SimpleNamespace(get=lambda url, **kw: SimpleNamespace(
            raise_for_status=lambda: None, json=lambda: kw['params']))
        get_weather = renderer('get_weather', requests=requests)
        with patch('services.public_sources.weather', side_effect=lambda url, params: params):
            self.assertEqual(get_weather(53.4072, -2.9916)['latitude'], 53.4072)
            self.assertEqual(get_weather(53.4072, -2.9916)['longitude'], -2.9916)

        import datetime
        sent = []
        printer = SimpleNamespace(set=lambda **kw: None)
        header = renderer('print_header', datetime=datetime.datetime,
                          printer_text=lambda printer, value: sent.append(value))
        header(printer, dict(DEFAULT_LOCATION, name='Liverpool', region='Merseyside, UK'))
        self.assertIn('LIVERPOOL / MERSEYSIDE, UK\n', sent)


if __name__ == '__main__':
    unittest.main()
