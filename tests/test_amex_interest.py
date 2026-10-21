from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from finance import amex_interest as interest
from storage import PrivateStateError, write_json

TODAY = date(2026, 10, 21)


def charge(**changes):
    return {'_source_provider': 'AMEX', '_source_account': 'card-one',
            'timestamp': '2026-10-20T00:00:00+01:00', 'amount': 12.34,
            'currency': 'GBP', 'transaction_type': 'DEBIT',
            'transaction_category': 'INTEREST', 'description': 'INTEREST CHARGE',
            'transaction_id': 'request-specific', **changes}


class AmexInterestTests(TestCase):
    def test_category_and_explicit_charge_descriptions(self):
        for tx in [charge(), charge(description='PURCHASE INTEREST', transaction_category='OTHER'),
                   charge(description='INTEREST CHARGE ON PURCHASES', transaction_category='OTHER'),
                   charge(description='INTEREST ON CASH ADVANCES', transaction_category='OTHER'),
                   charge(description='OTHER BANK WORDING'), charge(amount=-12.34)]:
            with self.subTest(tx=tx):
                row = next(iter(interest.detect([tx], TODAY).values()))
                self.assertEqual(row['amount'], '12.34')
                self.assertEqual(row['date'], '2026-10-20')

    def test_excludes_refunds_merchant_names_fees_invalid_values_and_other_banks(self):
        for changes in [dict(_source_provider='HSBC'), dict(_source_provider=''),
                        dict(transaction_type='CREDIT'), dict(transaction_type='REFUND'),
                        dict(description='INTEREST REFUND'), dict(description='INTEREST REVERSAL'),
                        dict(description='INTEREST WAIVED'), dict(description='NO INTEREST'),
                        dict(description='INTEREST-FREE'), dict(amount=0), dict(amount='NaN'),
                        dict(amount='Infinity'), dict(amount='bad'), dict(timestamp='invalid'),
                        dict(timestamp='2026-10-22'), dict(currency='BAD'),
                        dict(transaction_type='', amount=-2),
                        dict(transaction_category='PURCHASE', description='Special Interest Books'),
                        dict(transaction_category='FEE_CHARGE', description='LATE PAYMENT FEE'),
                        dict(transaction_category='PURCHASE', description='PAYMENT THANK YOU')]:
            with self.subTest(changes=changes):
                self.assertFalse(interest.detect([charge(**changes)], TODAY))

    def test_persistence_acknowledgement_and_id_rotation(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'alerts.json'
            first = charge(normalised_provider_transaction_id='stable')
            interest.capture([first, first], path=path, today=TODAY)
            self.assertEqual(len(interest.pending(path=path)), 1)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            ids = [row['id'] for row in interest.pending(path=path)]
            interest.capture([charge(normalised_provider_transaction_id='new', amount=5)], path=path, today=TODAY)
            interest.acknowledge(ids, path=path)
            interest.capture([{**first, 'transaction_id': 'rotated'}], path=path, today=TODAY)
            self.assertEqual(len(interest.visible([first], path=path, today=TODAY)), 1)
            interest.capture([], path=path, today=TODAY)  # Empty/failed retrieval cannot clear warnings.
            self.assertEqual(interest.pending(path=path)[0]['amount'], '5.00')
            self.assertNotIn('card-one', path.read_text())
            self.assertNotIn('request-specific', path.read_text())

    def test_fallback_id_rotation_and_multiple_cards(self):
        first = charge()
        self.assertEqual(interest.detect([first], TODAY), interest.detect([{**first, 'transaction_id': 'new'}], TODAY))
        self.assertEqual(len(interest.detect([first, first], TODAY)), 1)
        self.assertEqual(len(interest.detect([first, {**first, 'transaction_id': 'another'}], TODAY)), 2)
        self.assertEqual(len(interest.detect([first, charge(_source_account='card-two')], TODAY)), 2)

    def test_corrupt_state_is_retained_and_rejected(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'alerts.json'
            path.write_text('{broken')
            with self.assertRaises(PrivateStateError):
                interest.capture([charge()], path=path, today=TODAY)
            self.assertEqual(path.read_text(), '{broken')
            write_json(path, {'version': 1, 'charges': {'a' * 64: {'date': '2026-10-20', 'amount': 'bad', 'currency': 'GBP', 'acknowledged': False}}})
            with self.assertRaises(PrivateStateError):
                interest.pending(path=path)

    def test_backup_round_trip_and_corrupt_alert_rejection(self):
        import json
        from web_control.private_backup import export, validate, restore
        with TemporaryDirectory() as folder, TemporaryDirectory() as restored:
            root = Path(folder)
            interest.capture([charge()], path=root / 'data' / 'amex_interest_alerts.json', today=TODAY)
            raw = export(root)
            backup = validate(raw)
            restore(Path(restored), backup)
            self.assertEqual(len(interest.pending(path=Path(restored) / 'data' / 'amex_interest_alerts.json')), 1)
            backup['files']['amex_interest_alerts.json']['charges']['broken'] = {}
            with self.assertRaises(ValueError):
                validate(json.dumps(backup).encode())

    def test_receipt_warning_is_short_and_only_when_relevant(self):
        from unittest.mock import Mock
        rows = []
        printer = Mock()
        left = lambda _, text: rows.append(text)
        line = lambda *_: None
        interest.receipt_warning(printer, left, line, [])
        self.assertEqual(rows, [])
        interest.receipt_warning(printer, left, line, list(interest.detect([charge()], TODAY).values()))
        self.assertTrue(any('£12.34' in row and '20 Oct 2026' in row for row in rows))
        self.assertIn('AMEX INTEREST ALERT', ''.join(rows))

    def test_background_refresh_captures_before_review_callback(self):
        from web_control.finance_refresh import FinanceRefresh
        with TemporaryDirectory() as folder:
            root = Path(folder)
            snapshot = {'data': ([charge()], [], [], [], {'bank_data_status': 'partial'}), 'balances': {}}
            def reviewed(_):
                self.assertEqual(len(interest.pending(path=root / 'data' / 'amex_interest_alerts.json')), 1)
            manager = FinanceRefresh(root, lambda _: snapshot, on_success=reviewed)
            manager.start()
            manager.worker.join(3)
            self.assertEqual(manager.status()['state'], 'completed')

    def test_authenticated_routes_and_scoped_acknowledgement(self):
        from functools import wraps
        from flask import Flask, session
        from web_control.amex_interest import register
        app = Flask(__name__)
        app.secret_key = 'test'
        @app.get('/finance-review')
        def finance_review():
            return 'review'
        def login_required(fn):
            @wraps(fn)
            def wrapped(*args, **kwargs):
                if not session.get('authenticated'):
                    return 'login', 401
                return fn(*args, **kwargs)
            return wrapped
        register(app, login_required)
        with TemporaryDirectory() as folder, patch.object(interest, 'FILE', Path(folder) / 'alerts.json'):
            interest.capture([charge()], today=TODAY)
            client = app.test_client()
            self.assertEqual(client.get('/finance/amex-interest/status').status_code, 401)
            self.assertEqual(client.post('/finance/amex-interest/acknowledge').status_code, 401)
            with client.session_transaction() as session:
                session['authenticated'] = True
            response = client.get('/finance/amex-interest/status').get_json()
            self.assertEqual(len(response['charges']), 1)
            identifier = response['charges'][0]['id']
            self.assertEqual(client.post('/finance/amex-interest/acknowledge', data={'charge_id': identifier}).status_code, 302)
            self.assertFalse(interest.pending())
