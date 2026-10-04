import json
import os
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch
from services import source_cache, calendar_source
from receipt import quality
from receipt.capture import RecordingPrinter
from web_control import reconciliation


class ReceiptUsabilityTests(unittest.TestCase):
    def test_cache_reuses_results_falls_back_and_keeps_source_timestamp_private(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(source_cache,'FILE',Path(folder)/'cache.json'), \
             patch('receipt.freshness.mark') as mark, patch.object(source_cache.time,'time',return_value=1000):
            collect = Mock(return_value=[{'date':date(2026,10,4),'title':'Example event'}])
            result = source_cache.get('Calendar','private-calendar-url-with-secret',collect)
            self.assertEqual(result[0]['date'],date(2026,10,4))
            source_cache.get('Calendar','private-calendar-url-with-secret',collect)
            self.assertEqual(collect.call_count,1)
            original = mark.call_args.kwargs['source_checked_at']
            self.assertEqual(mark.call_args.args[1],'cached')
            source_cache.refresh()
            collect.side_effect = TimeoutError('PRIVATE ERROR')
            source_cache.get('Calendar','private-calendar-url-with-secret',collect)
            self.assertEqual(mark.call_args.args[1],'cached after error')
            self.assertEqual(mark.call_args.kwargs['source_checked_at'],original)
            raw = source_cache.FILE.read_text()
            self.assertNotIn('secret',raw);self.assertNotIn('PRIVATE ERROR',raw)
            self.assertEqual(source_cache.FILE.stat().st_mode & 0o777,0o600)
            with patch.object(source_cache.time,'time',return_value=90000),self.assertRaises(TimeoutError):
                source_cache.get('Calendar','private-calendar-url-with-secret',collect)

    def test_cache_range_identity_and_partial_status(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(source_cache,'FILE',Path(folder)/'cache.json'),patch('receipt.freshness.mark') as mark:
            collect=Mock(return_value=([], 'partial'))
            source_cache.get('Deliveries','today',collect)
            self.assertEqual(mark.call_args.args[1],'partial')
            source_cache.get('Deliveries','tomorrow',collect)
            self.assertEqual(collect.call_count,2)

    def test_calendar_worker_preserves_all_day_and_uk_time(self):
        text='BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:one\r\nDTSTART:20261004T090000Z\r\nDTEND:20261004T100000Z\r\nSUMMARY:Example meeting\r\nLOCATION:Example place\r\nEND:VEVENT\r\nBEGIN:VEVENT\r\nUID:two\r\nDTSTART;VALUE=DATE:20261004\r\nSUMMARY:All day\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n'
        rows=calendar_source.parse(text,date(2026,10,4),0)
        self.assertEqual({row['time'] for row in rows},{'10:00-11:00','ALL DAY'})
        response=Mock();response.iter_content.return_value=[text.encode()]
        encoded=source_cache.encode(rows)
        with patch('services.api_health.observed_request',return_value=response),patch.object(calendar_source.subprocess,'run',return_value=Mock(returncode=0,stdout=json.dumps(encoded))) as worker:
            result=calendar_source.collect('https://example.invalid/private',date(2026,10,4),0)
            self.assertEqual(result,rows);self.assertEqual(worker.call_args.kwargs['timeout'],8)
            self.assertNotIn('https://example.invalid/private',worker.call_args.kwargs['input'])
            response.close.assert_called_once()

    def test_quality_detects_wide_duplicate_long_and_stale_sources(self):
        text='UPCOMING DELIVERIES\n[ ] Dispatched: Example item\n[ ] Ordered: Example item\n' + ('X'*43+'\n')*181
        rows=quality.check({'actions':text},{'Calendar':{'status':'cached','checked_at':'2020-01-01T00:00:00+00:00'}})
        messages=' '.join(row['message'] for row in rows)
        for expected in ('42 columns','Long page','duplicate','cached','24 hours'):self.assertIn(expected,messages)
        self.assertEqual(quality.check({'information':'Safe line\n'+'-'*42},{}),[])

    def test_deferred_printer_checks_before_sending_preserves_commands(self):
        device=Mock();recorder=RecordingPrinter(device,defer=True)
        recorder.set(align='left');recorder.text('Safe text\n');recorder.cut()
        self.assertEqual(device.mock_calls,[])
        with patch('receipt.quality.check',return_value=[]) as check:
            recorder.send();check.assert_called_once()
        device.text.assert_called_once_with('Safe text\n');device.cut.assert_called_once()
        self.assertEqual(recorder.operations,[])

    def test_reconciliation_saves_only_unknown_spending_and_rule_changes_category(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(reconciliation,'QUEUE',Path(folder)/'queue.json'),patch.object(reconciliation,'RULES',Path(folder)/'rules.json'):
            transactions=[{'date':'2026-10-04','description':'EXAMPLE SHOP','amount':-12},
                          {'date':'2026-10-04','description':'ALDI','amount':-10},
                          {'date':'2026-10-04','description':'Salary','amount':800,'transaction_type':'CREDIT'}]
            reconciliation.save_review(transactions,[{'item':{'name':'Example bill','amount':5},'transaction':None}],date(2026,10,4))
            saved=reconciliation.read(reconciliation.QUEUE)
            self.assertEqual(len(saved['payments']),1)
            self.assertEqual(saved['payments'][0]['merchant'],'EXAMPLE SHOP')
            self.assertEqual(saved['unmatched'][0]['name'],'Example bill')

    def test_short_test_command_is_supervised_and_does_not_run_live_collectors(self):
        import sys
        from web_control import print_job
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);lock=root/'lock';status=root/'status.json';lock.write_text('123')
            with patch.object(print_job,'ROOT',root),patch.object(print_job,'LOCK',lock),patch.object(print_job,'STATUS',status), \
                 patch.object(sys,'argv',['worker','--printer-test']),patch.object(print_job,'run_bounded',return_value=0) as run:
                self.assertEqual(print_job.main(),0)
                self.assertTrue(run.call_args.args[0][1].endswith('/web_control/printer_test_job.py'))
                self.assertNotIn('--printer-test',run.call_args.args[0])
            self.assertFalse(lock.exists())

    def test_deferred_hardware_opens_once_after_generation(self):
        from receipt.printer import DeferredPhysicalPrinter
        device=Mock();factory=Mock(return_value=device)
        deferred=DeferredPhysicalPrinter(factory);recorder=RecordingPrinter(deferred,defer=True)
        recorder.hw('init');recorder.text('Example');recorder.cut()
        factory.assert_not_called()
        deferred.open();recorder.send();deferred.close()
        factory.assert_called_once();device.hw.assert_called_once_with('init');device.close.assert_called_once()
