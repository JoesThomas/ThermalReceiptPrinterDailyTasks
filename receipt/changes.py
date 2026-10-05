"""Compare saved receipt text locally, including partial-page generations."""
from difflib import SequenceMatcher
from receipt import archive


def compare(item):
    previous = {}
    remaining = set(item['pages'])
    for path in sorted(archive.DIRECTORY.glob('*.json'), reverse=True):
        try: candidate = archive.load(path.stem)
        except ValueError: continue
        if candidate['captured_at'] >= item['captured_at']: continue
        for name in list(remaining):
            if name in candidate['pages']:
                previous[name] = candidate['pages'][name]
                remaining.remove(name)
        if not remaining: break
    result = []
    for name, text in item['pages'].items():
        if name not in previous:
            result.append({'page': name, 'baseline': False, 'added': [], 'removed': [], 'changed': False})
            continue
        # Ignore blank lines and decorative rules; preserve meaningful text order.
        def lines(value):
            return [line.strip() for line in value.splitlines() if line.strip() and not line.strip().startswith('Generated ') and set(line.strip()) not in ({'-'}, {'='})]
        before, after = lines(previous[name]), lines(text)
        added = []; removed = []
        for tag, a, b, c, d in SequenceMatcher(None, before, after, autojunk=False).get_opcodes():
            if tag in {'replace', 'delete'}: removed.extend(before[a:b])
            if tag in {'replace', 'insert'}: added.extend(after[c:d])
        result.append({'page': name, 'baseline': True, 'added': added[:50], 'removed': removed[:50],
                       'changed': bool(added or removed), 'truncated': len(added)>50 or len(removed)>50})
    return result
