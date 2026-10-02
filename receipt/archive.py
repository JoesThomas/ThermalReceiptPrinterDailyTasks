"""Private dated copies of generated pages; no bank or printer calls when browsing."""
import base64
import json
import re
import uuid
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from receipt.capture import PAGE_NAMES, receipt_blocks
DIRECTORY = Path(__file__).resolve().parents[1] / 'data' / 'receipt_archive'

def load(identifier):
    if not re.fullmatch(r'[0-9]{8}T[0-9]{6}Z-[a-f0-9]{12}', identifier):
        raise ValueError('Invalid receipt identifier')
    try:
        return json.loads((DIRECTORY / (identifier + '.json')).read_text())
    except (OSError, ValueError):
        raise ValueError('Archived receipt unavailable') from None

def save(pages, images, captured_at, source, freshness):
    DIRECTORY.mkdir(parents=True, exist_ok=True, mode=0o700)
    identifier = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex[:12]
    value = dict(id=identifier, captured_at=captured_at, source=source, pages=pages,
                 page_images=images, freshness=freshness)
    target = DIRECTORY / (identifier + '.json')
    with target.open('x', encoding='utf-8') as stream:
        target.chmod(0o600)
        json.dump(value, stream, ensure_ascii=False)
    return identifier

def entries(on=None):
    from zoneinfo import ZoneInfo
    result = []
    for path in sorted(DIRECTORY.glob('*.json'), reverse=True):
        try:
            item = load(path.stem)
            local = datetime.fromisoformat(item['captured_at']).astimezone(ZoneInfo('Europe/London'))
            if on and local.date().isoformat() != on:
                continue
            result.append(dict(id=item['id'], source=item['source'], local=local,
                               pages=list(item['pages'])))
        except (ValueError, KeyError, TypeError):
            continue
    return result

def reprint(identifier, page='all'):
    from receipt.printer import open_printer
    item = load(identifier)
    names = [name for name in PAGE_NAMES if name in item['pages']] if page == 'all' else [page]
    if not names or any(name not in item['pages'] for name in names):
        raise ValueError('Page unavailable')
    printer = open_printer()
    try:
        for name in names:
            printer.set(align='left')
            for block in receipt_blocks(item['pages'][name], item.get('page_images', {}).get(name, [])):
                if 'text' in block:
                    printer.text(block['text'])
                else:
                    printer.image(BytesIO(base64.b64decode(block['image'].split(',', 1)[1], validate=True)))
            printer.text('\n')
            printer.cut()
    finally:
        printer.close()
