"""Private bin schedules. Exact council dates; no guessed automatic recurrence."""
import json
import re
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo
import fcntl
import requests
from storage import write_json

FILE = Path(__file__).resolve().parents[1] / 'data' / 'bin_collections.json'
COUNCIL_URL = 'https://www.birmingham.gov.uk/info/50388/check_your_collection_day'
DEFAULT = {'enabled': False, 'provider': 'birmingham', 'address': '', 'postcode': '', 'uprn': '',
           'manual': [], 'collections': [], 'last_success': '', 'last_attempt': '', 'error': ''}


def today(): return datetime.now(ZoneInfo('Europe/London')).date()
def now(): return datetime.now(timezone.utc)


def postcode(value):
    value = re.sub(r'\s+', '', value.upper())
    if not re.fullmatch(r'(?:[A-Z]{1,2}\d[A-Z\d]?\d[A-Z]{2}|GIR0AA)', value):
        raise ValueError('Enter a full UK postcode.')
    return value[:-3] + ' ' + value[-3:]


def label(value, maximum=180):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise ValueError('Enter a valid address or bin label.')
    return value.strip()


def validate(value):
    if not isinstance(value, dict): raise ValueError('Invalid bin settings.')
    if not isinstance(value.get('enabled'), bool) or value.get('provider') not in ('birmingham', 'manual'):
        raise ValueError('Invalid bin settings.')
    for key in ('address', 'postcode', 'uprn', 'last_success', 'last_attempt', 'error'):
        if not isinstance(value.get(key, ''), str): raise ValueError('Invalid bin settings.')
    if value.get('address'): label(value['address'])
    if value.get('postcode'): postcode(value['postcode'])
    if value.get('uprn') and not re.fullmatch(r'\d{6,12}', value['uprn']): raise ValueError('Enter a valid property reference (UPRN).')
    for key in ('last_success', 'last_attempt'):
        if value.get(key):
            stamp = datetime.fromisoformat(value[key])
            if stamp.tzinfo is None: raise ValueError('Invalid check timestamp.')
    for key in ('manual', 'collections'):
        rows = value.get(key, [])
        if not isinstance(rows, list) or len(rows) > 500: raise ValueError('Invalid bin schedule.')
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get('date'), str): raise ValueError('Invalid collection date.')
            date.fromisoformat(row['date']); label(row.get('bin'), 100)
            if key == 'manual' and (type(row.get('repeat', 0)) is not int or row.get('repeat', 0) not in (0,7,14,28)):
                raise ValueError('Repeat every 0, 7, 14 or 28 days.')
    return value


def load():
    try: value = json.loads(FILE.read_text())
    except FileNotFoundError: return dict(DEFAULT)
    except (OSError, ValueError) as error: raise ValueError('Bin settings could not be read.') from error
    return validate({**DEFAULT, **value}) if isinstance(value, dict) else validate(value)


@contextmanager
def transaction():
    FILE.parent.mkdir(parents=True, exist_ok=True)
    with FILE.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            state = load(); yield state; validate(state); write_json(FILE, state)
        finally: fcntl.flock(lock, fcntl.LOCK_UN)


def configure(enabled, provider, address, code, uprn, manual):
    config = {'enabled': enabled, 'provider': provider, 'address': label(address),
              'postcode': postcode(code), 'uprn': uprn.strip(), 'manual': manual}
    validate({**DEFAULT, **config})
    if provider == 'birmingham' and enabled and not config['uprn']:
        raise ValueError('Choose an address or enter its UPRN for automatic checks.')
    with transaction() as state:
        identity = ('provider','address','postcode','uprn')
        if any(state.get(key) != config[key] for key in identity): state.update(DEFAULT)
        state.update(config)


class CouncilHTML(HTMLParser):
    def __init__(self):
        super().__init__(); self.rows=[]; self.addresses=[]; self.table=False; self.row=None; self.cell=None; self.option=None
    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if tag == 'table' and 'data-table' in attrs.get('class','').split(): self.table=True
        if tag == 'tr' and self.table: self.row=[]
        if tag in ('th','td') and self.row is not None: self.cell=[]
        if tag == 'option' and re.fullmatch(r'\d{6,12}',attrs.get('value','')): self.option=[attrs['value'],[]]
    def handle_data(self, data):
        if self.cell is not None: self.cell.append(data)
        if self.option is not None: self.option[1].append(data)
    def handle_endtag(self, tag):
        if tag in ('th','td') and self.cell is not None:
            self.row.append(' '.join(''.join(self.cell).split()));self.cell=None
        if tag == 'tr' and self.row is not None:
            self.rows.append(self.row);self.row=None
        if tag == 'table': self.table=False
        if tag == 'option' and self.option is not None:
            title=' '.join(''.join(self.option[1]).split())
            if title: self.addresses.append({'uprn':self.option[0],'address':label(title)})
            self.option=None


