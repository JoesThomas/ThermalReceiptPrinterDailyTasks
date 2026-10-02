"""Authenticated cancellation of known receipt workers, never arbitrary PIDs."""
import os
import signal
import subprocess
from flask import abort, flash, jsonify, redirect, request, url_for


def register(app, login_required, root, print_status, preview_status):
    @app.get('/jobs/status')
    @login_required
    def jobs_status():
        return jsonify(print=print_status() or {'state': 'idle'},
                       preview=preview_status() or {'state': 'idle'})

    @app.post('/jobs/cancel')
    @login_required
    def cancel_receipt_job():
        kind = request.form.get('kind')
        if kind not in {'print', 'preview'}:
            abort(400)
        filename, script = ('.print_now.lock', 'print_job.py') if kind == 'print' else ('.live_preview.lock', 'preview_job.py')
        try:
            pid = int((root / 'data' / filename).read_text().strip())
            if not 0 < pid <= 2147483647:
                raise ValueError()
            result = subprocess.run(['ps', '-ww', '-p', str(pid), '-o', 'args='],
                                    capture_output=True, text=True, timeout=2, check=False)
            if str(root / 'web_control' / script) not in result.stdout or os.getpgid(pid) != pid:
                flash('Could not verify this worker. Check the job log before stopping it.')
            else:
                os.killpg(pid, signal.SIGTERM)
                flash('Cancellation requested. Wait for the worker to stop before starting another job.')
        except (OSError, ValueError, subprocess.TimeoutExpired):
            flash('The job has already stopped or could not be reached.')
        return redirect(url_for('preview') if kind == 'preview' else url_for('index'))
