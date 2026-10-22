"""Owner-only encrypted document store. Key material stays outside the repository."""
from datetime import date
from io import BytesIO
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
import zipfile
from cryptography.fernet import Fernet, InvalidToken
from receipt.local_time import uk_today
from storage import file_lock, write_bytes
from actions.day_assistant import text

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / 'data' / 'document_vault'
KEY_FILE = Path(os.environ.get('RECEIPT_VAULT_KEY_FILE', str(Path.home() / '.config' / 'receipt-control' / 'vault.key')))
MAX_FILE = 5 * 1024 * 1024
MAX_TOTAL = 100 * 1024 * 1024
MAX_DOCS = 100
ID = re.compile(r'[0-9a-f]{32}')
MIME = {'pdf': 'application/pdf', 'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg'}


def private_directory(path):
    if path == DIRECTORY and path.resolve().is_relative_to((ROOT / 'web_control').resolve()):
        raise ValueError('Document storage must be outside the web directory.')
    if path.is_symlink():
        raise ValueError('Linked storage locations are not supported.')
    existed = path.exists()
    if existed and path != DIRECTORY and stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ValueError('Choose a dedicated owner-only key directory (mode 0700).')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path == DIRECTORY or not existed:
        os.chmod(path, 0o700)


def read_private(path, limit):
    if path.is_symlink():
        raise ValueError('Linked private files are not supported.')
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as stream:
        metadata = os.fstat(stream.fileno())
        if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) & 0o077:
            raise ValueError('Private file permissions must be owner-only.')
        raw = stream.read(limit+1)
    if len(raw) > limit:
        raise ValueError('Private file is too large.')
    return raw


def cipher():
    key = KEY_FILE.resolve()
    if KEY_FILE.is_symlink() or key.is_relative_to(ROOT.resolve()) or key.is_relative_to(DIRECTORY.resolve()):
        raise ValueError('The document key must be stored outside the project and document directory.')
    if KEY_FILE.parent.exists() and stat.S_IMODE(KEY_FILE.parent.stat().st_mode) & 0o022:
        raise ValueError('The key directory must not be writable by other users.')
    try:
        return Fernet(read_private(KEY_FILE, 128))
    except FileNotFoundError:
        raise ValueError('Initialise document storage or restore its separate key.') from None


