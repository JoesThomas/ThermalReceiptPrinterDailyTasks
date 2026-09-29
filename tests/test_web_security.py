"""Exercise web security controls without contacting providers or printers."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WebSecurityTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec('flask'), 'Flask is a web_control dependency')
    def test_csrf_login_limit_and_body_limit(self):
        secret = ROOT / 'web_control' / 'secret_key.txt'
        created = not secret.exists()
        if created:
            secret.write_text('security-test-only-secret-key', encoding='utf-8')
        try:
            script = '''
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path('web_control').resolve()))
from app import app
with app.test_client() as client:
    assert client.post('/logout').status_code == 403
    client.get('/login')
    with client.session_transaction() as session:
        token = session['csrf_token']
    with patch('app.load_password_hash', return_value='unused'), patch('app.check_password_hash', return_value=False):
        for _ in range(5):
            assert client.post('/login', data={'csrf_token': token, 'password': 'wrong'}).status_code == 200
        assert client.post('/login', data={'csrf_token': token, 'password': 'wrong'}).status_code == 429
    with client.session_transaction() as session:
        session['authenticated'] = True
    assert client.post('/logout').status_code == 403
    assert client.post('/logout', data={'csrf_token': 'invalid'}).status_code == 403
    assert client.post('/logout', data={'csrf_token': token}).status_code == 302
    assert client.post('/login', data={'csrf_token': token, 'password': 'x' * (1024 * 1024)}).status_code == 413
'''
            result = subprocess.run([sys.executable, '-c', script], cwd=ROOT,
                                    env=os.environ.copy(), capture_output=True,
                                    text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
        finally:
            if created:
                secret.unlink(missing_ok=True)


if __name__ == '__main__':
    unittest.main()
