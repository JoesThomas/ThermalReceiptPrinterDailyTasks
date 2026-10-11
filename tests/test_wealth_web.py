import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]

class WealthWebTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec('flask'), 'Flask required')
    def test_private_editor_graph_and_security(self):
        secret = ROOT/'web_control/secret_key.txt'
        created = not secret.exists()
        if created:
            secret.write_text('wealth-web-test-secret')
        try:
            script = '''
import sys,tempfile
from pathlib import Path
from unittest.mock import patch
from datetime import date
sys.path.insert(0,str(Path('web_control').resolve()))
from app import app
from finance import wealth_history as wealth
with tempfile.TemporaryDirectory() as directory, patch.object(wealth,'HISTORY_FILE',Path(directory)/'history.json'):
 with app.test_client() as client:
  assert client.get('/savings').status_code==302
  with client.session_transaction() as session:
   session['authenticated']=True
   session['csrf_token']='test'
  assert client.post('/savings/record',data={'name':'Blocked'}).status_code==403
  for day,balance,deposit in [('01','1000','0'),('30','2000','800')]:
   response=client.post('/savings/record',data={'csrf_token':'test','name':'Example ISA','kind':'investment','date':'2026-09-'+day,'balance':balance,'deposits':deposit,'withdrawals':'0'})
   assert response.status_code==302
  response=client.get('/savings?month=2026-09')
  assert response.status_code==200,response.data
  assert b'Example ISA' in response.data
  assert b'+1000.00' in response.data and b'+100.0%' in response.data
  assert b'+200.00' in response.data
  assert b'<polyline' in response.data
  entry=wealth.load_history()[-1]
  assert client.post('/savings/record',data={'csrf_token':'test','name':'Example ISA','kind':'investment','date':'2026-09-30','balance':'1900','deposits':'800','withdrawals':'0'}).status_code==302
  assert len(wealth.load_history())==2
  assert client.post('/savings/delete',data={'csrf_token':'test','entry_id':entry['id']}).status_code==302
  assert len(wealth.load_history())==1
  assert client.get('/savings?month=invalid').status_code==200
'''
            result=subprocess.run([sys.executable,'-c',script],cwd=ROOT,env=os.environ.copy(),capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr)
        finally:
            if created:
                secret.unlink(missing_ok=True)
