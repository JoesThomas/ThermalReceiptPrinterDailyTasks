"""Long-term estimates stay separate from funded dates and retain stopping rules."""
from datetime import date
from decimal import Decimal as D
from unittest import TestCase
from finance.long_term_goals import estimate
from finance.projection import occurs

START=date(2026,10,25)


def sample(rate='0'):
    row=dict(id='pot',name='Pot',type='savings',kind='savings',balance=D(0),target=D(50000),
             projected=D(10000),goal_date=None,interest_rate=D(rate),
             allocations=[dict(date=occurs(START,m),total=D(200)) for m in range(48,60)])
    forecast=dict(run_out=None,events=[],end=date(2031,10,24))
    inputs=dict(start=START,months=60,mode='replace',salary_end=None)
    return row,forecast,inputs


class LongTermGoalTests(TestCase):
    def test_final_year_pace_produces_date_beyond_five_years(self):
        row,f,i=sample()
        self.assertEqual(estimate(row,f,i),occurs(START,260))
        self.assertIsNone(row['goal_date'])
        self.assertEqual(row['projected'],10000)

    def test_recorded_interest_and_scheduled_contributions_are_included(self):
        row,f,i=sample('3.5')
        no_interest=estimate(dict(row,interest_rate=D(0)),f,i)
        self.assertLess(estimate(row,f,i),no_interest)
        f['events']=[dict(date=occurs(START,m),savings_account='pot',amount=D(25)) for m in range(48,60)]
        self.assertLess(estimate(row,f,i),estimate(row,dict(f,events=[]),i))

    def test_stopped_income_funding_shortfall_limits_and_no_contributions(self):
        row,f,i=sample()
        self.assertIsNone(estimate(row,f,dict(i,salary_end=date(2030,1,1))))
        self.assertIsNone(estimate(row,dict(f,run_out=date(2029,1,1)),i))
        self.assertIsNone(estimate(dict(row,balance_limit=D(20000)),f,i))
        self.assertIsNone(estimate(dict(row,allocations=[]),f,i))
        self.assertIsNone(estimate(row,f,dict(i,mode='lump')))
