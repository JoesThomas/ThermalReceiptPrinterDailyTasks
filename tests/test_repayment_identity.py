from datetime import date
from decimal import Decimal
from unittest import TestCase
from finance.repayment_identity import unique_repayments
from finance.receipt import calculate_debt_and_payday
from finance.commitments import repayment_commitments


class RepaymentIdentityTests(TestCase):
    def test_generic_amazon_aliases_do_not_duplicate_debt_or_monthly_totals(self):
        products = [{'name': 'Instrument plan', 'amount': 120, 'remaining_balance': 1200},
                    {'name': 'Tool plan', 'amount': 40, 'remaining_balance': 160}]
        aliases = [{'name': 'Amazon Monthly Payments (2026-09-21)', 'monthly_payment': 120, 'balance': 1200},
                   {'name': 'Amazon Monthly Payments 2026-09-18', 'monthly_payment': 40, 'balance': 160}]
        settings = {'debts': aliases}
        snapshot = calculate_debt_and_payday(2000, 50, products, settings, date(2026, 10, 10))
        self.assertEqual([row['name'] for row in snapshot['debts']], ['AMEX', 'Instrument plan', 'Tool plan'])
        self.assertEqual(snapshot['short_term'], Decimal(1410))
        payments = repayment_commitments({'instalments': products}, settings)
        self.assertEqual(sum(row['amount'] for row in payments), 160)
        self.assertEqual(unique_repayments(aliases + products), products)

    def test_explicit_alias_and_punctuation_identify_same_debt(self):
        plans = [{'name': 'Laptop plan', 'monthly_commitment_name': 'Laptop payment',
                  'remaining_balance': 100, 'amount': 25}]
        debts = [{'name': 'LAPTOP-PAYMENT', 'balance': 900, 'monthly_payment': 25}]
        self.assertEqual(unique_repayments(plans, debts), plans)

    def test_matching_amount_alone_does_not_remove_a_debt(self):
        plans = [{'name': 'Product plan', 'amount': 40, 'remaining_balance': 160}]
        other = [{'name': 'Amazon Monthly Payments', 'monthly_payment': 40, 'balance': 200},
                 {'name': 'Separate loan', 'monthly_payment': 40, 'balance': 160}]
        self.assertEqual(unique_repayments(plans, other), plans + other)

    def test_ambiguous_generic_alias_is_kept_and_distinct_generic_plans_survive(self):
        plans = [{'name': name, 'amount': 40, 'remaining_balance': 160} for name in ('First product', 'Second product')]
        generic = {'name': 'Amazon Monthly Payments', 'amount': 40, 'remaining_balance': 160}
        self.assertEqual(len(unique_repayments(plans + [generic])), 3)
        different = dict(generic, amount=120, remaining_balance=1200)
        self.assertEqual(unique_repayments([generic, different]), [generic, different])
        snapshot = calculate_debt_and_payday(2000, 0, [generic, different], {}, date(2026, 10, 10))
        self.assertEqual(snapshot['short_term'], Decimal(1360))
        self.assertEqual(len(repayment_commitments({'instalments': [generic, different]}, {})), 2)
