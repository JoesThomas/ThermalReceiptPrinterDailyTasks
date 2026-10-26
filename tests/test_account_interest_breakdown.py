"""Interest disclosure reconciles by account without changing forecast balances."""
from datetime import date
from decimal import Decimal as D
from unittest import TestCase
from test_amex_reserve_priority import base, values, TODAY, ZERO
from finance.scenario_plan import build
from finance.money import rounded
from finance.test_receipt import receipt
from finance.test_scenarios import snapshot


def source():
    data=base(cash='5000',card='0',daily=ZERO,cash_gap='0')
    data['events']=[]
    data['savings_accounts']=[
        dict(id=key,name=name,type=kind,kind='savings',balance=balance,share=ZERO,target=ZERO,date=str(TODAY),interest_rate=rate,isa_contributions=None)
        for key,name,kind,balance,rate in [
            ('a','Savings A','savings',D(1000),D('3.5')),
            ('b','Cash ISA B','cash_isa',D(2000),D('4.0')),
            ('c','Investments','stocks_isa',D(100),D('7')),
            ('d','Zero rate','savings',D(100),ZERO),
            ('e','Unknown balance','savings',None,D('3.5'))]]
    return data


def run(data=None, **changes):
    form=values(salary='0',other_income='0',months='2');form.update(changes)
    return build(data or source(),form,TODAY)


class AccountInterestBreakdownTests(TestCase):
    def test_individual_monthly_interest_uses_each_rate_and_is_included_once(self):
        result=run();months=result['forecast']['monthly_balances']
        first={a['name']:a for a in months[0]['accounts']}
        second={a['name']:a for a in months[1]['accounts']}
        for name,balance,rate in [('Savings A',D(1000),D('3.5')),('Cash ISA B',D(2000),D('4'))]:
            factor=(1+rate/100)**(D(1)/365)
            interest_oct=rounded(balance*(factor**6-1))
            interest_nov=rounded(balance*(factor**36-1))-interest_oct
            self.assertEqual(first[name]['interest_month'],interest_oct)
            self.assertEqual(second[name]['interest_month'],interest_nov)
            self.assertEqual(second[name]['interest_to_date'],interest_oct+interest_nov)
            self.assertEqual(second[name]['balance'],balance+interest_oct+interest_nov)
        self.assertNotIn('interest_month',first['Investments'])
        self.assertEqual(first['Zero rate']['interest_month'],0)
        self.assertIsNone(first['Unknown balance']['interest_month'])

    def test_delayed_payday_excludes_prior_month_from_this_month_interest(self):
        result=run(start='2026-11-01',months='1')
        row=next(a for a in result['forecast']['monthly_balances'][0]['accounts'] if a['name']=='Savings A')
        factor=(1+D('3.5')/100)**(D(1)/365)
        self.assertEqual(row['interest_to_date'],rounded(D(1000)*(factor**36-1)))
        self.assertEqual(row['interest_month'],row['interest_to_date']-rounded(D(1000)*(factor**6-1)))
        total=next(a for a in result['account_plan']['accounts'] if a['id']=='a')['estimated_interest']
        self.assertEqual(row['interest_to_date'],total)

    def test_new_contribution_only_earns_interest_after_its_date(self):
        data=source()
        data['events']=[dict(name='Savings A',date=date(2026,11,15),amount=D(100),savings_account='a',category='savings')]
        result=run(data)
        month=result['forecast']['monthly_balances'][1]
        row=next(a for a in month['accounts'] if a['name']=='Savings A')
        factor=(1+D('3.5')/100)**(D(1)/365)
        total=rounded(D(1000)*(factor**36-1)+D(100)*(factor**15-1))
        self.assertEqual(row['interest_to_date'],total)
        self.assertEqual(row['balance'],D(1100)+total)
        self.assertEqual(row['interest_month'],total-rounded(D(1000)*(factor**6-1)))

    def test_receipts_and_serialized_web_details_show_individual_interest(self):
        result=run()
        for detail in ('compact','detailed'):
            text=receipt(result,TODAY,detail=detail)
            self.assertIn('Interest this month',text)
            end=text.split('BALANCES AT FORECAST END',1)[1]
            self.assertIn('Interest over forecast',end)
            self.assertLess(end.index('Savings A'),end.index('Interest over forecast'))
        data=snapshot(result,TODAY)
        row=next(a for a in data['monthly_balances'][0]['accounts'] if a['name']=='Savings A')
        self.assertEqual(row['interest_month'],'£0.57')
        for account in data['accounts']:
            original=next(r for r in result['account_plan']['accounts'] if r['name']==account['name'])
            if account['name']=='Investments':
                self.assertIsNone(account['estimated_interest'])
            elif account['name']=='Unknown balance':
                self.assertEqual(account['estimated_interest'],'Unavailable')
            else:
                self.assertEqual(D(account['estimated_interest'].replace('£','').replace(',','')),original['estimated_interest'])
