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
  assert client.get('/jobs/status').status_code==200
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
