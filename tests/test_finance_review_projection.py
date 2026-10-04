"""Web projection renders and accepts local edits without calling bank APIs."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class FinanceProjectionWebTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec('flask'), 'Flask is a web dependency')
    def test_page_settings_payments_and_dismissal(self):
        secret = ROOT / 'web_control' / 'secret_key.txt'
        created = not secret.exists()
        if created:
            secret.write_text('finance-projection-test-only-key', encoding='utf-8')
        try:
            script = '''
import sys, json, tempfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path('web_control').resolve()))
from app import app
import finance.receipt as receipt
from web_control import finance_suggestions, finance_insights
transactions = [{'date': date.today().isoformat(), 'amount': -30, 'description': 'Everyday store'}]
status = {'monthly': [{'name': 'Example bill', 'amount': 80, 'due_day': 15}], 'yearly': [], 'ended': []}
pipeline = SimpleNamespace(
    get_regular_finance_data=lambda: (transactions, [], [], [], {'bank_data_status': 'complete'}),
    get_account_balances=lambda: {'HSBC': {'available': 500}, 'MONZO': {'available': 50}},
    build_subscription_status=lambda *args, **kwargs: status,
    matching_subscription_transaction=lambda *args: None,
    analyse_incoming_payments=lambda *args, **kwargs: ([], []))
with tempfile.TemporaryDirectory() as directory:
    settings = Path(directory) / 'settings.json'
    settings.write_text('{}')
    with patch.dict(sys.modules, {'services.live_pipeline': pipeline}), \\
         patch.object(receipt, 'FINANCE_SETTINGS_FILE', settings), \\
         patch.object(receipt, 'load_finance_settings', side_effect=lambda: json.loads(settings.read_text())), \\
         patch.object(finance_insights, 'FILE', Path(directory) / 'observations.json'), \\
         patch.object(finance_suggestions, 'DISMISSED_FILE', Path(directory) / 'dismissed.json'):
        with app.test_client() as client:
            with client.session_transaction() as session:
                session['authenticated'] = True
                session['csrf_token'] = 'test-csrf'
            response = client.get('/finance-review')
            assert response.status_code == 200, response.status_code
            assert b'Finance suggestions' in response.data
            assert b'Review uncertain payments' in response.data
            assert b'Cash runway' in response.data
            assert b'Understand the figures' in response.data
            assert b'Private monthly observations' in response.data
            assert (Path(directory)/'observations.json').exists()
            assert b'Example bill' in response.data
            assert client.post('/finance-review/forecast-settings', data={
                'csrf_token': 'test-csrf', 'next_payday': '2026-10-30', 'payday_repeat': 'monthly',
                'emergency_buffer': '100', 'runway_daily_spend': '8'}).status_code == 302
            assert json.loads(settings.read_text())['runway_daily_spend'] == 8
            assert client.post('/finance-review/salary-settings',data={'csrf_token':'test-csrf','hsbc_emergency_reserve':'500','physical_cash_target':'150','physical_cash_held':'50','physical_cash_date':date.today().isoformat(),'salary_savings_target':'100'}).status_code==302
            assert json.loads(settings.read_text())['hsbc_emergency_reserve']==500
            assert json.loads(settings.read_text())['physical_cash_held']==50
            assert client.post('/finance-review/salary-settings',data={'hsbc_emergency_reserve':'0'}).status_code==403
            before=settings.read_text()
            assert client.post('/finance-review/salary-settings',data={'csrf_token':'test-csrf','physical_cash_held':'NaN'}).status_code==302
            assert settings.read_text()==before
            response=client.get('/finance-review')
            assert response.status_code==200
            assert b'Salary plan' in response.data
            assert b'Physical cash recorded' in response.data
            transactions.clear()
            status['monthly']=[]
            response=client.get('/finance-review')
            assert response.status_code==200
            assert b'Review uncertain payments' not in response.data

            assert client.post('/finance-review/payment/add', data={
                'csrf_token': 'test-csrf', 'name': 'Example card', 'amount': '50',
                'due_date': '2026-10-10', 'repeat': 'once'}).status_code == 302
            assert len(json.loads(settings.read_text())['commitments']) == 1
            assert client.post('/finance-review/payment/0/delete', data={'csrf_token': 'test-csrf'}).status_code == 302
            assert json.loads(settings.read_text())['commitments'] == []
            assert client.post('/finance-review/dismiss', data={
                'csrf_token': 'test-csrf', 'suggestion_id': 'a' * 24}).status_code == 302
            assert client.post('/finance-review/payment/add', data={'name': 'Blocked'}).status_code == 403
'''
            result = subprocess.run([sys.executable, '-c', script], cwd=ROOT,
                                    env=os.environ.copy(), capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
        finally:
            if created:
                secret.unlink(missing_ok=True)


if __name__ == '__main__':
    unittest.main()
