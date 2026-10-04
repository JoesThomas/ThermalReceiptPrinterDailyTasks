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
        return render_template('archive.html', entries=archive.entries(request.args.get('date') or None, request.args.get('q')),
                               selected_date=request.args.get('date', ''), query=request.args.get('q', '')[:200], receipt=None)

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
        names = list(item['pages']) if page == 'all' else [page]
        if any(name not in item['pages'] for name in names):
            abort(404)
        pages = [dict(name=name, blocks=receipt_blocks(item['pages'][name], item.get('page_images', {}).get(name, []))) for name in names]
        freshness = [dict(name=name, status=value['status'], local=uk_receipt_time(value.get('source_checked_at') or value['checked_at']))
                     for name, value in item.get('freshness', {}).items()]
        from receipt.quality import check
        return render_template('archive.html', quality_warnings=check(item['pages'], item.get('freshness', {})), receipt=item, pages=pages, freshness=freshness,
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
        from web_control.maintenance import saved, options
        from web_control.backup_health import state
        from receipt.local_time import uk_receipt_time
        health=state(root)
        return render_template('backup.html', pending=None, saved_backups=saved(root), backup_options=options(), backup_health=health, backup_health_time=uk_receipt_time(health.get('checked_at')), backup_verified_time=uk_receipt_time(health.get('backup_created_at')))

    @app.post('/backup/check')
    @login_required
    def backup_check():
        from web_control.backup_health import check
        try:
            result=check(root,force=True)
            flash('Restore drill passed in a temporary directory.' if result['status']=='passed' else 'Backup verification did not pass. Create a fresh snapshot and check your private files.')
        except (ValueError,OSError): flash('Backup verification could not complete.')
        return redirect(url_for('backup_page'))

    @app.post('/backup/settings')
    @login_required
    def backup_settings():
        from receipt_settings import load_receipt_settings, save_receipt_settings
        try:
            keep = int(request.form.get('keep', '14'))
            if keep not in (7, 14, 30): raise ValueError()
            settings = load_receipt_settings()
            settings['private_backup'] = {'enabled': request.form.get('enabled') == 'on', 'keep': keep}
            save_receipt_settings(settings)
            flash('Automatic backup preferences saved.')
        except ValueError: flash('Choose 7, 14 or 30 snapshots.')
        return redirect(url_for('backup_page'))

    @app.post('/backup/create')
    @login_required
    def backup_create():
        from web_control.maintenance import create
        try:
            with print_lock:
                ok = create(root, force=True)
                if ok:
                    from web_control.backup_health import check
                    check(root,force=True)
            flash('Private snapshot saved.' if ok else 'Wait for the receipt job or backup to finish, then try again.')
        except (OSError, ValueError): flash('Backup could not be saved. Check your local files and disk space.')
        return redirect(url_for('backup_page'))

    @app.get('/backup/saved/<name>')
    @login_required
    def backup_saved_download(name):
        from web_control.maintenance import read_saved
        try: raw = read_saved(root, name)
        except (OSError, ValueError): abort(404)
        response = send_file(BytesIO(raw), as_attachment=True, download_name=name, mimetype='application/json')
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.post('/backup/saved/<name>/review')
    @login_required
    def backup_saved_review(name):
        from web_control.maintenance import read_saved
        try: raw = read_saved(root, name)
        except (OSError, ValueError): abort(404)
        return stage_restore(raw)

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
            backup.validate(raw)
        except ValueError as error:
            flash(str(error))
            return redirect(url_for('backup_page'))
        return stage_restore(raw)

    def stage_restore(raw):
        value = backup.validate(raw)
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
                            pid = int(lock.read_text())
                            if not 0 < pid <= 2_147_483_647:
                                continue
                            os.kill(pid, 0)
                        except PermissionError:
                            raise ValueError('A receipt job may still be running; restore was not started.')
                        except (OSError, ValueError):
                            continue
                        raise ValueError('Wait for the current receipt job to finish before restoring.')
                backup.restore(root, value)
        except (ValueError, OSError) as error:
            flash(str(error) if isinstance(error, (ValueError, backup.RestoreRecoveryError)) else 'Restore failed; check the private rollback record before retrying.')
            return redirect(url_for('backup_page'))
        path.unlink(missing_ok=True)
        session.pop('restore_token', None)
        flash('Local data restored. Existing files outside this backup were kept.')
        return redirect(url_for('backup_page'))
