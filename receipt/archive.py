"""Private dated copies of generated pages; no bank or printer calls when browsing."""
from receipt.profile import COLUMNS
import base64
import json
import re
import uuid
from datetime import datetime, timezone
from io import BytesIO
from functools import lru_cache
from pathlib import Path
from receipt.capture import PAGE_NAMES, receipt_blocks
DIRECTORY = Path(__file__).resolve().parents[1] / 'data' / 'receipt_archive'

def load(identifier):
    if not re.fullmatch(r'[0-9]{8}T[0-9]{6}Z-[a-f0-9]{12}', identifier):
        raise ValueError('Invalid receipt identifier')
    try:
        value = json.loads((DIRECTORY / (identifier + '.json')).read_text())
        if not isinstance(value, dict) or value.get('id') != identifier or not isinstance(value.get('pages'), dict) or not value['pages']:
            raise ValueError()
        if any(name not in PAGE_NAMES or not isinstance(text, str) for name, text in value['pages'].items()):
            raise ValueError()
        if 'test_finance' in value and not isinstance(value['test_finance'],dict): raise ValueError()
        from storage import validate_schema_version
        validate_schema_version(value, 1)
        if 'build' in value and not isinstance(value['build'], dict):
            raise ValueError()
        datetime.fromisoformat(value['captured_at'])
        if value.get('source') not in {'preview', 'printed'} or not isinstance(value.get('page_images', {}), dict) or not isinstance(value.get('freshness', {}), dict):
            raise ValueError()
        if any(not isinstance(images, list) for images in value.get('page_images', {}).values()):
            raise ValueError()
        if any(not isinstance(check, dict) or not isinstance(check.get('status'), str) or not isinstance(check.get('checked_at'), str) for check in value.get('freshness', {}).values()):
            raise ValueError()
        return value
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        raise ValueError('Archived receipt unavailable') from None

def save(pages, images, captured_at, source, freshness, *, test_finance=None):
    DIRECTORY.mkdir(parents=True, exist_ok=True, mode=0o700)
    identifier = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex[:12]
    value = dict(id=identifier, captured_at=captured_at, source=source, pages=pages,
                 page_images=images, freshness=freshness)
    from receipt.build_info import metadata
    value["schema_version"] = 1
    value["build"] = metadata(test_finance.get("values") if test_finance else None, finance="finance" in pages)
    if test_finance is not None: value['test_finance']=test_finance
    target = DIRECTORY / (identifier + '.json')
    from storage import write_json
    write_json(target, value)
    return identifier

@lru_cache(maxsize=128)
def _entry_summary(path, modified_ns, size, inode):
    """Retain small listing/search data, never base64 images or scenario payloads."""
    from zoneinfo import ZoneInfo
    item = load(Path(path).stem)
    local = datetime.fromisoformat(item['captured_at']).astimezone(ZoneInfo('Europe/London'))
    pages = tuple(item['pages'].items())
    return item['id'], item['source'], local, pages, '\n'.join(text for _, text in pages).casefold()


def entries(on=None, query=None, *, limit=None, offset=0):
    result = []
    query = (query or '').strip()[:200].casefold()
    offset = max(0, offset)
    if limit is not None and limit <= 0:
        return result
    matched = 0
    for path in sorted(DIRECTORY.glob('*.json'), reverse=True):
        try:
            stat = path.stat()
            identifier, source, local, pages, search_text = _entry_summary(str(path), stat.st_mtime_ns, stat.st_size, stat.st_ino)
            if on and local.date().isoformat() != on:
                continue
            if query and query not in search_text:
                continue
            matched += 1
            if matched <= offset:
                continue
            matches = []
            if query:
                for name, text in pages:
                    for line in text.splitlines():
                        if query in line.casefold():
                            matches.append({'page': name, 'snippet': line.strip()[:200]})
                            if len(matches) >= 3:
                                break
                    if len(matches) >= 3:
                        break
            result.append(dict(id=identifier, source=source, local=local,
                               pages=[name for name, _ in pages], matches=matches))
            if limit is not None and len(result) >= limit:
                break
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return result


def reprint(identifier, page='all'):
    from receipt.printer import open_printer
    item = load(identifier)
    names = list(item['pages']) if page == 'all' else [page]
    if not names or any(name not in item['pages'] for name in names):
        raise ValueError('Page unavailable')
    from receipt.printer_layout import ContentPrinter
    printer = ContentPrinter(open_printer())
    try:
        printer.hw('init')
        printer.set(font='a', normal_textsize=True, align='left')
        for name in names:
            # Historical captures retain their original columns and indentation.
            widths = [len(row) for row in item['pages'][name].splitlines()
                      if row and set(row) <= {'-', '='} and len(row) in (40, 42, COLUMNS)]
            printer.columns = max(widths) if widths else COLUMNS
            printer.set(align='left')
            for block in receipt_blocks(item['pages'][name], item.get('page_images', {}).get(name, [])):
                if 'text' in block:
                    printer.text(block['text'])
                else:
                    printer.image(BytesIO(base64.b64decode(block['image'].split(',', 1)[1], validate=True)))
            printer.text('\n')
            printer.cut()
        from receipt.recovery import mark
        mark(identifier,'sent_at')
    finally:
        printer.close()