def council_html(params):
    started=time.monotonic()
    with requests.get(COUNCIL_URL, params=params, timeout=(4,8), stream=True, allow_redirects=False) as response:
        response.raise_for_status()
        if response.status_code != 200: raise ValueError('Council lookup unavailable.')
        content=bytearray()
        for chunk in response.iter_content(16384):
            if time.monotonic()-started>12: raise ValueError('Council check timed out.')
            content.extend(chunk)
            if len(content)>2_000_000: raise ValueError('Council response too large.')
    parser=CouncilHTML();parser.feed(content.decode('utf-8',errors='replace'));return parser


def addresses(code):
    result=council_html({'postcode':postcode(code)}).addresses
    if not result: raise ValueError('Address lookup unavailable. Enter your address and UPRN instead.')
    return result[:500]


def collection_date(text, day):
    text=re.sub(r'(\d)(?:st|nd|rd|th)\b',r'\1',text.strip(),flags=re.I)
    for fmt in ('%Y-%m-%d','%a %d/%m/%Y','%d/%m/%Y','%A %d %B %Y','%d %B %Y','%A %d %B','%A %d %b','%a %d %B','%a %d %b','%d %B','%d %b'):
        try:
            parsed=datetime.strptime(text if '%Y' in fmt else text+' 2000',fmt if '%Y' in fmt else fmt+' %Y').date()
            if '%Y' not in fmt:
                year=day.year + (1 if day.month>=10 and parsed.month<=3 else -1 if day.month<=3 and parsed.month>=10 else 0)
                parsed=parsed.replace(year=year)
            return parsed
        except ValueError: pass
    raise ValueError('Unrecognised collection date.')


def fetch(config):
    rows=council_html({'postcode':config['postcode'],'uprn':config['uprn'],'next':'Next'}).rows
    result=[]; day=today()
    for cells in rows:
        if len(cells)<2: continue
        for index in (0,1):
            try: stamp=collection_date(cells[index],day)
            except ValueError: continue
            name=label(cells[1-index],100)
            if stamp>=day: result.append({'date':stamp.isoformat(),'bin':name})
            break
    if not result: raise ValueError('No dated schedule returned. Check the address and UPRN.')
    return sorted([dict(date=key[0],bin=key[1]) for key in {(row['date'],row['bin']) for row in result}],key=lambda r:(r['date'],r['bin']))


def age(stamp):
    try: return (now()-datetime.fromisoformat(stamp)).total_seconds()
    except (ValueError,TypeError): return float('inf')


def refresh(force=False):
    state=load()
    if not state['enabled'] or state['provider']=='manual': return state
    interval=3600 if state.get('error') else 21600
    if not force and age(state.get('last_attempt',''))<interval: return state
    identity=tuple(state[key] for key in ('address','postcode','uprn','provider'))
    try: collections=fetch(state); error=''
    except (requests.RequestException,ValueError):
        collections=None;error='Council check failed. Verify the dates on the council website or use a manual schedule.'
    with transaction() as current:
        if identity!=tuple(current[key] for key in ('address','postcode','uprn','provider')): return current
        from services.api_health import record
        record('Bin collections','failed' if error else 'healthy')
        current.update(last_attempt=now().isoformat(),error=error)
        if collections is not None: current.update(collections=collections,last_success=now().isoformat())
        return dict(current)


def due_on(state, day):
    if not state['enabled']: return []
    if state['provider']=='birmingham':
        if age(state.get('last_success',''))>172800: return []
        rows=state['collections']
        return sorted({row['bin'] for row in rows if row['date']==day.isoformat()})
    result=set()
    for row in state['manual']:
        delta=(day-date.fromisoformat(row['date'])).days
        if delta==0 or (delta>0 and row.get('repeat',0) and delta%row['repeat']==0): result.add(row['bin'])
    return sorted(result)


def reminder_lines(state=None, day=None):
    state=state if state is not None else refresh(); day=day or today()
    names=due_on(state,day+timedelta(days=1))
    lines=['[ ] Put out '+name+' for tomorrow' for name in names]
    if state['enabled'] and state['provider']=='birmingham' and state.get('error'):
        lines.append('BIN CHECK FAILED - verify with council' if not names else 'Bin dates cached - check council changes')
    return lines


def manual_text(rows):
    return '\n'.join(f"{row['date']} | {row['bin']} | {row.get('repeat',0)}" for row in rows)


def parse_manual(text):
    if len(text)>50000: raise ValueError('Manual schedule is too large.')
    rows=[]
    for line in text.splitlines():
        if not line.strip(): continue
        parts=[part.strip() for part in line.split('|')]
        if len(parts) not in (2,3): raise ValueError('Use date | bin name | repeat days, one per line.')
        rows.append({'date':date.fromisoformat(parts[0]).isoformat(),'bin':label(parts[1],100),'repeat':int(parts[2]) if len(parts)==3 else 0})
    validate({**DEFAULT,'manual':rows});return rows
