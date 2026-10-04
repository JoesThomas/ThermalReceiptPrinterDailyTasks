"""Atomic owner-only writes for private runtime state."""
import json
import os
import tempfile
from pathlib import Path

def write_bytes(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)

def write_json(path, value):
    content = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
    write_bytes(path, content)


class PrivateStateError(ValueError):
    """A private state file is damaged, oversized or fails schema validation."""


class PrivateStore:
    """Shared bounded reads and locked atomic updates; never replace damaged state."""
    def __init__(self, path, *, default, validate=lambda value: None, max_bytes=4_000_000):
        self.path = Path(path)
        self.default = default
        self.validate = validate
        self.max_bytes = max_bytes

    def read(self):
        import copy
        if not self.path.exists():
            return copy.deepcopy(self.default())
        try:
            with self.path.open('rb') as stream:
                content = stream.read(self.max_bytes + 1)
            if len(content) > self.max_bytes:
                raise ValueError('Size limit exceeded')
            value = json.loads(content)
            self.validate(value)
            return value
        except (ValueError, TypeError, KeyError, RecursionError) as error:
            raise PrivateStateError(f'Private state is invalid: {self.path.name}. Restore a valid backup.') from error

    def update(self, change):
        import fcntl
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_suffix('.lock').open('a') as lock:
            os.chmod(lock.name, 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                value = self.read()
                change(value)
                self.validate(value)
                if len(json.dumps(value,ensure_ascii=False,allow_nan=False).encode()) > self.max_bytes:
                    raise PrivateStateError("Private state exceeds its size limit.")
                write_json(self.path, value)
                return value
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
