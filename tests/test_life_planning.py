from datetime import date, timedelta, datetime
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from werkzeug.datastructures import MultiDict
from organiser import records
from finance import annual_funds as funds, rental_tax
from storage import write_json

TODAY = date(2026, 10, 22)


class LifePlanningTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for module, filename in [(funds, 'funds.json'), (records, 'organiser.json'), (rental_tax, 'tax.json')]:
            patcher = patch.object(module, 'FILE', self.root / filename)
            patcher.start()
            self.addCleanup(patcher.stop)

    def settings(self):
        value = funds.defaults()
        value.update(enabled=True, tax_source='manual', tax_due=str(TODAY), tax_checked=str(TODAY), tax_target='500.00')
        value['pots'] = [{'id': 'a'*24, 'name': 'Insurance', 'target': '300.00', 'balance': '0.00', 'due': str(TODAY),
                          'inside': False, 'priority': 1, 'destination': 'Insurance savings'}]
        return value

    def test_tax_is_first_and_funding_has_no_salary_requirement(self):
        value = self.settings()
        result = funds.plan(D(600), TODAY, value)
        self.assertEqual([r['name'] for r in result['rows']], ['Tax reserve', 'Insurance'])
        self.assertEqual([r['suggested'] for r in result['rows']], [500, 100])
        self.assertEqual(result['rows'][1]['shortfall'], 200)
        self.assertEqual(result['total'], 600)
        self.assertEqual(funds.plan(D(0), TODAY, value, valid=False)['total'], 0)

    def test_legacy_tax_reserve_is_merged_not_added_and_paid_tax_reduces_target(self):
        value = self.settings()
        value.update(tax_balance='100.00', tax_paid='50.00')
        tax = dict(rental_tax.DEFAULT, reserved='200.00')
        write_json(rental_tax.FILE, tax)
        write_json(funds.FILE, value)
        row = funds.pots(today=TODAY)[0]
        self.assertEqual(row['balance'], 200)
        self.assertEqual(row['target'], 450)
        self.assertEqual(funds.protected_reserve(), 200)
        result = funds.plan(D(1000), TODAY)
        funds.complete(result['rows'][0]['transfer_id'], 'tax', result['rows'][0]['suggested'], today=TODAY)
        self.assertEqual(funds.pots(today=TODAY)[0]['balance'], 450)

    def test_completing_transfer_once_and_monthly_recommendations_do_not_repeat(self):
        value = self.settings()
        write_json(funds.FILE, value)
        result = funds.plan(D(700), TODAY)
        tax = result['rows'][0]
        funds.complete(tax['transfer_id'], 'tax', tax['suggested'], today=TODAY)
        funds.complete(tax['transfer_id'], 'tax', tax['suggested'], today=TODAY)
        self.assertEqual(len(funds.store().read()['transfers']), 1)
        self.assertEqual(funds.plan(D(700), TODAY)['rows'][0]['suggested'], 0)
        annual = funds.plan(D(700), TODAY)['rows'][1]
        funds.complete(annual['transfer_id'], annual['id'], annual['suggested'], today=TODAY)
        # Virtual tax earmark + pending external bank movement are each protected once.
        self.assertEqual(funds.protected_reserve(), 800)
        transactions = [{'amount': -300, 'date': str(TODAY), 'transaction_type': 'DEBIT', 'transaction_id': 'posted1'}]
        candidate = funds.bank_candidates(transactions)[0]
        funds.match(annual['transfer_id'], candidate['key'], transactions)
        self.assertEqual(funds.protected_reserve(), 500)
        with self.assertRaises(ValueError):
            funds.match(annual['transfer_id'], candidate['key'], transactions)

    def test_new_funds_use_existing_available_cash_without_salary(self):
        from finance.projection import build_projection
        from finance.salary_plan import build
        value = self.settings()
        write_json(funds.FILE, value)
        settings = {'hsbc_emergency_reserve': 1000, 'runway_daily_spend': 0}
        balances = {'HSBC': {'available': 1800}, 'MONZO': {'available': 0}}
        projection = build_projection(balances, [], [], [], settings, TODAY)
        allocation = build([], [], balances, projection, settings, None, TODAY)
        self.assertFalse(allocation['valid'])  # No salary allocation invented.
        self.assertTrue(allocation['fund_plan']['valid'])
        self.assertEqual(allocation['fund_plan']['total'], 800)

    def test_existing_salary_allocations_still_add_up_after_fund_priority(self):
        from finance.projection import build_projection
        from finance.salary_plan import build
        value = self.settings()
        write_json(funds.FILE, value)
        settings = {'hsbc_emergency_reserve': 1000, 'runway_daily_spend': 0, 'salary_savings_target': 1000, 'next_payday': '2026-11-01'}
        balances = {'HSBC': {'available': 2200}, 'MONZO': {'available': 0}}
        projection = build_projection(balances, [], [], [], settings, TODAY)
        allocation = build([{'date': TODAY, 'amount': 2200}], [], balances, projection, settings, None, TODAY)
        self.assertEqual(sum(b['amount'] for b in allocation['buckets']), allocation['available'])
        self.assertEqual(allocation['planned_savings'], 400)
        self.assertEqual(allocation['suggested_savings'], 400)

    def test_organiser_lifecycle_and_sunday_lookahead(self):
        records.save_item(MultiDict({'kind':'job', 'title':'Interview preparation', 'notes':'Prepare examples', 'due':str(TODAY+timedelta(days=2))}))
        row = records.store().read()['items'][0]
        self.assertFalse(records.receipt_lines(today=TODAY))
        sunday = date(2026, 10, 25)
        self.assertTrue(any('Interview preparation' in line for line in records.receipt_lines(today=sunday)))
        records.update(row['id'], 'done')
        self.assertFalse(records.receipt_lines(today=sunday))
        records.update(row['id'], 'reopen')
        records.update(row['id'], 'defer', str(sunday+timedelta(days=20)))
        self.assertFalse(any('Interview preparation' in line for line in records.receipt_lines(today=sunday)))
        records.update(row['id'], 'delete')
        self.assertEqual(records.store().read()['items'], [])

    def test_overlap_nonadjacent_events_and_travel_buffer(self):
        def event(title, start, end, location):
            return {'title': title, 'start_dt': datetime.fromisoformat(f'{TODAY}T{start}:00+01:00'),
                    'end_dt': datetime.fromisoformat(f'{TODAY}T{end}:00+01:00'), 'location': location}
        events = [event('Long', '09:00', '12:00', 'A'), event('Short', '09:30', '09:45', 'B'), event('Later', '11:00', '11:30', 'B')]
        warnings = records.clashes(events, today=TODAY)
        self.assertTrue(any('Long / Later' in w for w in warnings))
        events = [event('First', '09:00', '10:00', 'A'), event('Second', '10:10', '11:00', 'B')]
        self.assertTrue(any('10 minutes' in w for w in records.clashes(events, today=TODAY)))
        events[0].pop('end_dt')
        self.assertFalse(records.clashes(events, today=TODAY))

    def test_linked_bill_and_included_cash_pot_reserve_the_same_money_once(self):
        from finance.projection import build_projection
        from finance.salary_plan import build
        value = self.settings()
        value['tax_enabled'] = False
        value['pots'][0].update(inside=True, balance='300.00', bill_name='Insurance renewal')
        write_json(funds.FILE, value)
        settings = {'hsbc_emergency_reserve': 1000, 'runway_daily_spend': 0, 'next_payday': '2026-10-30', 'salary_savings_target': 1000}
        balances = {'HSBC': {'available': 2000}, 'MONZO': {'available': 0}}
        monthly = [{'name': 'Insurance renewal', 'amount': 300, 'due_date': '2026-10-25'}]
        projection = build_projection(balances, [], monthly, [], settings, TODAY, horizon=30)
        self.assertEqual(projection['buffer'], 1000)
        self.assertEqual(projection['safe_before_payday'], 700)
        allocation = build([{'date': TODAY, 'amount': 2000}], [], balances, projection, settings, None, TODAY)
        self.assertEqual(allocation['fund_plan']['total'], 0)
        self.assertTrue(allocation['fund_plan']['rows'][0]['covered_by_bill'])
        self.assertEqual(allocation['suggested_savings'], 700)
        monthly[0]['due_date'] = '2026-11-25'
        projection = build_projection(balances, [], monthly, [], settings, TODAY, horizon=60)
        self.assertEqual(projection['safe_before_payday'], 700)
        allocation = build([], [], balances, projection, settings, None, TODAY)
        self.assertEqual(allocation['bills_cost'], 300)

    def test_general_backup_restores_plans_without_document_contents(self):
        import json
        from web_control.private_backup import export, validate, restore
        value = self.settings()
        write_json(self.root / 'data' / 'annual_funds.json', value)
        write_json(self.root / 'data' / 'organiser.json', {'version':1,'travel_buffer':30,'items':[]})
        private = self.root / 'data' / 'document_vault'
        private.mkdir()
        (private / 'index.enc').write_bytes(b'ENCRYPTED DOCUMENT CONTENTS')
        raw = export(self.root)
        self.assertNotIn(b'ENCRYPTED DOCUMENT CONTENTS', raw)
        backup = validate(raw)
        with TemporaryDirectory() as other:
            restore(Path(other), backup)
            self.assertTrue(json.loads((Path(other) / 'data' / 'annual_funds.json').read_text())['enabled'])