def initialise():
    private_directory(DIRECTORY)
    if any(DIRECTORY.glob('*.enc')) and not (DIRECTORY / 'index.enc').exists():
        raise ValueError('Document index is missing. Restore an encrypted backup.')
    if any(DIRECTORY.glob('*.enc')) and not KEY_FILE.exists():
        raise ValueError('Encrypted documents exist. Restore their original key; do not replace it.')
    if not KEY_FILE.exists():
        if KEY_FILE.resolve().is_relative_to(ROOT.resolve()) or KEY_FILE.resolve().is_relative_to(DIRECTORY.resolve()):
            raise ValueError('Choose an external document key location.')
        private_directory(KEY_FILE.parent)
        descriptor = os.open(KEY_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(Fernet.generate_key())
            stream.flush()
            os.fsync(stream.fileno())
    encryption = cipher()
    with file_lock(DIRECTORY / 'index.json'):
        if not (DIRECTORY / 'index.enc').exists():
            write_bytes(DIRECTORY / 'index.enc', encryption.encrypt(b'{"version":1,"documents":{}}'))
        index()  # Refuse a wrong key rather than silently replacing the index.


def validate(value):
    if not isinstance(value, dict) or value.get('version') != 1 or not isinstance(value.get('documents'), dict) or len(value['documents']) > MAX_DOCS:
        raise ValueError('Invalid document index.')
    for identifier, row in value['documents'].items():
        if not ID.fullmatch(identifier) or not isinstance(row, dict) or row.get('suffix') not in MIME or type(row.get('size')) is not int or not 0 < row['size'] <= MAX_FILE:
            raise ValueError('Invalid document metadata.')
        text(row.get('title'), 100)
        if row.get('expires'):
            date.fromisoformat(row['expires'])


def index():
    if not (DIRECTORY / 'index.enc').exists():
        return {'version': 1, 'documents': {}}
    try:
        value = json.loads(cipher().decrypt(read_private(DIRECTORY / 'index.enc', 250_000)))
        validate(value)
        return value
    except (InvalidToken, KeyError, TypeError):
        raise ValueError('Document storage cannot be decrypted or is damaged.') from None


def save_index(value):
    validate(value)
    write_bytes(DIRECTORY / 'index.enc', cipher().encrypt(json.dumps(value).encode()))


def listing():
    if not DIRECTORY.exists():
        return []
    private_directory(DIRECTORY)
    if any(DIRECTORY.glob('*.enc')) and not (DIRECTORY / 'index.enc').exists():
        raise ValueError('Document index is missing. Restore its encrypted backup.')
    with file_lock(DIRECTORY / 'index.json'):
        value = index()
        expired = [i for i, row in value['documents'].items() if row.get('expires') and date.fromisoformat(row['expires']) <= uk_today()]
        for identifier in expired:
            del value['documents'][identifier]
        if expired:
            save_index(value)
            for identifier in expired:
                (DIRECTORY / (identifier + '.enc')).unlink(missing_ok=True)
        # Clean encrypted orphan files left by interrupted uploads/deletions.
        for path in DIRECTORY.glob('*.enc'):
            if path.name != 'index.enc' and path.stem not in value['documents']:
                path.unlink()
        return [{'id': identifier, **row} for identifier, row in value['documents'].items()]


def upload(stream, filename, title, expires=None):
    title = text(title, 100)
    if not filename or any(c in filename for c in ('/', '\\', ':')) or any(ord(c) < 32 for c in filename):
        raise ValueError('Use a plain PDF, JPEG or PNG filename.')
    suffix = filename.rsplit('.', 1)[-1].lower()
    if suffix not in MIME:
        raise ValueError('Only PDF, JPEG and PNG documents are supported.')
    if expires and date.fromisoformat(expires) <= uk_today():
        raise ValueError('Choose a future retention date.')
    raw = stream.read(MAX_FILE+1)
    if not raw or len(raw) > MAX_FILE:
        raise ValueError('Documents must be no larger than 5 MiB.')
    try:
        result = subprocess.run([sys.executable, str(Path(__file__).with_name('document_check.py')), suffix],
                                input=raw, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=8, check=True)
    except (subprocess.SubprocessError, OSError):
        raise ValueError('File failed the document format and safety checks. Use a passive PDF or a JPEG/PNG image.') from None
    if not result.stdout or len(result.stdout) > MAX_FILE:
        raise ValueError('The validated document exceeds the size limit.')
    raw = result.stdout
    private_directory(DIRECTORY)
    encryption = cipher()  # Never create or overwrite a key during an upload.
    listing()
    identifier = secrets.token_hex(16)
    path = DIRECTORY / (identifier + '.enc')
    with file_lock(DIRECTORY / 'index.json'):
        value = index()
        if len(value['documents']) >= MAX_DOCS or sum(row['size'] for row in value['documents'].values()) + len(raw) > MAX_TOTAL:
            raise ValueError('Document storage quota reached (100 documents / 100 MiB).')
        token = encryption.encrypt(identifier.encode() + b'\n' + raw)
        write_bytes(path, token)
        try:
            value['documents'][identifier] = {'title': title, 'suffix': suffix, 'size': len(raw), 'expires': expires, 'created': uk_today().isoformat()}
            save_index(value)
        except Exception:
            path.unlink(missing_ok=True)
            raise
    return identifier


def read(identifier):
    if not ID.fullmatch(identifier):
        raise ValueError('Document not found.')
    listing()  # Enforce retention on every read, not only the listing screen.
    row = index()['documents'].get(identifier)
    if row is None:
        raise ValueError('Document not found or retention date reached.')
    try:
        decoded = cipher().decrypt(read_private(DIRECTORY / (identifier + '.enc'), MAX_FILE * 2))
        if not decoded.startswith(identifier.encode() + b'\n'):
            raise ValueError('Document identity mismatch.')
        raw = decoded[33:]
        if len(raw) != row['size']:
            raise ValueError('Document size mismatch.')
        return row, raw
    except InvalidToken:
        raise ValueError('Document failed its integrity check.') from None


def remove(identifier):
    if not ID.fullmatch(identifier):
        raise ValueError('Document not found.')
    with file_lock(DIRECTORY / 'index.json'):
        value = index()
        if identifier not in value['documents']:
            raise ValueError('Document not found.')
        del value['documents'][identifier]
        save_index(value)
        (DIRECTORY / (identifier + '.enc')).unlink(missing_ok=True)


def backup():
    listing()
    output = BytesIO()
    with file_lock(DIRECTORY / 'index.json'), zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED) as archive:
        value = index()
        archive.writestr('index.enc', read_private(DIRECTORY / 'index.enc', 250_000))
        for identifier in value['documents']:
            archive.writestr(identifier + '.enc', read_private(DIRECTORY / (identifier + '.enc'), MAX_FILE*2))
    output.seek(0)
    return output


def restore(raw):
    """Explicit offline recovery; accepts only a bounded, authenticated vault backup."""
    if len(raw) > MAX_TOTAL * 2:
        raise ValueError('Backup is too large.')
    with zipfile.ZipFile(BytesIO(raw)) as archive:
        infos = archive.infolist()
        if len(infos) > MAX_DOCS + 1 or len({i.filename for i in infos}) != len(infos) or sum(i.file_size for i in infos) > MAX_TOTAL * 2 or any(i.compress_type != zipfile.ZIP_STORED for i in infos):
            raise ValueError('Invalid encrypted backup.')
        token = archive.read('index.enc')
        value = json.loads(cipher().decrypt(token))
        validate(value)
        expected = {'index.enc', *(i + '.enc' for i in value['documents'])}
        if {i.filename for i in infos} != expected:
            raise ValueError('Unexpected backup contents.')
        files = {}
        for identifier, row in value['documents'].items():
            content = archive.read(identifier + '.enc')
            decoded = cipher().decrypt(content)
            if not decoded.startswith(identifier.encode() + b'\n') or len(decoded[33:]) != row['size']:
                raise ValueError('Damaged encrypted backup.')
            files[identifier] = content
        private_directory(DIRECTORY)
        with file_lock(DIRECTORY / 'index.json'):
            if index()['documents']:
                raise ValueError('Restore requires an empty vault; existing documents are never overwritten.')
            for identifier, content in files.items():
                write_bytes(DIRECTORY / (identifier + '.enc'), content)
            write_bytes(DIRECTORY / 'index.enc', token)
        listing()
