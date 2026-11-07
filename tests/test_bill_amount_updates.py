from datetime import date
import importlib
import unittest
from unittest.mock import patch

from finance.projection import payment_schedule
from finance.yearly_subscriptions import annual_subscription_rows
from services import subscriptions


TODAY = date(2026, 11, 7)
BILL = {"name": "Energy", "match": ["energy co"], "category": "bill", "amount": 50, "due_day": 8}
ANNUAL = {"name": "Annual service", "match": ["annual service"], "amount": 120,
          "renewal_date": "2025-11-08"}


def payment(amount, description="Energy Co", on="2026-11-06", **fields):
    return {"amount": amount, "merchant_name": description, "date": on, **fields}


def status(items, transactions, yearly=()):
    with patch("services.private_config.load", return_value={}):
        pipeline = importlib.import_module("services.live_pipeline")
    return pipeline.build_subscription_status(
        transactions, subscriptions_data={"monthly": items, "yearly": yearly}, finance_settings={}, today=TODAY
    )["monthly"]


class BillAmountUpdatesTests(unittest.TestCase):
    def test_higher_bill_is_paid_and_next_month_uses_matched_amount(self):
        transactions = [payment(-65), payment(80, transaction_type="CREDIT"),
                        payment(-77, status="PENDING"), payment(-70, on="2026-11-08")]
        rows = status([BILL], transactions)
        row = rows[0]
        self.assertTrue(row["paid"])
        self.assertEqual(row["bank_match_index"], 0)
        self.assertEqual(row["expected_amount"], 50)
        self.assertEqual(row["amount"], 65)
        self.assertEqual(BILL["amount"], 50)
        events, _, _ = payment_schedule(rows, [], transactions, {}, TODAY, horizon=40)
        self.assertEqual([(event["date"], event["amount"]) for event in events],
                         [(date(2026, 12, 8), 65)])

    def test_higher_same_merchant_purchase_does_not_replace_exact_bill(self):
        rows = status([BILL], [payment(-65), payment(-50)])
        self.assertEqual(rows[0]["bank_match_index"], 1)
        self.assertEqual(rows[0]["amount"], 50)

    def test_ambiguous_late_or_repayment_debits_remain_unverified(self):
        for bill, transactions in [
            (BILL, [payment(-65), payment(-70)]),
            (dict(BILL, due_day=24), [payment(-65)]),
            (dict(BILL, category="repayment"), [payment(-65)]),
        ]:
            with self.subTest(bill=bill, transactions=transactions):
                self.assertFalse(status([bill], transactions)[0]["paid"])
        self.assertFalse(any(row["paid"] for row in status(
            [BILL, dict(BILL, name="Another energy bill", amount=45)], [payment(-65)]
        )))

    def test_higher_annual_renewal_is_not_reserved_again(self):
        transactions = [payment(-145, "Annual Service")]
        row = annual_subscription_rows([ANNUAL], transactions, TODAY)[0]
        self.assertEqual(row["bank_paid_date"], date(2026, 11, 6))
        self.assertEqual(row["bank_paid_amount"], 145)
        events, _, _ = payment_schedule([], [ANNUAL], transactions, {}, TODAY, horizon=400)
        self.assertEqual([(event["date"], event["amount"]) for event in events],
                         [(date(2027, 11, 8), 145)])
        for amount, on in [(-10, "2026-11-06"), (-145, "2026-10-25")]:
            row = annual_subscription_rows([ANNUAL], [payment(amount, "Annual Service", on)], TODAY)[0]
            self.assertIsNone(row["bank_paid_date"])

    def test_annual_renewal_cannot_also_pay_a_monthly_bill(self):
        monthly = dict(BILL, name="Monthly service", match=["annual service"], amount=10)
        rows = status([monthly], [payment(-145, "Annual Service")], yearly=[ANNUAL])
        self.assertFalse(rows[0]["paid"])
        self.assertEqual(rows[0]["amount"], 10)

    def test_finance_receipt_records_change_once_and_never_rolls_back_history(self):
        data = {"monthly": [BILL.copy()], "yearly": [ANNUAL.copy()], "instalments": []}
        transactions = [payment(-65), payment(-145, "Annual Service")]
        with patch.object(subscriptions, "load_subscriptions", return_value=data), \
             patch.object(subscriptions, "save_subscriptions") as save:
            changes = subscriptions.update_subscriptions_from_transactions(transactions, today=TODAY)
            self.assertEqual([(item["old_amount"], item["new_amount"]) for item in changes],
                             [(50, 65), (120, 145)])
            self.assertEqual(subscriptions.update_subscriptions_from_transactions(transactions, today=TODAY), [])
            self.assertEqual(subscriptions.update_subscriptions_from_transactions(
                [payment(-50, on="2026-11-05")], today=TODAY), [])
        save.assert_called_once()
        self.assertEqual(data["monthly"][0]["history"], [{"date": "2026-11-06", "amount": 65}])
        self.assertEqual(data["yearly"][0]["amount"], 145)
