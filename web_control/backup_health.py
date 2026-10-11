"""Restore drills in a disposable directory; never touches live private data."""
import json
import tempfile
from datetime import datetime,timedelta,timezone
from web_control import private_backup as backup
from storage import write_json


def state(root):
    try:
        value=json.loads((root/'data'/'backup_health.json').read_text())
        return value if isinstance(value,dict) else {}
    except (ValueError,OSError): return {}


def check(root,*,force=False,now=None):
    from web_control.maintenance import PATTERN
    now=now or datetime.now(timezone.utc)
    previous=state(root)
    try: last=datetime.fromisoformat(previous.get('checked_at',''))
    except (ValueError,TypeError): last=None
    if last and last.tzinfo is None: last=last.replace(tzinfo=timezone.utc)
    if not force and last and timedelta(0)<=now-last<timedelta(days=1): return previous
    files=sorted((root/'data'/'private_backups').glob('auto-*.json'),reverse=True)
    files=[p for p in files if PATTERN.fullmatch(p.name) and not p.is_symlink()]
    result={'checked_at':now.isoformat(),'status':'unavailable','backup_created_at':None,'files':0}
    if files:
        try:
            with files[0].open('rb') as stream: value=backup.validate(stream.read(backup.MAX_BYTES+1))
            with tempfile.TemporaryDirectory(prefix='receipt-backup-check-') as folder:
                from pathlib import Path
                temporary=Path(folder)
                backup.restore(temporary,value)
                restored=backup.validate(backup.export(temporary))
                if restored['files']!=value['files']: raise ValueError('Restore mismatch')
            result.update(status='passed',backup_created_at=value.get('created_at'),files=len(value['files']))
        except (ValueError,OSError,KeyError,TypeError): result['status']='failed'
    write_json(root/'data'/'backup_health.json',result)
    return result
