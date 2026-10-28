"""Isolated browser fixture server. Never run against a user's private data."""
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
folder = tempfile.TemporaryDirectory()
copy = Path(folder.name) / 'project'
shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns('.git', 'data', 'logs', '__pycache__', '*.json', 'secret_key.txt'))
shutil.copy2(ROOT / 'finance' / 'tax_rules.json', copy / 'finance' / 'tax_rules.json')
(copy / 'web_control' / 'secret_key.txt').write_text('browser-test-only-secret')
sys.path[:0] = [str(copy / 'web_control'), str(copy)]
print("Fixture files ready", file=sys.stderr, flush=True)
import app as web
print("Web app imported", file=sys.stderr, flush=True)
from flask import redirect, session
from organiser import vault
vault.KEY_FILE = Path(folder.name) / 'separate-keys' / 'vault.key'
from werkzeug.security import generate_password_hash
fixture_password_hash = generate_password_hash('fixture-only-password')
web.load_password_hash = lambda: fixture_password_hash
from actions import delivery_state
from services import bin_collections
from storage import write_json
from receipt.capture import RecordingPrinter
from receipt.profile import COLUMNS
from receipt.live_preview import VirtualPrinter
from web_control import preview_job

# No external integration or hardware calls are allowed in this fixture process.
fixture_print_commands = []
def fixture_start_print(args):
    fixture_print_commands.append(args)
    return True, ''
web._start_print_command_locked = fixture_start_print

@web.app.get('/__fixture_last_print')
def fixture_last_print():
    from flask import jsonify
    return jsonify(fixture_print_commands[-1] if fixture_print_commands else [])

import requests
patch.object(requests.sessions.Session, 'request', side_effect=RuntimeError('External requests disabled in browser fixtures')).start()
write_json(copy / 'data' / 'subscriptions.json', {'monthly': [], 'yearly': [], 'instalments': []})
row = {'carrier': 'AMAZON', 'event_title': 'Example book', 'order_ref': '123-1234567-1234567', 'delivery_date': str(bin_collections.today())}
delivery_state.record_deliveries([row], lambda value: 'AMAZON', lambda value: 'Expected today')

@web.app.get('/__fixture_login')
def fixture_login():
    session['authenticated'] = True
    return redirect('/bins')


@web.app.get('/__fixture_amex_interest')
def fixture_amex_interest():
    from datetime import date
    from finance.amex_interest import capture
    capture([{'_source_provider': 'AMEX', '_source_account': 'fixture-card',
              'date': date.today().isoformat(), 'amount': 12.34, 'currency': 'GBP',
              'transaction_type': 'DEBIT', 'transaction_category': 'INTEREST',
              'description': 'INTEREST CHARGE', 'provider_transaction_id': 'fixture-interest'}])
    return 'ok'


@web.app.get('/__fixture_backup_data')
def fixture_backup_data():
    from flask import request
    target = copy / 'data' / 'to_buy.json'
    target.write_text('PRIVATE FIXTURE VALUE invalid JSON' if request.args.get('invalid') == '1' else '{"items":[]}')
    return redirect('/backup')


@web.app.get('/__fixture_reviews')
def fixture_reviews():
    from datetime import timedelta
    from decimal import Decimal
    from receipt.local_time import uk_today
    from finance import reviews
    today=uk_today()
    plan={'latest':today,'valid':True,'end':today+timedelta(days=20),'received':Decimal(4500),'spent':Decimal(0),'buckets':[{'name':'Upcoming bills & repayments','amount':Decimal(1000)},{'name':'Estimated everyday spending','amount':Decimal(600)},{'name':'Savings contribution','amount':Decimal(500)}]}
    projection={'cash':Decimal(6000),'buffer':Decimal(1000),'daily':Decimal(20),'payday':today+timedelta(days=21)}
    income={'month_total':Decimal(800),'recent':[{'date':today,'name':'Fixture rent','amount':Decimal(800),'category':'Rent Received'}]}
    summary={'bank_data_status':'complete','requested_from':str(today-timedelta(days=29)),'requested_to':str(today)}
    reviews.capture(plan,[],[],income,projection,summary,None,None,today,Decimal(0))
    return redirect('/finance/results')


@web.app.get('/__fixture_amex_balance')
def fixture_amex_balance():
    from flask import request
    from finance.amex_protection import store
    from datetime import datetime, timezone
    def change(value):
        value['evidence'] = dict(current=request.args.get('amount', '1500'), currency='GBP',
                                checked_at=datetime.now(timezone.utc).isoformat(), amex_ok=True,
                                balances={}, payments=[])
    store().update(change)
    return 'ok'


@web.app.get('/__fixture_villa_calendar')
def fixture_villa_calendar():
    from datetime import datetime, time, timedelta
    from receipt.local_time import uk_today
    from services.villa_fixtures import UK
    from services import calendar_source, villa_fixtures
    today = uk_today()
    kickoff = datetime.combine(today, time(19,45), UK)
    rows = [dict(id='example-cup',kickoff=kickoff,home_team='Bournemouth',away_team='Aston Villa',
                 home_code='BOU',away_code='AVL',is_home=False,venue='Vitality Stadium',competition='English League Cup'),
            dict(id='example-home',kickoff=kickoff+timedelta(days=3),home_team='Aston Villa',away_team='Fulham',
                 home_code='AVL',away_code='FUL',is_home=True,venue='Villa Park',competition='Premier League')]
    personal = [dict(uid='existing-google-event',date=today,time='19:00',title='Bournemouth vs Aston Villa',
                     location='My saved location',start_dt=kickoff,end_dt=kickoff,all_day=False)]
    patch.object(villa_fixtures,'collect_club',return_value=rows).start()
    patch.object(calendar_source,'collect',return_value=personal).start()
    write_json(copy/'passwords.json',dict(calendar={'ical_url':'https://calendar.example.test/fixture.ics'}))
    return redirect('/calendar-map')


