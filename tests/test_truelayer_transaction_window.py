import ast
from datetime import date, datetime, timedelta
from pathlib import Path
import unittest
from unittest.mock import Mock
from zoneinfo import ZoneInfo


class HTTPError(Exception):
    def __init__(self, response):
        self.response = response


class TransactionWindowTests(unittest.TestCase):
    def setUp(self):
        source = ast.parse((Path(__file__).resolve().parents[1] / 'services/live_pipeline.py')
                           .read_text(encoding='utf-8'))
        node = next(n for n in source.body if isinstance(n, ast.FunctionDef)
                    and n.name == '_truelayer_transactions')
        self.requests = Mock(HTTPError=HTTPError)
        namespace = {'requests': self.requests, 'datetime': datetime,
                     'ZoneInfo': ZoneInfo, 'timedelta': timedelta,
                     'TRUELAYER_DATA_URL': 'https://example.invalid/data/v1'}
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<transaction-window>', 'exec'), namespace)
        self.fetch = namespace['_truelayer_transactions']

    def test_clamps_future_end_and_inclusive_ninety_day_window(self):
        today_utc = datetime.now(ZoneInfo('UTC')).date()
        response = Mock()
        response.json.return_value = {'results': [{'amount': 800}]}
        self.requests.get.return_value = response
        got = self.fetch('token', 'accounts', 'account',
                         today_utc - timedelta(days=90), today_utc + timedelta(days=1))
        self.assertEqual(got, [{'amount': 800}])
        params = self.requests.get.call_args.kwargs['params']
        self.assertEqual(params['to'], today_utc.isoformat())
        self.assertEqual(params['from'], (today_utc - timedelta(days=89)).isoformat())

    def test_invalid_date_range_falls_back_to_thirty_days(self):
        today_utc = datetime.now(ZoneInfo('UTC')).date()
        bad = Mock(status_code=400)
        bad.json.return_value = {'error': 'invalid_date_range'}
        failing = Mock()
        failing.raise_for_status.side_effect = HTTPError(bad)
        good = Mock()
        good.json.return_value = {'results': [{'amount': 800}]}
        self.requests.get.side_effect = [failing, good]
        info = {}
        got = self.fetch('token', 'accounts', 'account',
                         today_utc - timedelta(days=90), today_utc + timedelta(days=1),
                         range_info=info)
        self.assertEqual(got, [{'amount': 800}])
        self.assertTrue(info['shortened'])
        self.assertEqual(self.requests.get.call_args.kwargs['params']['from'],
                         (today_utc - timedelta(days=29)).isoformat())

    def test_other_errors_are_not_retried(self):
        bad = Mock(status_code=400)
        bad.json.return_value = {'error': 'validation_error'}
        failing = Mock()
        failing.raise_for_status.side_effect = HTTPError(bad)
        self.requests.get.return_value = failing
        with self.assertRaises(HTTPError):
            self.fetch('token', 'accounts', 'account', date(2026, 9, 1), date(2026, 9, 2))
        self.assertEqual(self.requests.get.call_count, 1)


if __name__ == '__main__':
    unittest.main()
