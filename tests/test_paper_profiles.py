"""Roll arithmetic, safe persistence and real narrow-profile rendering."""
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from flask import Flask
from receipt import paper_settings as paper
from receipt.paper import estimate
from receipt.profile import fit_text
from web_control.paper_settings import register

ROOT = Path(__file__).resolve().parents[1]


class PaperProfileTests(TestCase):
    def test_roll_arithmetic_counts_initial_roll_separately(self):
        settings = dict(paper.DEFAULT, roll_length_m=10, waste_percent=0, prints_per_week=7, line_mm=10, cutter_mm=0)
        result = estimate({'information': 'one line'}, settings=settings)
        self.assertEqual(result['year_metres'], 3.6)  # 1 cm/day = 3.65 m/year before rounding.
        self.assertEqual(result['rolls_required'], 1)
        self.assertEqual(result['replacements'], 0)
        self.assertEqual(result['days_per_roll'], 1000)
        settings['roll_length_m'] = 1
        result = estimate({'information':'one line'}, settings=settings)
        self.assertEqual((result['rolls_required'],result['replacements']), (4,3))
        settings.update(prints_per_week=0)
        result = estimate({'information':'one line'}, settings=settings)
        self.assertEqual(result['rolls_required'],0)
        self.assertIsNone(result['days_per_roll'])

    def test_waste_frequency_and_exact_boundary(self):
        settings = dict(paper.DEFAULT, roll_length_m=73, waste_percent=0, prints_per_week=7, line_mm=10, cutter_mm=0)
        pages = {'information':'\n'.join(['line']*20)}  # 20 cm/day; exactly 73 m/year.
        result = estimate(pages, settings=settings)
        self.assertEqual((result['rolls_required'],result['replacements']), (1,0))
        settings['waste_percent']=5
        self.assertEqual(estimate(pages, settings=settings)['rolls_required'],2)
        settings['prints_per_week']=3.5
        self.assertLess(estimate(pages, settings=settings)['rolls_per_year'],1)

    def test_invalid_values_and_geometry_are_rejected(self):
        for changes in ({'roll_length_m':0},{'roll_length_m':float('nan')},{'waste_percent':100},
                        {'columns':True},{'columns':80},{'columns':30.5},{'printable_pixels':575},
                        {'dpi':float('inf')},{'paper_width_mm':40},{'preset':[]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                paper.validate(dict(paper.DEFAULT,**changes))

    def test_paper_settings_save_and_restart_guard(self):
        app = Flask(__name__)
        app.secret_key='test'
        app.add_url_rule('/', 'index', lambda:'ok')
        app.add_url_rule('/preview/generate', 'generate', lambda:'generated', methods=['POST'])
        register(app, lambda f:f)
        with TemporaryDirectory() as folder, patch.object(paper,'FILE',Path(folder)/'paper.json'):
            client=app.test_client()
            data=dict(paper.DEFAULT,roll_length_m='65',preset='58mm')
            response=client.post('/settings/printer-paper',data=data)
            self.assertEqual(response.status_code,302)
            self.assertEqual(paper.load()['columns'],30)
            self.assertEqual(paper.load()['roll_length_m'],65)
            self.assertEqual(client.post('/preview/generate').status_code,302)
            data['preset']='80mm'
            client.post('/settings/printer-paper',data=data)
            self.assertEqual(client.post('/preview/generate').data,b'generated')
            before=paper.FILE.read_bytes()
            data['roll_length_m']='nan'
            client.post('/settings/printer-paper',data=data)
            self.assertEqual(paper.FILE.read_bytes(),before)

    def test_saved_wide_image_scales_to_narrow_printer(self):
        from receipt.printer_layout import ContentPrinter
        from types import SimpleNamespace
        from io import BytesIO
        from PIL import Image
        from unittest.mock import Mock
        device=Mock()
        device.profile=SimpleNamespace(profile_data={'media':{'width':{'pixels':384}}})
        stream=BytesIO()
        Image.new('1',(576,120),1).save(stream,format='PNG')
        stream.seek(0)
        ContentPrinter(device,columns=30).image(stream)
        sent=device.image.call_args.args[0]
        self.assertEqual(Image.open(sent).size,(384,80))
        self.assertEqual(stream.tell(),0)

    def test_standard_80mm_upgrades_to_48_but_custom_46_is_preserved(self):
        legacy = dict(paper.DEFAULT, preset='80mm', columns=46)
        upgraded = paper.validate(legacy)
        self.assertEqual(upgraded['columns'],48)
        self.assertEqual(legacy['columns'],46)  # No mutation during a read.
        self.assertEqual(paper.validate(dict(legacy,preset='custom'))['columns'],46)
        self.assertEqual(paper.validate(dict(paper.DEFAULT,**paper.PRESETS['58mm'],preset='58mm'))['columns'],30)

    def test_fit_preserves_indent_and_values_and_reflows_rules(self):
        value=fit_text('  A very long account description with £50,000.00\n'+'-'*46+'\n',30)
        self.assertIn('£50,000.00',value)
        self.assertTrue(all(len(line)<=30 for line in value.splitlines()))
        self.assertEqual(value.splitlines()[-1],'-'*30)

    def test_narrow_profile_renders_weather_and_both_finance_modes(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'paper.json'
            path.write_text(json.dumps(dict(paper.DEFAULT,**paper.PRESETS['58mm'],preset='58mm')))
            script='''
import json
from tools.receipt_visual_fixture import weather_capture, full_capture
from receipt.profile import COLUMNS, PRINTABLE_PIXELS, web_context
from finance.test_receipt import build, receipt
from decimal import Decimal
from datetime import date
from receipt.printer_layout import ContentPrinter
from escpos.printer import Dummy
from io import BytesIO
from PIL import Image
text,images=weather_capture()
assert COLUMNS==30 and PRINTABLE_PIXELS==384
assert all(len(line)<=30 for line in text.splitlines()),text
assert all(word in text for word in ('Maximum','Minimum','Sunrise','Sunset','Temp','Feels','Hum'))
assert '23:00' in text
for image in images:
 import base64
 assert Image.open(BytesIO(base64.b64decode(image.split(',',1)[1]))).width==384
source={'valid':True,'cash':Decimal(2000),'buffer':Decimal(1000),'daily':Decimal(10),'events':[],'warnings':[],'amex':{'balance':Decimal(0),'scheduled':False,'full_reserved':False}}
result=build(source,{'salary':'3000','other_income':'0','start':'2026-10-11','months':'2','strategy':'amex_first','save_all':'on'},date(2026,10,11))
for detail in ('compact','detailed'):
 report=receipt(result,date(2026,10,11),detail=detail)
 assert all(len(row)<=30 for row in report.splitlines()),report
assert web_context()['receipt_paper_width']==58
print(json.dumps({'columns':COLUMNS,'rows':len(text.splitlines())}))
'''
            result=subprocess.run([sys.executable,'-c',script],cwd=ROOT,env={**os.environ,'RECEIPT_PAPER_SETTINGS':str(path)},capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout)['columns'],30)
            path.write_text(json.dumps(dict(paper.DEFAULT,preset='custom',columns=20)))
            narrow="from tools.receipt_visual_fixture import weather_capture; t,_=weather_capture(); assert all(len(r)<=20 for r in t.splitlines()); assert '23:00' in t"
            result=subprocess.run([sys.executable,'-c',narrow],cwd=ROOT,env={**os.environ,'RECEIPT_PAPER_SETTINGS':str(path)},capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)

