import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]

class InterfaceViewsTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec('flask'),'Flask required')
    def test_focused_views_keep_editing_and_navigation(self):
        secret=ROOT/'web_control/secret_key.txt'
        created=not secret.exists()
        if created: secret.write_text('interface-test-secret')
        try:
            script='''
import sys,copy,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path('web_control').resolve()))
import app as web
from receipt_settings import DEFAULT_SETTINGS
from services import local_gigs
settings=copy.deepcopy(DEFAULT_SETTINGS)
settings['therapy_payment']['payee']='Example payee'
subscriptions={'monthly':[{'name':'Example bill','amount':30,'due_day':15,'category':'bill','match':[]}],'yearly':[],'instalments':[]}
with tempfile.TemporaryDirectory() as directory, patch.object(web,'load_receipt_settings',return_value=settings), patch.object(web,'load_routines',return_value=[]), patch.object(web,'load_subscriptions',return_value=subscriptions), patch.object(web,'load_food_shop_items',return_value=([],None)), patch.object(web,'food_shop_override',return_value=None), patch.object(web,'load_to_buy',return_value=[]), patch.object(web,'load_tasks',return_value=[]), patch.object(web,'load_print_status',return_value={'state':'completed','page':'all','updated_at':'2026-10-01T12:00:00+00:00'}), patch.object(local_gigs,'CONFIG_FILE',Path(directory)/'gigs.json'):
 with web.app.test_client() as client:
  with client.session_transaction() as session:
   session['authenticated']=True
   session['csrf_token']='test'
  for view in ['dashboard','receipt','settings','tasks','accounts']:
   response=client.get('/?view='+view)
   assert response.status_code==200,(view,response.data)
   text=response.data.decode()
   assert 'Main navigation' in text and 'main-content' in text
   assert 'aria-current="page"' in text, view
   if view=='dashboard':
    assert 'Next scheduled print' in text and '13:00 BST' in text
    assert 'id="commitments"' not in text and 'name="therapy_payee"' not in text
   if view in ['receipt','settings']:
    for field in ['calendar','weather','therapy_payee','salary_payee','latitude','longitude','return_view']:
     assert 'name="'+field+'"' in text,(view,field)
    assert 'id="routines"' not in text
   if view=='tasks':
    assert 'id="future-tasks"' in text and 'id="routines"' in text
    assert 'id="commitments"' not in text
   if view=='accounts':
    assert 'Example bill' in text and 'id="commitments"' in text
    assert 'id="future-tasks"' not in text
  assert client.get('/?view=unknown').status_code==200
  for name in web.app.jinja_env.list_templates(): web.app.jinja_env.get_template(name)
  with patch.object(web,'save_receipt_settings') as save:
   response=client.post('/save',data={'csrf_token':'test','return_view':'settings','calendar':'on','weather':'on','local_gigs':'on'})
   assert response.status_code==302 and 'view=settings' in response.location
   assert save.call_args.args[0]['features']['weather']
  assert client.post('/save',data={'return_view':'settings'}).status_code==403
'''
            result=subprocess.run([sys.executable,'-c',script],cwd=ROOT,env=os.environ.copy(),capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr)
        finally:
            if created: secret.unlink(missing_ok=True)
