"""Isolated browser fixture server. Never run against a user's private data."""
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
folder = tempfile.TemporaryDirectory()
copy = Path(folder.name) / 'project'
shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns('.git', 'data', 'logs', '__pycache__', '*.json', 'secret_key.txt'))
shutil.copy2(ROOT / 'finance' / 'tax_rules.json', copy / 'finance' / 'tax_rules.json')
(copy / 'web_control' / 'secret_key.txt').write_text('browser-test-only-secret')
sys.path[:0] = [str(copy / 'web_control'), str(copy)]
print("Fixture files ready", file=sys.stderr, flush=True)
import app as web
print("Web app imported", file=sys.stderr, flush=True)
from flask import redirect, session
from actions import delivery_state
from services import bin_collections
from storage import write_json
from receipt.capture import RecordingPrinter
from receipt.live_preview import VirtualPrinter
from web_control import preview_job

# No external integration or hardware calls are allowed in this fixture process.
import requests
patch.object(requests.sessions.Session, 'request', side_effect=RuntimeError('External requests disabled in browser fixtures')).start()
write_json(copy / 'data' / 'subscriptions.json', {'monthly': [], 'yearly': [], 'instalments': []})
row = {'carrier': 'AMAZON', 'event_title': 'Example book', 'order_ref': '123-1234567-1234567', 'delivery_date': str(bin_collections.today())}
delivery_state.record_deliveries([row], lambda value: 'AMAZON', lambda value: 'Expected today')

@web.app.get('/__fixture_login')
def fixture_login():
    session['authenticated'] = True
    return redirect('/bins')


def fixture_preview():
    # Replace external collection, retaining the production capture/save/render path.
    printer = RecordingPrinter(VirtualPrinter(), defer=True)
    printer.text('INFORMATION\nFixture receipt generated\n')
    from receipt.capture import LIVE_PREVIEW_FILE
    printer.save('information', path=LIVE_PREVIEW_FILE, replace=True)
    preview_job.save_status('running')
    preview_job.save_status('completed')
    return redirect('/preview?source=live')

web._generate_live_preview_locked = fixture_preview
if '--stdio' in sys.argv:
    import json
    import base64
    import contextlib
    with web.app.test_client() as client:
        for line in sys.stdin:
            request = json.loads(line)
            with contextlib.redirect_stdout(sys.stderr):
                response = client.open(request['path'], method=request['method'],
                                       data=request.get('body', ''), headers=request.get('headers', {}),
                                       base_url='http://receipt.test')
            print(json.dumps({'status': response.status_code, 'headers': dict(response.headers),
                              'body': base64.b64encode(response.data).decode()}), flush=True)
else:
    raise SystemExit('Use --stdio; the fixture never listens on a network port.')
