import ast
import re
import unittest
from datetime import date,datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from actions.delivery_summary import references,summary_lines,identity

class DeliverySummaryTests(unittest.TestCase):
    def test_group_notices_and_keep_separate_orders(self):
        notices=[dict(carrier='AMAZON',event_title='Arriving: Example item',delivery_date='2026-10-02',**references('Arriving: Example item','Order 123-1234567-1234567')),
                 dict(carrier='AMAZON',event_title='Arriving: Example item',delivery_date='2026-10-02',**references('Arriving: Example item','Order 123-7654321-7654321'))]
        self.assertNotEqual(identity(notices[0]),identity(notices[1]))
        lines=summary_lines(notices+notices,lambda r:r['carrier'],lambda r:'Expected tomorrow')
        self.assertEqual(lines.count('AMAZON / 2 notices'),1)
        self.assertEqual(lines.count('Expected tomorrow'),1)
        self.assertTrue('...234567' in ' '.join(lines))
        self.assertTrue(all(len(line)<=40 for line in lines))
    def test_tracking_updates_and_split_order(self):
        first=dict(carrier='AMAZON',**references('Dispatched','Tracking number TBA123456789 Order 123-1234567-1234567'))
        second=dict(carrier='AMAZON',**references('Arriving today','Tracking number TBA123456789 Order 123-1234567-1234567'))
        third=dict(carrier='AMAZON',**references('Second parcel','Tracking number TBA987654321 Order 123-1234567-1234567'))
        self.assertEqual(identity(first),identity(second))
        self.assertNotEqual(identity(second),identity(third))
    def test_relative_date_uses_email_date_and_preserves_time(self):
        source=ast.parse(Path('services/live_pipeline.py').read_text())
        names=['extract_delivery_from_email','_normalise_delivery_time']
        nodes=[n for n in source.body if isinstance(n,ast.FunctionDef) and n.name in names]
        namespace=dict(re=re,datetime=datetime,date=date,timedelta=timedelta,ZoneInfo=ZoneInfo,printer_safe_text=lambda t:t)
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'<delivery>','exec'),namespace)
        delivery=namespace['extract_delivery_from_email']('Amazon arriving tomorrow','Expected tomorrow between 14:30 and 16:30',reference_date=date(2026,9,20))
        self.assertEqual(delivery['delivery_date'],date(2026,9,21))
        self.assertEqual(delivery['time_from'],'14:30')
        self.assertEqual(delivery['time_to'],'16:30')
