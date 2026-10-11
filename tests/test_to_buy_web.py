"""Exercise the web checkbox and local list editor with Flask's test client."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ToBuyWebTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec('flask'), 'Flask is a web_control dependency')
    def test_checkbox_and_editor(self):
        secret = ROOT / 'web_control' / 'secret_key.txt'
        created = not secret.exists()
        if created:
            secret.write_text('to-buy-test-only-secret', encoding='utf-8')
        try:
            script = '''
import sys, tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path('web_control').resolve()))
from app import app
import receipt_settings
from web_control import to_buy
with tempfile.TemporaryDirectory() as directory, \\
     patch.object(receipt_settings, 'SETTINGS_FILE', Path(directory) / 'settings.json'), \\
     patch.object(to_buy, 'TO_BUY_FILE', Path(directory) / 'to_buy.json'):
    with app.test_client() as client:
        with client.session_transaction() as session:
            session['authenticated'] = True
            session['csrf_token'] = 'test-token'
        response = client.post('/to-buy/save', data={'csrf_token': 'test-token', 'items': 'Example A\\nExample B'})
        assert response.status_code == 302
        assert to_buy.load_to_buy() == ['Example A', 'Example B']
        assert client.post('/save', data={'csrf_token': 'test-token', 'to_buy': 'on'}).status_code == 302
        assert receipt_settings.load_receipt_settings()['one_shot']['to_buy']
        assert client.post('/save', data={'csrf_token': 'test-token'}).status_code == 302
        assert not receipt_settings.load_receipt_settings()['one_shot']['to_buy']
        assert client.post('/to-buy/save', data={'items': 'unauthorised'}).status_code == 403
'''
            result = subprocess.run([sys.executable, '-c', script], cwd=ROOT,
                                    env=os.environ.copy(), capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
        finally:
            if created:
                secret.unlink(missing_ok=True)


if __name__ == '__main__':
    unittest.main()