@web.app.get('/__fixture_instalment_plan')
def fixture_instalment_plan():
    import json
    from datetime import timedelta
    from receipt.local_time import uk_today
    target = copy / 'data' / 'subscriptions.json'
    data = json.loads(target.read_text())
    if not any('amex' in row.get('name','').casefold() for row in data.get('monthly',[])):
        data.setdefault('monthly',[]).append(dict(name='Amex payment',amount=50,category='repayment',
                                                due_day=min(28,uk_today().day+1)))
    data['instalments'] = [dict(name='Example Amazon headphones', balance='100', monthly_payment='25',
                                next_payment=(uk_today()+timedelta(days=7)).isoformat(), type='payment_plan')]
    write_json(target, data)
    return redirect('/finance/test')


def fixture_preview():
    # Replace external collection, retaining the production capture/save/render path.
    printer = RecordingPrinter(VirtualPrinter(), defer=True)
    printer.text('INFORMATION\nFixture receipt generated\n')
    printer.text('-'*COLUMNS + '\n')
    from io import BytesIO
    import math
    from PIL import Image, ImageDraw
    from receipt.weather_renderers import print_temperature_graph
    print_temperature_graph(printer, [{'time':f'{h:02d}:00','temperature':8+h/3} for h in range(24)],
        _context={'Image':Image,'ImageDraw':ImageDraw,'BytesIO':BytesIO,'math':math,
                  'printer_text':lambda printer,text:printer.text(text)})
    printer.text('-'*COLUMNS + '\n')
    from receipt.capture import LIVE_PREVIEW_FILE
    printer.save('information', path=LIVE_PREVIEW_FILE, replace=True)
    preview_job.save_status('running')
    preview_job.save_status('completed')
    return redirect('/preview?source=live')

@web.app.get('/__fixture_daily_outcome')
def fixture_daily_outcome():
    from receipt.local_time import uk_today
    from web_control.schedule_history import record
    record(uk_today(), 'failed', directory=copy / 'data', preview_saved=True)
    return redirect('/')


@web.app.get('/__fixture_archive_pages')
def fixture_archive_pages():
    from receipt import archive
    for index in range(55):
        archive.save({'information': f'Archive pagination fixture {index}'}, {},
                     '2026-10-11T12:00:00+00:00', 'preview', {})
    return redirect('/receipts?q=Archive+pagination+fixture')


# A controlled background bank fixture exercises the production snapshot/refresh path.
from threading import Event
from types import SimpleNamespace
from datetime import date
from flask import jsonify
finance_release = Event()
finance_manager = web.app.extensions['finance_refresh']

@web.app.get('/__fixture_finance_setup')
def fixture_finance_setup():
    finance_release.set()
    if finance_manager.worker:
        finance_manager.worker.join(2)
    finance_release.clear()
    finance_manager.snapshot_file.unlink(missing_ok=True)
    finance_manager.status_file.unlink(missing_ok=True)
    def collect(progress):
        progress('Retrieving HSBC transactions')
        if not finance_release.wait(30):
            raise TimeoutError('Bank fixture was not released')
        return {'data':([{'date':date.today().isoformat(),'amount':-30,'description':'Fixture everyday store'}], [], [], [], {'bank_data_status':'complete'}),
                'balances':{'HSBC':{'available':500},'MONZO':{'available':50},'AMEX':{'current':0}}}
    finance_manager.collect = collect
    def subscriptions(*args, **kwargs):
        from services.subscriptions import load_subscriptions
        values = load_subscriptions()
        return {'monthly':values.get('monthly',[]),'yearly':values.get('yearly',[]),'ended':[]}
    sys.modules['services.live_pipeline'] = SimpleNamespace(build_subscription_status=subscriptions,
        matching_subscription_transaction=lambda *args:None,
        analyse_incoming_payments=lambda *args,**kwargs:([],[]))
    return redirect('/finance-review')

@web.app.get('/__fixture_finance_release')
def fixture_finance_release():
    finance_release.set()
    if finance_manager.worker:
        finance_manager.worker.join(2)
    return jsonify(finance_manager.public_status())

@web.app.get('/__fixture_finance_fail')
def fixture_finance_fail():
    def fail(progress):
        raise RuntimeError('Simulated unavailable bank')
    finance_manager.collect = fail
    return jsonify(ok=True)


web._generate_live_preview_locked = fixture_preview
if '--stdio' in sys.argv:
    import json
    import base64
    import contextlib
    with web.app.test_client() as client:
        for line in sys.stdin:
            request = json.loads(line)
            with contextlib.redirect_stdout(sys.stderr):
                response = client.open(request['path'], method=request['method'],
                                       data=base64.b64decode(request['body_base64']) if 'body_base64' in request else request.get('body', ''), headers=request.get('headers', {}),
                                       base_url='http://receipt.test')
            print(json.dumps({'status': response.status_code, 'headers': dict(response.headers),
                              'body': base64.b64encode(response.data).decode()}), flush=True)
else:
    raise SystemExit('Use --stdio; the fixture never listens on a network port.')
