from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from jinja2 import Environment, FileSystemLoader
from finance.salary_plan import reserves


class CashCountDateTests(TestCase):
    def test_new_count_defaults_to_uk_today_without_changing_saved_date(self):
        with patch('receipt.local_time.uk_today', return_value=date(2026, 10, 10)), patch('finance.rental_tax.protected_reserve', return_value=0):
            reserve = reserves({'physical_cash_held': 200, 'physical_cash_date': '2026-09-01'})
        self.assertEqual(reserve['date'], date(2026, 9, 1))
        self.assertEqual(reserve['count_default_date'], '2026-10-10')
        env = Environment(loader=FileSystemLoader(Path(__file__).resolve().parents[1] / 'web_control/templates'))
        output = env.get_template('cash_reserve.html').render(
            cash_reserve=reserve, reserve_settings={}, csrf_token=lambda: '',
            url_for=lambda name: '/save', request=SimpleNamespace(endpoint='finance_review'))
        self.assertIn('counted 2026-09-01', output)
        self.assertRegex(output, 'name="physical_cash_date"\\s+value="2026-10-10"')
        self.assertIn('type="date"', output)
