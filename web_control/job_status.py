"""Shared lifecycle status for manual, scheduled and preview workers."""
import json
import uuid
from datetime import datetime, timezone
from storage import write_json
from web_control.job_runtime import MAX_SECONDS


def save(path, state, *, page=None):
    try:
        previous = json.loads(path.read_text())
    except (OSError, ValueError):
        previous = {}
    now = datetime.now(timezone.utc).isoformat()
    value = {**previous, 'state': state, 'updated_at': now}
    if page is not None:
        value['page'] = page
    if state == 'running':
        value.pop('preview_saved', None)
        value.update(started_at=now, stage_started_at=now, job_id=uuid.uuid4().hex[:12],
                     stage='Preparing receipt', completed=0, total=5,
                     timeout_seconds=MAX_SECONDS, timings=[], stages=[])
    elif state == 'completed' and page is not None:
        value.update(completed=5, stage='Sent to printer; paper output not confirmed')
    elif state != 'completed':
        value['stage'] = {'failed': 'Receipt generation failed; check the job log',
                          'timed_out': 'Time limit reached; child stopped',
                          'cancelled': 'Cancelled; child stopped'}.get(state, state)
    write_json(path, value)
    return value
