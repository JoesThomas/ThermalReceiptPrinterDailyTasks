import unittest
from copy import deepcopy
from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from finance import reviews
from receipt import finance_details


class FinanceResultsTests(unittest.TestCase):
    def capture(self,today,transactions=None,rows=None,coverage='complete'):
        plan={'latest':date(2026,10,1),'valid':True,'end':date(2026,10,10),'received':Decimal(4500),'spent':Decimal(0),
              'buckets':[{'name':'Upcoming bills & repayments','amount':Decimal(100)},{'name':'Estimated everyday spending','amount':Decimal(200)},{'name':'Savings contribution','amount':Decimal(500)}]}
        projection={'cash':Decimal(5000),'buffer':Decimal(1000),'daily':Decimal(20),'payday':date(2026,10,11)}
        income={'month_total':Decimal(800),'recent':[{'date':date(2026,10,1),'name':'Rent','amount':Decimal(800),'category':'Rent Received'}]}
        summary={'bank_data_status':coverage,'requested_from':'2026-09-20','requested_to':today.isoformat()}
        return reviews.capture(plan,transactions or [],rows or [],income,projection,summary,None,None,today,Decimal(100))

    def test_plan_preserved_observations_deduplicated_and_savings_unknown(self):
        with TemporaryDirectory() as folder,patch.object(reviews,'FILE',Path(folder)/'reviews.json'):
            first=self.capture(date(2026,10,1))
            original=deepcopy(first['periods']['2026-10-01']['plan'])
            bill={'date':'2026-10-02','amount':-100,'description':'Bill','transaction_id':'bill'}
            coffee={'date':'2026-10-03','amount':-10,'description':'Cafe','transaction_id':'coffee'}
            self.capture(date(2026,10,3),[bill,coffee],[{'transaction':bill}])
            state=self.capture(date(2026,10,4),[bill,coffee],[{'transaction':bill}])
            period=state['periods']['2026-10-01']
            self.assertEqual(period['plan'],original)
            self.assertEqual(Decimal(period['actual']['bills']),100)
            self.assertEqual(Decimal(period['actual']['everyday']),10)
            self.assertIsNone(period['confirmed_savings'])
            self.assertTrue(reviews.period_review(state)[0]['covered'])
            # Shrinking provider windows retain previously seen aggregates.
            state=self.capture(date(2026,10,5),[coffee],[],coverage='partial')
            self.assertEqual(Decimal(state['periods']['2026-10-01']['actual']['bills']),100)

    def test_bank_rent_once_and_costs_tax_not_double_counted(self):
        with TemporaryDirectory() as folder,patch.object(reviews,'FILE',Path(folder)/'reviews.json'):
            state=self.capture(date(2026,10,1));candidate=state['rent_candidates'][0]
            property_row={'id':'111111111111','name':'Rental property'}
            reviews.add_entry(property_row,'rent','','',candidate=candidate)
            with self.assertRaises(ValueError):reviews.add_entry(property_row,'rent','','',candidate=candidate)
            for kind,amount in [('operating','100'),('repair','50'),('capital','80'),('tax','150')]:reviews.add_entry(property_row,kind,'2026-10-01',amount)
            tax={'tax':Decimal(1200),'rules':{'start':'2026-04-06','end':'2027-04-05'}}
            result=reviews.rental_performance(reviews.load(),'2026-10',tax)
            self.assertEqual(result['cash_flow'],420)
            self.assertEqual(result['after_provision'],420)
            self.assertIsNone(reviews.rental_performance(reviews.load(),'2025-10',tax)['provision'])

    def test_frozen_summary_preserves_coverage_and_assumptions(self):
        with TemporaryDirectory() as folder,patch.object(reviews,'FILE',Path(folder)/'reviews.json'):
            self.capture(date(2026,10,1),coverage='partial')
            reviews.freeze('2026-10');original=deepcopy(reviews.load()['summaries']['2026-10'])
            self.capture(date(2026,10,4))
            self.assertEqual(reviews.load()['summaries']['2026-10'],original)
            self.assertEqual(original['coverage'],'partial')
            with self.assertRaises(ValueError):reviews.freeze('2026-10')
            with self.assertRaises(ValueError):reviews.freeze('2026-09')

    def test_closed_period_retains_aggregate_without_raw_observations(self):
        with TemporaryDirectory() as folder,patch.object(reviews,'FILE',Path(folder)/'reviews.json'):
            self.capture(date(2026,10,1))
            tx={'date':'2026-10-04','amount':-10,'description':'Cafe','transaction_id':'coffee'}
            state=self.capture(date(2026,10,11),[tx])
            self.assertTrue(state['periods']['2026-10-01']['closed'])
            self.assertNotIn('observations',state['periods']['2026-10-01'])
            self.assertEqual(Decimal(state['periods']['2026-10-01']['actual']['everyday']),10)

    def test_print_detail_preview_and_failure_do_not_commit(self):
        with TemporaryDirectory() as folder,patch.object(finance_details,'FILE',Path(folder)/'details.json'):
            finance_details.reset();on=date(2026,10,5)
            self.assertTrue(finance_details.show('tax',{'amount':10},on))
            finance_details.reset() # failed job or preview: no successful commit
            self.assertTrue(finance_details.show('tax',{'amount':10},on))
            finance_details.commit()
            self.assertFalse(finance_details.show('tax',{'amount':10},on))
            self.assertTrue(finance_details.show('tax',{'amount':20},on))
            self.assertTrue(finance_details.show('tax',{'amount':10},date(2026,11,5)))
            finance_details.reset()

    def test_needs_update_and_backup_validation(self):
        rows=reviews.needs_update({'warnings':['Missing repayment date'],'payday':None},{'properties':[{'id':'111111111111','name':'Property','stale':True,'mortgage_stale':False}]},'partial',{},None)
        self.assertEqual(len(rows),4)
        from web_control.private_backup import _validate_file,OBJECT_FILES
        self.assertIn('finance_reviews.json',OBJECT_FILES)
        _validate_file('finance_reviews.json',deepcopy(reviews.DEFAULT))
        value=deepcopy(reviews.DEFAULT);value['rent_entries']=[{'id':'a'*12,'date':'2026-10-01','amount':'nan'}]
        with self.assertRaises(ValueError):_validate_file('finance_reviews.json',value)

    def test_capture_commits_details_only_for_sent_finance_path(self):
        from receipt import capture,archive
        from receipt.live_preview import VirtualPrinter
        with TemporaryDirectory() as folder:
            root=Path(folder)
            with patch.object(finance_details,'FILE',root/'details.json'),patch.object(capture,'CAPTURE_FILE',root/'printed.json'),patch.object(capture,'LIVE_PREVIEW_FILE',root/'preview.json'),patch.object(archive,'DIRECTORY',root/'archive'),patch('web_control.today_summary.snapshot_changes'):
                finance_details.reset()
                finance_details.show('tax',{'amount':10},date(2026,10,5))
                recorder=capture.RecordingPrinter(VirtualPrinter())
                recorder.text('FINANCE\n')
                recorder.save('finance',path=capture.LIVE_PREVIEW_FILE,replace=True)
                self.assertFalse(finance_details.FILE.exists())
                recorder.save('information',path=capture.CAPTURE_FILE,replace=True)
                self.assertFalse(finance_details.FILE.exists())
                recorder.save('finance',path=capture.CAPTURE_FILE,replace=True)
                self.assertTrue(finance_details.FILE.exists())
                finance_details.reset()
