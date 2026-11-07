import ast
from datetime import date, datetime
from pathlib import Path
import unittest
from zoneinfo import ZoneInfo
from finance.yearly_subscriptions import annual_subscription_rows


class SubscriptionEndDateTests(unittest.TestCase):
    def test_final_month_is_included_then_excluded(self):
        source = ast.parse((Path(__file__).resolve().parents[1] / 'services/live_pipeline.py')
                           .read_text(encoding='utf-8'))
        nodes = [node for node in source.body if isinstance(node, ast.FunctionDef)
                 and node.name in {'build_subscription_status'}]
        namespace = {'date': date, 'datetime': datetime, 'ZoneInfo': ZoneInfo,
                     'annual_subscription_rows': annual_subscription_rows,
                     'load_finance_settings': lambda: {},
                     'repayment_commitments': lambda subscriptions, settings: [],
                     'inferred_netflix_commitment': lambda regular, transactions, today: None}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), '<subscriptions>', 'exec'), namespace)
        subscription = {'name': 'Broadband', 'amount': 30, 'match': ['broadband'],
                        'end_date': '2026-09-10'}
        data = {'monthly': [subscription], 'yearly': []}
        build = namespace['build_subscription_status']
        september = build([], subscriptions_data=data, finance_settings={}, today=date(2026, 9, 29))
        october = build([], subscriptions_data=data, finance_settings={}, today=date(2026, 10, 1))
        self.assertEqual([item['name'] for item in september['monthly']], ['Broadband'])
        self.assertEqual(october['monthly'], [])
        self.assertEqual(october['ended'], [subscription])
        self.assertEqual(data['monthly'], [subscription])

    def test_undated_contract_stays_active(self):
        from finance.bill_payments import monthly_contract_ended
        self.assertFalse(monthly_contract_ended({'name': 'Netflix'}, date(2026, 10, 1)))


if __name__ == '__main__':
    unittest.main()
