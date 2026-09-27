import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from finance_trends import (
    categorise_transaction, category_trends, clean_spending_transactions,
    everyday_spending_transactions, load_rules, spending_total,
    uncategorised_merchants,
)


class FinanceCategoryTests(unittest.TestCase):
    def test_statement_merchants_group_into_useful_categories(self):
        rules = load_rules(Path('/missing/finance_categories.json'))
        examples = {
            'RENT': 'HOUSING',
            'TESCO PETROL 5386 BIRMINGHAM': 'TRANSPORT',
            'TESCO STORES 2503 BIRMINGHAM': 'FOOD',
            'AMZNMKTPLACE*NU0ZD9CE4 AMAZON.CO.UK': 'SHOPPING',
            'SCOTTISHPOWER': 'BILLS & UTILITIES',
            'THOMAS LJ&DJA CAR INSURANCE': 'INSURANCE',
            'SQ *ORIGINAL PATTYBirmingham': 'EATING OUT',
            'SQ *BOUTIQUE HAIR Harborne': 'PERSONAL CARE',
            'NETFLIX.COM 203832 LND': 'SUBSCRIPTIONS',
            'TRAINLINE.COM 744825 LONDON': 'TRANSPORT',
            'TRUCK FESTIV 12867NOTTINGHAM': 'ENTERTAINMENT',
            'SQ *LEMONWORLD Birmingham': 'EATING OUT',
            'Stir Store Birmingham': 'EATING OUT',
            'JOBGETHER.COM BRUSSELS': 'SUBSCRIPTIONS',
        }
        for merchant, expected in examples.items():
            with self.subTest(merchant=merchant):
                self.assertEqual(categorise_transaction({'description': merchant}, rules), expected)
        self.assertEqual(categorise_transaction({'description': 'PERSON NAME PAYMENT'}, rules), 'OTHER')
        self.assertEqual(categorise_transaction({'description': 'CAR RENTAL'}, rules), 'OTHER')
        self.assertEqual(categorise_transaction({'description': 'NOSTALGIA.CO.UK EDINBURGH'}, rules), 'OTHER')

    def test_private_specific_override_precedes_built_in_generic_rule(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'categories.json'
            path.write_text(json.dumps({'AMZNMKTPLACE*NU0ZD9CE4': 'HOUSEHOLD'}))
            rules = load_rules(path)
        self.assertEqual(categorise_transaction(
            {'description': 'AMZNMKTPLACE*NU0ZD9CE4 AMAZON.CO.UK'}, rules), 'HOUSEHOLD')
        self.assertEqual(categorise_transaction({'description': 'AMAZON.CO.UK'}, rules), 'SHOPPING')

    def test_unknown_merchants_are_aggregated_for_review(self):
        raw = [
            {'date': '2026-09-10', 'amount': -110, 'type': 'DEBIT',
             'description': 'PERSON NAME PAYMENT'},
            {'date': '2026-09-18', 'amount': -110, 'type': 'DEBIT',
             'description': 'PERSON NAME PAYMENT'},
            {'date': '2026-09-21', 'amount': -28.45, 'type': 'DEBIT',
             'description': 'ALDI STIRCHLEY'},
        ]
        result = uncategorised_merchants(
            clean_spending_transactions(raw), load_rules(Path('/missing/file.json')),
            as_of=date(2026, 9, 27), minimum_amount=25,
        )
        self.assertEqual(result, [{'merchant': 'PERSON NAME PAYMENT', 'amount': 220.0}])

    def test_one_off_gift_override_does_not_relabel_later_merchant_purchases(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'categories.json'
            path.write_text(json.dumps({'transactions': [{
                'date': '2026-09-18', 'amount': 22.00,
                'merchant': 'NOSTALGIA.CO.UK', 'category': 'GIFTS',
            }]}))
            rules = load_rules(path)
        base = {'description': 'NOSTALGIA.CO.UK EDINBURGH', 'amount': -22.00}
        self.assertEqual(categorise_transaction({**base, 'date': '2026-09-18'}, rules), 'GIFTS')
        self.assertEqual(categorise_transaction({**base, 'date': '2026-10-18'}, rules), 'OTHER')
        self.assertEqual(categorise_transaction({**base, 'date': '2026-09-18', 'amount': -21}, rules), 'OTHER')

    def test_rules_change_category_but_not_total_spend_or_fixed_commitments(self):
        raw = [
            {'date': '2026-09-10', 'amount': -750, 'type': 'DEBIT',
             'description': 'RENT'},
            {'date': '2026-09-23', 'amount': -71.61, 'type': 'DEBIT',
             'description': 'TESCO PETROL 5386 BIRMINGHAM'},
            {'date': '2026-09-25', 'amount': -5.99, 'type': 'DEBIT',
             'description': 'NETFLIX.COM 203832 LND'},
        ]
        cleaned = clean_spending_transactions(raw)
        self.assertEqual(spending_total(cleaned, as_of=date(2026, 9, 27)), 827.60)
        self.assertEqual(len(everyday_spending_transactions(cleaned)), 1)
        trends = category_trends(cleaned, load_rules(Path('/missing/finance_categories.json')),
                                 as_of=date(2026, 9, 27), minimum_current_spend=0)
        totals = {item['category']: item['current'] for item in trends}
        self.assertEqual(totals['HOUSING'], 750)
        self.assertEqual(totals['TRANSPORT'], 71.61)
        self.assertEqual(totals['SUBSCRIPTIONS'], 5.99)

if __name__ == '__main__':
    unittest.main()
