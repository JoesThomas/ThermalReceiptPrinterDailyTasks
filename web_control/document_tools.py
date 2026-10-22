"""TLS, short document unlock sessions, and authenticated encrypted storage routes."""
from functools import wraps
from io import BytesIO
import ipaddress
import os
from time import time
from flask import Request, abort, flash, redirect, render_template, request, send_file, session, url_for
from flask.sessions import SecureCookieSessionInterface
from organiser import vault

UNLOCK_SECONDS = 15 * 60


class PrivateRequest(Request):
    def _get_file_stream(self, total_content_length, content_type, filename=None, content_length=None):
        if self.endpoint == 'document_upload':
            return BytesIO()  # Bounded upload; never spool unencrypted documents to disk.
        return super()._get_file_stream(total_content_length, content_type, filename, content_length)


class TransportSession(SecureCookieSessionInterface):
    def get_cookie_secure(self, app):
        return request.is_secure or super().get_cookie_secure(app)


def register(app, login_required, verify_password, limited):
    app.request_class = PrivateRequest
    app.session_interface = TransportSession()
    proxy = os.environ.get('RECEIPT_TRUST_PROXY') == '1'
    if proxy:
        from werkzeug.middleware.proxy_fix import ProxyFix
        original = app.wsgi_app
        forwarded = ProxyFix(original, x_proto=1, x_for=0)
        def trusted_proxy(environ, start_response):
            try:
                local_proxy = ipaddress.ip_address(environ.get('REMOTE_ADDR', '0.0.0.0')).is_loopback
            except ValueError:
                local_proxy = False
            return (forwarded if local_proxy else original)(environ, start_response)
        app.wsgi_app = trusted_proxy

    def secure_before():
        try:
            local = ipaddress.ip_address(request.remote_addr or '0.0.0.0').is_loopback
        except ValueError:
            local = False
        if (proxy or not local) and not request.is_secure:
            abort(403, description='HTTPS is required when connecting from another device. Configure TLS or a trusted HTTPS reverse proxy.')
        if request.endpoint == 'document_upload':
            request.max_content_length = vault.MAX_FILE + 128 * 1024
            request.max_form_memory_size = 64 * 1024
            request.max_form_parts = 10
    @app.after_request
    def document_transport_headers(response):
        if request.is_secure:
            response.headers.setdefault('Strict-Transport-Security', 'max-age=31536000')
        if request.endpoint and request.endpoint.startswith('document_'):
            response.headers['Cache-Control'] = 'no-store'
            response.headers['X-Content-Type-Options'] = 'nosniff'
            response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    # Apply transport and upload limits before the existing CSRF parser reads forms.
    app.before_request_funcs.setdefault(None, []).insert(0, secure_before)

    def unlocked():
        elapsed = time() - session.get('document_unlocked_at', 0)
        return 0 <= elapsed < UNLOCK_SECONDS

    def document_access(fn):
        @wraps(fn)
        @login_required
        def wrapped(*args, **kwargs):
            if not unlocked():
                if request.method != 'GET':
                    abort(403, description='Unlock document storage before changing it.')
                return redirect(url_for('document_list'))
            return fn(*args, **kwargs)
        return wrapped

    @app.get('/documents')
    @login_required
    def document_list():
        rows, error = [], None
        if unlocked():
            try:
                rows = vault.listing()
            except (ValueError, OSError):
                error = 'Document storage is unavailable. Check its key, permissions and encrypted backup.'
        return render_template('documents.html', documents=rows, vault_unlocked=unlocked(), vault_error=error,
                               vault_ready=(vault.DIRECTORY / 'index.enc').exists())

    @app.post('/documents/unlock')
    @login_required
    def document_unlock():
        address = request.remote_addr or 'unknown'
        if limited(address):
            abort(429)
        if not verify_password(request.form.get('password', '')):
            limited(address, failed=True)
            flash('Document unlock failed.')
        else:
            session['document_unlocked_at'] = time()
        return redirect(url_for('document_list'))

    @app.post('/documents/lock')
    @login_required
    def document_lock():
        session.pop('document_unlocked_at', None)
        return redirect(url_for('document_list'))

    @app.post('/documents/initialise')
    @document_access
    def document_initialise():
        try:
            vault.initialise()
            flash('Encrypted document storage initialised. Back up its separate key securely; losing it prevents recovery.')
        except (ValueError, OSError):
            flash('Storage could not be initialised. Check the external key location and existing encrypted files.')
        return redirect(url_for('document_list'))

    @app.post('/documents/upload')
    @document_access
    def document_upload():
        try:
            incoming = request.files.get('document')
            if not incoming:
                raise ValueError('Choose a PDF, JPEG or PNG document.')
            vault.upload(incoming.stream, incoming.filename, request.form.get('title', ''), request.form.get('expires') or None)
            flash('Document encrypted and saved.')
        except (ValueError, OSError) as error:
            flash(str(error) if isinstance(error, ValueError) else 'Document could not be stored.')
        return redirect(url_for('document_list'))

    @app.get('/documents/<identifier>/download')
    @document_access
    def document_download(identifier):
        try:
            row, raw = vault.read(identifier)
        except (ValueError, OSError):
            abort(404)
        response = send_file(BytesIO(raw), mimetype=vault.MIME[row['suffix']], as_attachment=True,
                             download_name=f"document-{identifier}.{row['suffix']}", max_age=0)
        response.headers['Content-Security-Policy'] = "sandbox; default-src 'none'"
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/documents/<identifier>/preview')
    @document_access
    def document_preview(identifier):
        try:
            row, raw = vault.read(identifier)
            if row['suffix'] == 'pdf':
                abort(415, description='PDFs are download-only. Image previews are available for JPEG and PNG.')
        except (ValueError, OSError):
            abort(404)
        response = send_file(BytesIO(raw), mimetype=vault.MIME[row['suffix']], max_age=0)
        response.headers['Content-Security-Policy'] = "sandbox; default-src 'none'"
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.post('/documents/<identifier>/delete')
    @document_access
    def document_delete(identifier):
        try:
            vault.remove(identifier)
            flash('Live document deleted. Delete any downloaded backup copies separately.')
        except (ValueError, OSError):
            abort(404)
        return redirect(url_for('document_list'))

    @app.get('/documents/backup')
    @document_access
    def document_backup():
        try:
            content = vault.backup()
        except (ValueError, OSError):
            abort(503)
        return send_file(content, mimetype='application/zip', as_attachment=True, download_name='encrypted-documents.zip', max_age=0)
