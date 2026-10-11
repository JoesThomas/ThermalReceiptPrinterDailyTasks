"""Preview must work when Waitress imports web_control/app.py as `app`."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PreviewRouteTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec('flask'), 'Flask is a web_control dependency')
    def test_preview_renders_under_waitress_import_layout(self):
        secret = ROOT / 'web_control' / 'secret_key.txt'
        created = not secret.exists()
        if created:
            secret.write_text('preview-smoke-test-only-key', encoding='utf-8')
        try:
            script = '''
import sys
from pathlib import Path
sys.path.insert(0, str(Path('web_control').resolve()))
from app import app
with app.test_client() as client:
    with client.session_transaction() as session:
        session['authenticated'] = True
    for url in ('/preview', '/preview?page=finance', '/preview?page=actions'):
        response = client.get(url)
        assert response.status_code == 200, (url, response.status_code)
        assert b'Receipt preview' in response.data
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
