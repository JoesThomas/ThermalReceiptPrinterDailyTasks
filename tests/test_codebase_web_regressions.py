import importlib.util
import os
import subprocess
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class CodebaseWebTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec('flask'),'Flask required')
    def test_job_lock_input_validation_and_private_response_headers(self):
        secret=ROOT/'web_control/secret_key.txt';created=not secret.exists()
        if created:secret.write_text('review-test-secret')
        try:
            code='''
import sys,tempfile,json,os,time
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from threading import Thread
sys.path.insert(0,str(Path('web_control').resolve()))
import app as web
from web_control.private_backup import validate
with tempfile.TemporaryDirectory() as folder,patch.object(web,'PROJECT_ROOT',Path(folder)):
 root=Path(folder);(root/'data').mkdir()
 with web.app.test_client() as client:
  with client.session_transaction() as session:
   session['authenticated']=True;session['csrf_token']='test'
  from copy import deepcopy
  from receipt_settings import DEFAULT_SETTINGS
  with patch.object(web,'load_receipt_settings',return_value=deepcopy(DEFAULT_SETTINGS)),patch.object(web,'save_receipt_settings') as save:
   assert client.post('/settings/print-schedule',data={'csrf_token':'test','time':'08:45','enabled':'on'}).status_code==302
   assert save.call_args.args[0]['print_schedule']=={'enabled':True,'time':'08:45'}
   save.reset_mock()
   assert client.post('/settings/print-schedule',data={'csrf_token':'test','time':'25:00'}).status_code==302
   save.assert_not_called()
   assert client.post('/settings/print-schedule',data={'time':'08:45'}).status_code==403
  from actions import checklists
  with patch.object(checklists,'FILE',root/'data'/'daily_lists.json'):
   assert client.get('/tasks').status_code==200
   assert client.get('/exercises').status_code==200
   assert client.post('/lists/tasks/update',data={'action':'add','title':'Test'}).status_code==403
   assert client.post('/lists/tasks/update',data={'csrf_token':'test','action':'add','title':'Test task'}).status_code==302
   item=checklists.rows('tasks')[0]
   assert client.post('/lists/tasks/update',data={'csrf_token':'test','action':'toggle','id':item['id']}).status_code==302
   assert checklists.rows('tasks')[0]['completed']
   response=client.get('/tasks');assert b'Test task' in response.data
   checklists.sync('Dumbbell curls\\nRowing\\nPlank', 'exercises')
   assert client.post('/exercises/plan',data={'action':'suggest'}).status_code==403
   assert client.post('/exercises/plan',data={'csrf_token':'test','action':'equipment','equipment':'dumbbells'}).status_code==302
   assert client.post('/exercises/plan',data={'csrf_token':'test','action':'suggest'}).status_code==302
   response=client.get('/exercises');assert response.status_code==200 and b'Today' in response.data
   assert 1 <= len(checklists.exercise_plan(5)) <= 5
   assert all(set(checklists.required_equipment(r)) <= {'dumbbells'} for r in checklists.exercise_plan(5))
   assert b'Today' in response.data and b'receipt workout' in response.data
   assert client.get('/tasks?q=missing').status_code==200
   with patch.object(web,'load_food_shop_items',return_value=([],None)),patch.object(web,'load_routines',return_value=[]),patch.object(web,'load_subscriptions',return_value={}),patch.object(web,'load_receipt_settings',return_value=deepcopy(DEFAULT_SETTINGS)):
    response=client.get('/');assert response.status_code==200,response.data
    assert b'Tasks, plans and arrivals' in response.data
    assert b'Data freshness' in response.data
   with patch.object(web,'load_receipt_settings',return_value=deepcopy(DEFAULT_SETTINGS)),patch.object(web,'save_receipt_settings') as save:
    assert client.post('/settings/receipt-layout',data={'page_0':'actions'}).status_code==403
    assert client.post('/settings/receipt-layout',data={'csrf_token':'test','detail':'compact','page_0':'actions','page_1':'information','page_2':'food','page_3':'finance'}).status_code==302
    assert save.call_args.args[0]['layout']['order'][0]=='actions'
    save.reset_mock()
    client.post('/settings/receipt-layout',data={'csrf_token':'test','detail':'compact','page_0':'actions','page_1':'actions','page_2':'food','page_3':'finance'})
    save.assert_not_called()
  from services import bin_collections as bins
  with patch.object(bins,'FILE',root/'data'/'bin_collections.json'):
   assert client.get('/bins').status_code==200
   assert client.post('/bins/save',data={'address':'Example'}).status_code==403
   assert client.post('/bins/refresh').status_code==403
   assert client.post('/bins/lookup').status_code==403
   assert client.post('/bins/save',data={'csrf_token':'test','enabled':'on','provider':'manual','address':'Example Road','postcode':'B1 1AA','manual':'2026-10-05 | General waste | 7'}).status_code==302
   response=client.get('/bins');assert response.status_code==200 and b'Example Road' in response.data
  from services import api_health as health
  with patch.object(health,'ROOT',root),patch.object(health,'FILE',root/'data'/'health.json'),patch.object(health,'RUN_LOCK',root/'data'/'health_run.lock'):
   health.record('Gmail','failed',code=403,reason='http')
   response=client.get('/api-health');assert response.status_code==200 and b'HTTP 403' in response.data
   assert client.post('/api-health/settings',data={'interval':'60'}).status_code==403
   assert client.post('/api-health/check').status_code==403
   with patch('web_control.health_tools.load_receipt_settings',return_value=deepcopy(DEFAULT_SETTINGS)),patch('web_control.health_tools.save_receipt_settings') as save:
    assert client.post('/api-health/settings',data={'csrf_token':'test','enabled':'on','interval':'180'}).status_code==302
    assert save.call_args.args[0]['api_health']=={'enabled':True,'interval_minutes':180}
    save.reset_mock()
    client.post('/api-health/settings',data={'csrf_token':'test','interval':'1'})
    save.assert_not_called()
   with patch('web_control.health_tools.Thread') as thread:
    assert client.post('/api-health/check',data={'csrf_token':'test'}).status_code==302
    thread.return_value.start.assert_called_once()
  from web_control import daily_tools, reconciliation, live_data
  from meals import legacy_planner as meals
  from services import source_cache
  with patch.object(daily_tools,'dashboard',return_value={'tasks':[],'exercises':[],'deliveries':[]}),patch.object(meals,'recipes',return_value=[{'name':'Example recipe'}]),patch.object(live_data,'MEALS_EATEN_FILE',root/'data'/'meals.json'):
   response=client.get('/quick-actions');assert response.status_code==200 and b'Example recipe' in response.data
   assert client.post('/meals/eaten',data={'csrf_token':'test','recipe':'Example recipe','return_quick':'1'}).location.endswith('/quick-actions')
   assert client.post('/meals/eaten/clear',data={'csrf_token':'test','return_quick':'1'}).location.endswith('/quick-actions')
  with patch.object(source_cache,'FILE',root/'data'/'source_cache.json'):
   response=client.get('/printer-diagnostics');assert response.status_code==200 and b'Printer connection' in response.data
   assert client.post('/printer-diagnostics/check').status_code==403
   assert client.post('/printer-diagnostics/test').status_code==403
   assert client.post('/sources/refresh').status_code==403
   with patch.object(daily_tools,'readiness',return_value=(False,'Printer unreachable')),patch.object(daily_tools,'write_json') as save:
    assert client.post('/printer-diagnostics/check',data={'csrf_token':'test'}).status_code==302
    assert save.call_args.args[1]['reachable'] is False
  with patch.object(reconciliation,'QUEUE',root/'data'/'queue.json'),patch.object(reconciliation,'RULES',root/'data'/'categories.json'):
   reconciliation.save_review([{'date':web._local_today().isoformat(),'description':'EXAMPLE SHOP','amount':-12}],[],web._local_today())
   response=client.get('/finance-reconciliation');assert response.status_code==200 and b'EXAMPLE SHOP' in response.data
   identity=reconciliation.read(reconciliation.QUEUE)['payments'][0]['id']
   assert client.post('/finance-reconciliation/category',data={'id':identity}).status_code==403
   assert client.post('/finance-reconciliation/category',data={'csrf_token':'test','id':identity,'category':'GIFTS','scope':'purchase'}).status_code==302
   assert reconciliation.read(reconciliation.RULES)['transactions'][0]['category']=='GIFTS'
   assert b'EXAMPLE SHOP' not in client.get('/finance-reconciliation').data
   before=reconciliation.RULES.read_bytes()
   client.post('/finance-reconciliation/category',data={'csrf_token':'test','id':identity,'category':'INVALID'})
   assert reconciliation.RULES.read_bytes()==before
  from finance import savings_goals as goals, wealth_history
  with patch.object(goals,'FILE',root/'data'/'goals.json'),patch.object(wealth_history,'HISTORY_FILE',root/'data'/'history.json'),patch('finance.premium_bonds.load',return_value={'balances':[]}):
   assert client.post('/savings/isa/create').status_code==403
   assert client.post('/savings/isa/balance').status_code==403
   assert client.post('/savings/isa/rate').status_code==403
   assert client.post('/savings/isa/create',data={'csrf_token':'test','name':'Created cash ISA','type':'cash_isa','date':web._local_today().isoformat(),'balance':'1250'}).status_code==302
   created=goals.identity('Created cash ISA','savings')
   assert created in goals.load()['accounts']
   assert client.post('/savings/isa/balance',data={'csrf_token':'test','account':created,'date':web._local_today().isoformat(),'balance':'1300'}).status_code==302
   assert client.post('/savings/goals/contribution',data={'csrf_token':'test','name':'Created cash ISA','kind':'savings','date':web._local_today().isoformat(),'amount':'50','event':'interest'}).status_code==302
   assert client.post('/savings/goals/account',data={'name':'Example ISA'}).status_code==403
   assert client.post('/savings/goals/contribution').status_code==403
   assert client.post('/savings/goals/contribution/remove').status_code==403
   assert client.post('/savings/goals/year').status_code==403
   assert client.post('/savings/goals/account',data={'csrf_token':'test','name':'Example ISA','kind':'investment','type':'stocks_isa'}).status_code==302
   assert client.post('/savings/goals/contribution',data={'csrf_token':'test','name':'Example ISA','kind':'investment','type':'stocks_isa','date':web._local_today().isoformat(),'amount':'1000','event':'contribution'}).status_code==302
   response=client.get('/savings/goals');assert response.status_code==200,response.data
   assert b'Combined adult ISA contributions' in response.data
   assert b'1,000.00' in response.data
   assert b'Remaining allowance is not verified' in response.data
   year=goals.tax_year(web._local_today())
   assert client.post('/savings/goals/year',data={'csrf_token':'test','year':year,'allowance':'20000','cash_limit':'20000','complete':'on'}).status_code==302
   response=client.get('/savings/goals');assert b'19,000.00' in response.data
   identity=next(e['id'] for e in goals.load()['entries'] if e['event']=='contribution')
   assert client.post('/savings/goals/contribution/remove',data={'csrf_token':'test','id':identity}).status_code==302
   assert all(e['event']=='interest' for e in goals.load()['entries'])
   assert b'1,300.00' in client.get('/savings/goals').data
  assert client.get('/jobs/status').status_code==200
  for endpoint in ['/print-plan','/preview/print-saved','/deliveries/status','/meals/skip']:
   assert client.post(endpoint).status_code==403
  assert client.post('/jobs/cancel',data={'kind':'print'}).status_code==403
  assert client.get('/deliveries').status_code==200
  assert client.post('/deliveries/confirm',data={'id':'unknown','confirmed':'1'}).status_code==403
  response=client.get('/premium-bonds')
  assert response.headers['Cache-Control']=='no-store'
  assert response.headers['X-Content-Type-Options']=='nosniff'
  for amount in ['NaN','Infinity','-1']:
   with patch.object(web,'load_subscriptions',return_value={'instalments':[{'name':'Example'}]}),patch.object(web,'save_subscriptions') as save:
    assert client.post('/instalment/0/update',data={'csrf_token':'test','amount':amount}).status_code==302
    save.assert_not_called()
  for raw in [{'features':[]},{'features':{'weather':'yes'}}]:
   try:validate(json.dumps({'version':1,'files':{'receipt_settings.json':raw}}).encode())
   except ValueError:pass
   else:raise AssertionError('invalid restore accepted')
  try:validate(b'{"version":1,"files":{"finance_settings.json":{"amount":1e999}}}')
  except ValueError:pass
  else:raise AssertionError('overflow accepted')
  lock=root/'data'/'.print_now.lock'
  for pid in ['0','-1','9999999999999999999']:
   lock.write_text(pid);assert not web._job_active(lock)
  lock.write_text(str(os.getpid()))
  with patch.object(web.subprocess,'Popen') as start:
   assert client.post('/preview/generate',data={'csrf_token':'test'}).status_code==302
   start.assert_not_called()
  lock.unlink()
 calls=[];statuses=[]
 def popen(*args,**kwargs):
  calls.append(args);time.sleep(.05);return SimpleNamespace(pid=os.getpid())
 def preview():
  with web.app.test_client() as client:
   with client.session_transaction() as session:session['authenticated']=True;session['csrf_token']='test'
   response=client.post('/preview/generate',data={'csrf_token':'test'});statuses.append(response.status_code)
 with patch.object(web.subprocess,'Popen',side_effect=popen),patch.object(web,'watch_job'):
  threads=[Thread(target=preview),Thread(target=preview)]
  for thread in threads:thread.start()
  for thread in threads:thread.join()
 assert statuses==[302,302],statuses
 assert len(calls)==1,calls
 assert web._start_print_command([])[0] is False
'''
            r=subprocess.run([sys.executable,'-c',code],cwd=ROOT,env=os.environ.copy(),capture_output=True,text=True,timeout=20)
            self.assertEqual(r.returncode,0,r.stderr)
        finally:
            if created:secret.unlink(missing_ok=True)
