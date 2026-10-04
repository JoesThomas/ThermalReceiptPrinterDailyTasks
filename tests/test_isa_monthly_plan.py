import unittest
from datetime import date
from decimal import Decimal
from finance.savings_goals import monthly_plan


class MonthlyPlanTests(unittest.TestCase):
    def test_full_year_and_rounding(self):
        plan=monthly_plan(Decimal('20000'),2026,date(2026,4,6))
        self.assertEqual(plan['count'],12)
        self.assertEqual(plan['amount'],Decimal('1666.67'))
        self.assertEqual(plan['final_amount'],Decimal('1666.63'))
        self.assertEqual(sum(a for _,a in plan['payments']),Decimal('20000'))

    def test_five_payments_and_contributions(self):
        plan=monthly_plan(Decimal('15000'),2026,date(2026,11,6))
        self.assertEqual(plan['count'],5)
        self.assertEqual(plan['amount'],Decimal('3000'))
        self.assertEqual(monthly_plan(Decimal('12000'),2026,date(2026,12,6),'2026-11-06')['amount'],Decimal('3000'))

    def test_month_end_anchor(self):
        plan=monthly_plan(Decimal('1000'),2026,date(2027,1,31),'2026-05-31')
        self.assertEqual(plan['dates'],[date(2027,1,31),date(2027,2,28),date(2027,3,31)])

    def test_deadline_unknown_used_and_expired(self):
        self.assertEqual(monthly_plan(Decimal('10'),2026,date(2027,4,5))['count'],1)
        self.assertIsNone(monthly_plan(Decimal('10'),2026,date(2027,4,6))['amount'])
        self.assertIsNone(monthly_plan(None,2026,date(2026,10,4))['amount'])
        self.assertEqual(monthly_plan(Decimal('0'),2026,date(2026,10,4))['amount'],0)
        plan=monthly_plan(Decimal('0.01'),2026,date(2026,4,6))
        self.assertEqual(sum(a for _,a in plan['payments']),Decimal('0.01'))
