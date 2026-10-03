import importlib.util
import os
import subprocess
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

class PrivateToolsWebTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec('flask'), 'Flask required')
    def test_archive_restore_authentication_csrf_and_confirmation(self):
        secret=ROOT/'web_control/secret_key.txt'; created=not secret.exists()
        if created: secret.write_text('private-tools-test-secret')
        try:
            script='''
import sys,tempfile,json
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from flask import Flask
from threading import Lock
sys.path.insert(0,str(Path('web_control').resolve()))
import app as web
from receipt import archive
from web_control.private_tools import register
with tempfile.TemporaryDirectory() as directory:
 root=Path(directory)
 # Separate app avoids touching any real private files.
 app=Flask(__name__,template_folder=str(Path('web_control/templates').resolve()))
 app.secret_key='test'
 app.before_request(web.require_csrf)
 app.jinja_env.globals['csrf_token']=web.csrf_token
 for name in ['index','finance_review','meals_page','calendar_map','generate_live_preview','delivery_checklist','jobs_status','cancel_receipt_job','preview','task_list','exercise_list']:
  app.add_url_rule('/test/'+name,endpoint=name,view_func=lambda:'test')
 app.add_url_rule('/login',endpoint='login',view_func=lambda:'login')
 register(app,web.login_required,lambda args:(True,None),root,Lock())
 with patch.object(archive,'DIRECTORY',root/'data'/'receipt_archive'),app.test_client() as client:
  assert client.get('/backup').status_code==302
  with client.session_transaction() as session:
   session['authenticated']=True;session['csrf_token']='test'
  assert client.post('/backup/restore').status_code==403
  raw=json.dumps({'version':1,'files':{'to_buy.json':{'items':['Example']}}}).encode()
  response=client.post('/backup/restore',data={'csrf_token':'test','backup':(BytesIO(raw),'backup.json')})
  assert response.status_code==200,response.data
  assert not (root/'data'/'to_buy.json').exists()
  with client.session_transaction() as session: token=session['restore_token']
  assert client.post('/backup/restore/confirm',data={'csrf_token':'test','token':'wrong'}).status_code==400
  assert client.post('/backup/restore/confirm',data={'csrf_token':'test','token':token}).status_code==302
  assert (root/'data'/'to_buy.json').exists()
  assert client.get('/backup/download').headers['Cache-Control']=='no-store'
  identifier=archive.save({'information':'<script>bad</script>'},{},'2026-10-02T12:00:00+00:00','preview',{})
  response=client.get('/receipts/'+identifier)
  assert response.status_code==200,response.data
  assert b'&lt;script&gt;bad&lt;/script&gt;' in response.data
  assert client.get('/receipts/'+identifier+'?page=finance').status_code==404
  assert client.post('/receipts/'+identifier+'/print',data={'csrf_token':'test','page':'unknown'}).status_code==400
  assert client.get('/receipts?date=2026-10-02').status_code==200
'''
            result=subprocess.run([sys.executable,'-c',script],cwd=ROOT,env=os.environ.copy(),capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr)
        finally:
            if created:secret.unlink(missing_ok=True)
