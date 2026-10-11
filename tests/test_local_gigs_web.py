import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]

class LocalGigsWebTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec('flask'),'Flask required')
    def test_web_links_configuration_csrf_and_private_key(self):
        secret=ROOT/'web_control/secret_key.txt'
        created=not secret.exists()
        if created: secret.write_text('local-gigs-test-secret')
        try:
            script='''
import sys,tempfile
from datetime import date
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path('web_control').resolve()))
from app import app
import receipt_settings
from services import local_gigs as gigs
from tests.test_local_gigs import FakeResponse,event
with tempfile.TemporaryDirectory() as directory, patch.object(gigs,'CONFIG_FILE',Path(directory)/'key.json'), patch.object(receipt_settings,'SETTINGS_FILE',Path(directory)/'settings.json'), patch.dict('os.environ',{},clear=True):
 with app.test_client() as client:
  assert client.get('/gigs').status_code==302
  with client.session_transaction() as session:
   session['authenticated']=True
   session['csrf_token']='test'
  assert client.post('/gigs/settings',data={'api_key':'Blocked'}).status_code==403
  response=client.get('/gigs')
  assert response.status_code==200
  assert b'Add a Ticketmaster' in response.data
  assert client.post('/gigs/settings',data={'csrf_token':'test','enabled':'on','radius_km':'25','receipt_limit':'8','api_key':'PrivateTestKey'}).status_code==302
  assert gigs.api_key()=='PrivateTestKey'
  assert gigs.options()['enabled']
  show=event()
  show['_embedded']['venues'][0]['location']={'latitude':'52.4294','longitude':'-1.92035'}
  with patch.object(gigs,'urlopen',return_value=FakeResponse({'_embedded':{'events':[show]},'page':{'totalPages':1}})):
   response=client.get('/gigs?date=2026-10-01')
  assert response.status_code==200,response.data
  assert b'Example gig' in response.data and b'Example venue' in response.data
  assert b'https://example.com/tickets' in response.data
  assert b'PrivateTestKey' not in response.data
  assert client.get('/gigs?date=invalid').status_code==400
  with patch.object(gigs,'urlopen',side_effect=RuntimeError()):
   assert client.get('/gigs?date=2026-10-02').status_code==200
  assert client.post('/gigs/settings',data={'csrf_token':'test','enabled':'on','radius_km':'0','receipt_limit':'8'}).status_code==302
  assert gigs.options()['radius_km']==25
  assert client.post('/gigs/settings',data={'csrf_token':'test','radius_km':'25','receipt_limit':'8','clear_key':'on'}).status_code==302
  assert not gigs.api_key()
  assert not gigs.options()['enabled']
  app.jinja_env.get_template('index.html')
'''
            result=subprocess.run([sys.executable,'-c',script],cwd=ROOT,env=os.environ.copy(),capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr)
        finally:
            if created: secret.unlink(missing_ok=True)
