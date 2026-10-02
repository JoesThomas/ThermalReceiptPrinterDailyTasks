"""Authenticated views for private history and backup management."""
import json
import secrets
import time
from io import BytesIO
from flask import abort, flash, redirect, render_template, request, send_file, session, url_for
from receipt import archive
from receipt.capture import PAGE_NAMES, receipt_blocks
from receipt.local_time import uk_receipt_time
from web_control import private_backup as backup

def register(app, login_required, start_print, root, print_lock):
    @app.get('/receipts')
    @login_required
    def archive_list():
        return render_template('archive.html', entries=archive.entries(request.args.get('date') or None),
                               selected_date=request.args.get('date', ''), receipt=None)

    @app.get('/receipts/<identifier>')
    @login_required
    def archive_detail(identifier):
        try:
            item = archive.load(identifier)
        except ValueError:
            abort(404)
        page = request.args.get('page', 'all')
        if page not in {'all', *PAGE_NAMES}:
            abort(400)
        names = [name for name in PAGE_NAMES if name in item['pages']] if page == 'all' else [page]
        if any(name not in item['pages'] for name in names):
            abort(404)
        pages = [dict(name=name, blocks=receipt_blocks(item['pages'][name], item.get('page_images', {}).get(name, []))) for name in names]
        freshness = [dict(name=name, status=value['status'], local=uk_receipt_time(value['checked_at']))
                     for name, value in item.get('freshness', {}).items()]
        return render_template('archive.html', receipt=item, pages=pages, freshness=freshness,
                               captured_local=uk_receipt_time(item['captured_at']))

    @app.post('/receipts/<identifier>/print')
    @login_required
    def archive_print(identifier):
        try:
            item = archive.load(identifier)
        except ValueError:
            abort(404)
        page = request.form.get('page', 'all')
        if page != 'all' and page not in item['pages']:
            abort(400)
        ok, error = start_print(['--archive', identifier, page])
        flash('Archived receipt queued for printing.' if ok else error)
        return redirect(url_for('archive_detail', identifier=identifier))

    @app.get('/backup')
    @login_required
    def backup_page():
        return render_template('backup.html', pending=None)

    @app.get('/backup/download')
    @login_required
    def backup_download():
        try:
            raw = backup.export(root)
        except (ValueError, OSError):
            flash('Backup could not be created. Check the local data files and size limit.')
            return redirect(url_for('backup_page'))
        response = send_file(BytesIO(raw), as_attachment=True, download_name='receipt-control-private-backup.json', mimetype='application/json')
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.post('/backup/restore')
    @login_required
    def backup_preview():
        uploaded = request.files.get('backup')
        if uploaded is None:
            abort(400)
        try:
            raw = uploaded.stream.read(backup.MAX_BYTES + 1)
            value = backup.validate(raw)
        except ValueError as error:
            flash(str(error))
            return redirect(url_for('backup_page'))
        token = secrets.token_hex(24)
        directory = root / 'data' / 'restore_pending'
        # Remove expired staging files, never active restore candidates.
        for old in directory.glob('*.json'):
            if time.time() - old.stat().st_mtime > 900:
                old.unlink(missing_ok=True)
        backup.private_write(directory / (token + '.json'), raw)
        session['restore_token'] = token
        return render_template('backup.html', pending=value['files'])

    @app.post('/backup/restore/confirm')
    @login_required
    def backup_confirm():
        token = session.get('restore_token', '')
        if not token or not secrets.compare_digest(token, request.form.get('token', '')):
            abort(400)
        path = root / 'data' / 'restore_pending' / (token + '.json')
        try:
            if time.time() - path.stat().st_mtime > 900:
                raise ValueError('Restore preview expired; upload the backup again.')
            value = backup.validate(path.read_bytes())
            with print_lock:
                for lock_name in ('.print_now.lock', '.live_preview.lock'):
                    lock = root / 'data' / lock_name
                    if lock.exists():
                        import os
                        try:
                            os.kill(int(lock.read_text()), 0)
                        except (OSError, ValueError):
                            continue
                        raise ValueError('Wait for the current receipt job to finish before restoring.')
                backup.restore(root, value)
        except (ValueError, OSError) as error:
            flash(str(error) if isinstance(error, ValueError) else 'Restore failed; previous local files were retained.')
            return redirect(url_for('backup_page'))
        path.unlink(missing_ok=True)
        session.pop('restore_token', None)
        flash('Local data restored. Existing files outside this backup were kept.')
        return redirect(url_for('backup_page'))
