import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from actions import checklists
from receipt.layout import OrderedPrinter, validate
from receipt.capture import RecordingPrinter, load_capture
from web_control import today_summary


class TodayDashboardTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.patches = [patch.object(checklists, 'FILE', self.root/'lists.json'),
                        patch.object(today_summary, 'CALENDAR', self.root/'calendar.json'),
                        patch.object(today_summary, 'CHANGES', self.root/'changes.json'),
                        patch('web_control.today_summary.delivery_state.checklist', return_value=[])]
        for item in self.patches: item.start()
    def tearDown(self):
        for item in reversed(self.patches): item.stop()
        self.folder.cleanup()

    def test_custom_order_preserves_page_names_in_saved_capture(self):
        recorder = RecordingPrinter(SimpleNamespace(text=lambda *a: None, set=lambda **kw: None, cut=lambda: None))
        printer = OrderedPrinter(recorder, ['actions','information','food','finance'])
        printer.begin('information'); printer.text('Weather\n'); printer.cut()
        printer.begin('actions'); printer.text('Tasks\n'); printer.cut()
        self.assertEqual(recorder.lines, [])
        printer.flush()
        with patch('receipt.archive.save'):
            path = self.root/'capture.json'
            recorder.save(path=path)
        value = load_capture(path)
        self.assertEqual(value['pages'], {'actions':'Tasks','information':'Weather'})
        self.assertEqual(value['page_order'][:2], ['actions','information'])

    def test_buffer_copies_image_before_input_closes(self):
        images=[]
        target=SimpleNamespace(set=lambda **kw:None, image=lambda data:images.append(data.read()),cut=lambda:None)
        printer=OrderedPrinter(target,['information']);printer.begin('information')
        with BytesIO(b'image') as image: printer.image(image)
        printer.cut();printer.flush()
        self.assertEqual(images,[b'image'])

    def test_layout_rejects_duplicate_pages(self):
        with self.assertRaises(ValueError): validate({'order':['actions']*4})
        self.assertEqual(validate({})['order'], ['information','actions','food','finance'])

    def test_comparison_keeps_baseline_for_unprinted_pages(self):
        checklists.update('tasks','add',title='First')
        today_summary.snapshot_changes({'actions':'Tasks'})
        self.assertFalse(today_summary.read(today_summary.CHANGES)['compared'])
        checklists.update('tasks','add',title='Second')
        today_summary.snapshot_changes({'information':'Weather'})
        self.assertEqual(today_summary.read(today_summary.CHANGES)['changes'],[])
        today_summary.snapshot_changes({'actions':'Tasks'})
        self.assertIn('New task: Second',today_summary.read(today_summary.CHANGES)['changes'])

    def test_new_paid_matches_and_changed_delivery_timing(self):
        with patch('web_control.today_summary.delivery_state.checklist',return_value=[{'id':'one','expected':'Tomorrow'}]):
            today_summary.snapshot_changes({'actions':'Tasks','finance':'PAID [BANK MATCH]\nRent £10.00\nPAID TOTAL'})
        with patch('web_control.today_summary.delivery_state.checklist',return_value=[{'id':'one','expected':'Today'}]):
            today_summary.snapshot_changes({'actions':'Tasks','finance':'PAID [BANK MATCH]\nRent £10.00\nWater £5.00\nPAID TOTAL'})
        changes=today_summary.read(today_summary.CHANGES)['changes']
        self.assertIn('Delivery timing changed: Today',changes)
        self.assertIn('New bank match: Water £5.00',changes)

    def test_calendar_dashboard_filters_today_without_network(self):
        from datetime import date
        today_summary.save_calendar([{'date':date.fromisoformat(checklists.today()),'title':'Meeting','time':'10:00','location':'Room'},
                                     {'date':'2000-01-01','title':'Old'}])
        with patch('requests.get', side_effect=AssertionError('dashboard fetched external data')):
            view=today_summary.dashboard()
        self.assertEqual([r['title'] for r in view['events']],['Meeting'])
