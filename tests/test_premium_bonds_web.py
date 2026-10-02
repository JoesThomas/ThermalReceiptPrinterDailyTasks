import importlib.util
import os
import subprocess
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class PremiumBondsWebTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec('flask'),'Flask required')
    def test_editor_and_coverage_are_authenticated_and_csrf_protected(self):
        secret=ROOT/'web_control/secret_key.txt';created=not secret.exists()
        if created:secret.write_text('bonds-test-secret')
        try:
            script='''
import sys,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path('web_control').resolve()))
import app as web
from finance import premium_bonds as bonds
with tempfile.TemporaryDirectory() as directory, patch.object(bonds,'FILE',Path(directory)/'bonds.json'),web.app.test_client() as client:
 assert client.get('/premium-bonds').status_code==302
 with client.session_transaction() as session:
  session['authenticated']=True;session['csrf_token']='test'
 assert client.post('/premium-bonds/record').status_code==403
 assert client.get('/premium-bonds').status_code==200
 for kind,amount in [('balance',10000),('prize',10000)]:
  assert client.post('/premium-bonds/record',data={'csrf_token':'test','kind':kind,'date':'2025-01-01','amount':amount}).status_code==302
 response=client.get('/premium-bonds?year=2025')
 assert b'100.00%' in response.data,response.data
 assert b'Recorded period' in response.data
 assert client.post('/premium-bonds/confirm',data={'csrf_token':'test','year':2025}).status_code==400
 assert client.post('/premium-bonds/confirm',data={'csrf_token':'test','year':2025,'complete':'on'}).status_code==302
 assert b'Annual winnings return' in client.get('/premium-bonds?year=2025').data
 identifier=bonds.load()['prizes'][0]['id']
 assert client.post('/premium-bonds/remove',data={'csrf_token':'test','kind':'prize','id':identifier}).status_code==302
 assert client.get('/premium-bonds?year=oops').status_code==400
'''
            r=subprocess.run([sys.executable,'-c',script],cwd=ROOT,env=os.environ.copy(),capture_output=True,text=True,timeout=20)
            self.assertEqual(r.returncode,0,r.stderr)
        finally:
            if created:secret.unlink(missing_ok=True)
