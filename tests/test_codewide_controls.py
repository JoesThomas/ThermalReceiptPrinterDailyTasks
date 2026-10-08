import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from receipt.capture import RecordingPrinter
from receipt.live_preview import VirtualPrinter
from services import source_cache
from actions import checklists, delivery_state


class CodewideControlsTests(unittest.TestCase):
    def test_adjacent_rules_are_one_in_preview_and_hardware_operations(self):
        printer=RecordingPrinter(VirtualPrinter(),defer=True)
        printer.text('-'*42+'\n');printer.set(bold=True);printer.text('-'*42+'\n');printer.text('UPCOMING DELIVERIES\n')
        self.assertEqual(''.join(printer.lines),'-'*42+'\nUPCOMING DELIVERIES\n')
        self.assertEqual(len([op for op in printer.operations if op[0]=='text']),2)
        printer.text('-'*42+'\n');printer.text('\n');printer.text('-'*42+'\n')
        self.assertEqual(len([op for op in printer.operations if op[0]=='text']),5)

    def test_target_retry_fetches_only_target_and_keeps_other_valid_cache(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(source_cache,'FILE',Path(folder)/'cache.json'):
            source_cache.get('Weather','weather',lambda:['sun'])
            source_cache.get('UK news','news',lambda:['headline'])
            with patch.dict(os.environ,{'RECEIPT_REFRESH_SOURCE':'Weather'}):
                collector=Mock(return_value=['rain'])
                self.assertEqual(source_cache.get('Weather','weather',collector),['rain']);collector.assert_called_once()
                self.assertEqual(source_cache.get('UK news','news',lambda: self.fail('Sibling fetched')),['headline'])
                with self.assertRaises(ValueError):source_cache.get('Calendar','new',lambda:self.fail('Unrequested fetch'))

    def test_task_skip_is_not_completion_and_remove_can_be_undone(self):
        from web_control.undo import restore
        with tempfile.TemporaryDirectory() as folder,patch.object(checklists,'FILE',Path(folder)/'lists.json'),patch.object(checklists,'today',return_value='2026-10-08'):
            checklists.update('tasks','add',title='Example task')
            key=checklists.rows('tasks')[0]['id']
            before,after=checklists.update('tasks','skip',key)
            self.assertFalse(after['done']);self.assertEqual(checklists.task_text(''), '')
            restore(dict(kind='tasks',id=key,before=before,after=after))
            self.assertIn('Example task',checklists.task_text(''))
            before,after=checklists.update('tasks','delete',key)
            self.assertIsNone(after)
            restore(dict(kind='tasks',id=key,before=before,after=after))
            self.assertEqual(checklists.rows('tasks')[0]['title'],'Example task')

    def test_delivery_dismiss_survives_new_notice_without_claiming_received(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(delivery_state,'FILE',Path(folder)/'deliveries.json'):
            row={'carrier':'AMAZON','event_title':'Needles','order_ref':'123-1234567-1234567'}
            carrier=lambda row:'AMAZON';expected=lambda row:'Today'
            delivery_state.record_deliveries([row],carrier,expected)
            key=delivery_state.delivery_id(row)
            delivery_state.disposition(key,'dismiss')
            self.assertEqual(delivery_state.record_deliveries([row],carrier,expected),[])
            self.assertFalse(delivery_state.checklist()[0]['confirmed'])
            delivery_state.disposition(key,'restore')
            self.assertEqual(delivery_state.record_deliveries([row],carrier,expected),[row])

    def test_saved_preview_is_frozen_before_print_queued(self):
        from flask import Flask
        from receipt import archive
        from storage import write_json
        from web_control import receipt_controls
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=root/'data'/'preview.json'
            value=dict(pages={'information':'Saved content'},page_times={'information':'2026-10-08T08:00:00+00:00'},page_order=['information'],page_images={},freshness={})
            write_json(path,value)
            app=Flask(__name__);app.secret_key='fixture'
            app.add_url_rule('/preview','preview',lambda:'Preview')
            start=Mock(return_value=(True,''))
            receipt_controls.register(app,lambda view:view,start,root)
            with patch.object(receipt_controls,'LIVE_PREVIEW_FILE',path),patch.object(archive,'DIRECTORY',root/'archive'):
                client=app.test_client()
                self.assertEqual(client.post('/preview/print-saved').status_code,302);start.assert_not_called()
                self.assertEqual(client.post('/preview/print-saved',data={'confirm_saved':'on','page':'all'}).status_code,302)
                identifier=start.call_args.args[0][1]
                self.assertEqual(archive.load(identifier)['pages']['information'],'Saved content')
                write_json(path,{**value,'pages':{'information':'New content'}})
                self.assertEqual(archive.load(identifier)['pages']['information'],'Saved content')

    def test_partial_preview_preserves_other_pages_and_original_order(self):
        from receipt import capture
        from storage import write_json
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'preview.json'
            write_json(path,dict(pages={'information':'Old info','actions':'Old actions'},page_times={'information':'2026-10-07T08:00:00+00:00','actions':'2026-10-07T08:00:00+00:00'},page_order=list(capture.PAGE_NAMES),page_images={},freshness={}))
            printer=RecordingPrinter(VirtualPrinter(),defer=True);printer.text('New actions');printer.capture_order=['actions']
            with patch('receipt.archive.save'),patch('web_control.today_summary.snapshot_changes'):
                printer.save('actions',path=path,replace=False)
            saved=capture.load_capture(path)
            self.assertEqual(saved['pages'],{'information':'Old info','actions':'New actions'})
            self.assertEqual(saved['page_order'],list(capture.PAGE_NAMES))
