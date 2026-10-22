from functools import wraps
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from flask import Flask, abort, redirect, request, session
from PIL import Image
from organiser import vault
from web_control.document_tools import register


def image_bytes():
    output = BytesIO()
    Image.new('RGB', (20, 20)).save(output, format='PNG')
    return output.getvalue()


class DocumentWebTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        for name, value in [('DIRECTORY', root/'data'/'vault'), ('KEY_FILE', root/'separate-key'/'vault.key')]:
            patcher = patch.object(vault, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.app = self.make_app()
        self.client = self.app.test_client()
        with self.client.session_transaction() as state:
            state.update(authenticated=True, csrf_token='test')

    def make_app(self, proxy=False):
        app = Flask(__name__)
        app.secret_key = 'test'
        app.config['MAX_CONTENT_LENGTH'] = 1024*1024
        @app.before_request
        def csrf():
            if request.method == 'POST' and request.form.get('csrf_token') != session.get('csrf_token'):
                abort(403)
        def login_required(fn):
            @wraps(fn)
            def wrapped(*args, **kwargs):
                return fn(*args, **kwargs) if session.get('authenticated') else redirect('/login')
            return wrapped
        with patch.dict('os.environ', {'RECEIPT_TRUST_PROXY':'1' if proxy else '0'}):
            register(app, login_required, lambda p: p == 'secret', lambda *args, **kwargs: False)
        return app

    def unlock(self):
        self.assertEqual(self.client.post('/documents/unlock', data={'csrf_token':'test','password':'secret'}).status_code, 302)
        self.assertEqual(self.client.post('/documents/initialise', data={'csrf_token':'test'}).status_code, 302)

    def test_upload_preview_download_and_delete_require_login_unlock_and_csrf(self):
        self.assertEqual(self.client.post('/documents/initialise', data={'csrf_token':'test'}).status_code, 403)
        self.assertEqual(self.client.post('/documents/unlock', data={'password':'secret'}).status_code, 403)
        self.unlock()
        response = self.client.post('/documents/upload', data={'csrf_token':'test','title':'Insurance', 'document':(BytesIO(image_bytes()),'insurance.png')})
        self.assertEqual(response.status_code, 302)
        identifier = vault.listing()[0]['id']
        preview = self.client.get(f'/documents/{identifier}/preview')
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.headers['Cache-Control'], 'no-store')
        self.assertIn('sandbox', preview.headers['Content-Security-Policy'])
        download = self.client.get(f'/documents/{identifier}/download')
        self.assertIn('attachment', download.headers['Content-Disposition'])
        stranger = self.app.test_client()
        self.assertEqual(stranger.get(f'/documents/{identifier}/preview').status_code, 302)
        self.client.post('/documents/lock', data={'csrf_token':'test'})
        self.assertEqual(self.client.get(f'/documents/{identifier}/download').headers['Location'], '/documents')
        self.assertEqual(self.client.post(f'/documents/{identifier}/delete', data={'csrf_token':'test'}).status_code, 403)
        self.client.post('/documents/unlock', data={'csrf_token':'test','password':'secret'})
        self.assertEqual(self.client.post(f'/documents/{identifier}/delete').status_code, 403)
        self.client.post(f'/documents/{identifier}/delete', data={'csrf_token':'test'})
        self.assertEqual(vault.listing(), [])

    def test_remote_http_is_blocked_and_forwarded_headers_are_not_implicitly_trusted(self):
        for headers in ({}, {'X-Forwarded-Proto':'https'}):
            response = self.client.get('/documents', environ_overrides={'REMOTE_ADDR':'192.168.0.20'}, headers=headers)
            self.assertEqual(response.status_code, 403)
        secure = self.client.post('/documents/unlock', base_url='https://localhost', data={'csrf_token':'test','password':'secret'}, environ_overrides={'REMOTE_ADDR':'192.168.0.20'})
        self.assertEqual(secure.status_code, 302)
        self.assertIn('Secure', secure.headers['Set-Cookie'])
        self.assertIn('Strict-Transport-Security', secure.headers)

    def test_proxy_trust_is_explicit_and_limited_to_loopback(self):
        client = self.make_app(proxy=True).test_client()
        self.assertEqual(client.get('/documents', headers={'X-Forwarded-Proto':'https'}, environ_overrides={'REMOTE_ADDR':'192.168.0.20'}).status_code, 403)
        self.assertEqual(client.get('/documents', headers={'X-Forwarded-Proto':'https'}, environ_overrides={'REMOTE_ADDR':'127.0.0.1'}).status_code, 302)
        self.assertEqual(client.get('/documents').status_code, 403)

    def test_unlock_expires_and_uploads_never_spool_plaintext_to_disk(self):
        self.unlock()
        with self.client.session_transaction() as state:
            state['document_unlocked_at'] = 1
        self.assertEqual(self.client.get('/documents/backup').headers['Location'], '/documents')
        with self.app.test_request_context('/documents/upload', method='POST', data={'document':(BytesIO(b'x'*700000),'x.pdf')}):
            self.assertIsInstance(request.files['document'].stream, BytesIO)
            request.environ['wsgi.input'].close()
