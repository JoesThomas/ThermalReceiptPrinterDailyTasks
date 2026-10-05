import unittest
from copy import deepcopy
from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from finance import rental_tax
from finance.salary_plan import reserves


class RentalTaxTests(unittest.TestCase):
    def plan(self, **changes):
        value = deepcopy(rental_tax.DEFAULT)
        value.update({key:'0' for key in rental_tax.FIELDS})
        value.update(enabled=True, rent='9600')
        value.update(changes)
        return value

    def test_no_other_income_and_rent_below_allowance(self):
        result = rental_tax.estimate(self.plan(), date(2026,10,5))
        self.assertEqual(result['tax'],0)
        self.assertEqual(result['profit'],9600)
        self.assertEqual(result['cash_after_tax_interest'],9600)

    def test_profit_crosses_employment_tax_band(self):
        result = rental_tax.estimate(self.plan(other_income='45000'),date(2026,10,5))
        self.assertEqual(result['tax'],Decimal('2786'))
        self.assertEqual(result['months'],7)
        self.assertEqual(result['monthly'],Decimal('398.00'))

    def test_allowance_taper_is_included(self):
        base,_=rental_tax.income_tax(Decimal('100000'))
        combined,_=rental_tax.income_tax(Decimal('109600'))
        self.assertEqual(combined-base,Decimal('5760'))

    def test_interest_is_restricted_credit_not_expense(self):
        result=rental_tax.estimate(self.plan(other_income='60000',expenses='1000',interest='3000'),date(2026,10,5))
        self.assertEqual(result['profit'],8600)
        self.assertEqual(result['relief'],600)
        self.assertEqual(result['tax'],2840)
        self.assertEqual(result['cash_after_tax_interest'],2760)

    def test_relief_cannot_create_refund_and_unused_costs_remain(self):
        result=rental_tax.estimate(self.plan(interest='3000'),date(2026,10,5))
        self.assertEqual(result['relief'],0)
        self.assertEqual(result['unused_finance'],3000)
        self.assertEqual(result['tax'],0)

    def test_allowance_replaces_expenses_and_rejects_finance_relief(self):
        result=rental_tax.estimate(self.plan(method='allowance',expenses='2000',other_income='60000'),date(2026,10,5))
        self.assertEqual(result['profit'],8600)
        self.assertEqual(result['cash_after_tax_interest'],4160)
        with self.assertRaises(ValueError): rental_tax.validate(self.plan(method='allowance',interest='1'))

    def test_loss_and_reserve_gap(self):
        result=rental_tax.estimate(self.plan(other_income='60000',losses='1000',reserved='1000'),date(2026,10,6))
        self.assertEqual(result['tax'],3440)
        self.assertEqual(result['gap'],2440)
        self.assertEqual(result['months'],6)
        self.assertEqual(result['monthly'],Decimal('406.67'))

    def test_future_rules_and_missing_inputs_are_not_guessed(self):
        self.assertIsNone(rental_tax.estimate(self.plan(),date(2027,4,6)))
        with self.assertRaises(ValueError): rental_tax.validate(self.plan(other_income=''))
        with self.assertRaises(ValueError): rental_tax.validate(self.plan(region='Scotland'))
        with self.assertRaises(ValueError): rental_tax.validate(self.plan(rent='nan'))

    def test_reserve_protection_is_opt_in_and_stacks(self):
        with TemporaryDirectory() as directory, patch.object(rental_tax,'FILE',Path(directory)/'tax.json'), patch.object(rental_tax,'uk_today',return_value=date(2026,10,5)):
            value=self.plan(other_income='60000',protect=True)
            rental_tax.store().update(lambda previous:previous.update(value))
            self.assertEqual(reserves({'hsbc_emergency_reserve':1000})['buffer'],4840)
            with patch.object(rental_tax,'uk_today',return_value=date(2027,4,6)):
                with self.assertRaises(ValueError): rental_tax.protected_reserve()
            rental_tax.store().update(lambda previous:previous.update(protect=False))
            self.assertEqual(reserves({'hsbc_emergency_reserve':1000})['buffer'],1000)

    def test_private_backup_validation(self):
        from web_control.private_backup import _validate_file,OBJECT_FILES
        self.assertIn('rental_tax.json',OBJECT_FILES)
        _validate_file('rental_tax.json',self.plan())
        with self.assertRaises(ValueError): _validate_file('rental_tax.json',self.plan(rent='-1'))
