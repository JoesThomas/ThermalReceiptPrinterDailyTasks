import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from actions import delivery_state as state
from actions.delivery_summary import references, summary_lines


def notice(prefix, item='Example item', order='123-1234567-1234567'):
    title = prefix + ': ' + repr(item)
    return dict(carrier='AMAZON', event_title=title, delivery_date='2026-10-02',
                **references(title, 'Order ' + order))


class DeliveryChecklistTests(unittest.TestCase):
    def test_status_updates_combine_and_receipt_has_tick_boxes(self):
        rows = [notice('Ordered'), notice('Dispatched'), notice('Dispatched', 'Second item')]
        lines = summary_lines(rows, lambda r: r['carrier'], lambda r: 'Expected today')
        self.assertEqual(lines[0], 'AMAZON / 2 items')
        self.assertEqual(sum('[ ]' in line for line in lines), 2)
        self.assertNotIn('Ordered:', '\n'.join(lines))
        self.assertNotIn('Ref', '\n'.join(lines))
        self.assertTrue(all(len(line) <= 40 for line in lines))

    def test_confirm_hide_future_notices_and_undo(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(state, 'FILE', Path(folder) / 'state.json'):
            rows = state.record_deliveries([notice('Ordered')], lambda r: r['carrier'], lambda r: 'Expected today')
            key = state.delivery_id(rows[0])
            self.assertTrue(state.confirm_delivery(key, True))
            self.assertEqual(state.record_deliveries([notice('Dispatched')], lambda r: r['carrier'], lambda r: 'Expected today'), [])
            self.assertTrue(state.checklist()[0]['confirmed'])
            self.assertTrue(state.confirm_delivery(key, False))
            self.assertEqual(len(state.record_deliveries([notice('Dispatched')], lambda r: r['carrier'], lambda r: 'Expected today')), 1)
            self.assertFalse(state.confirm_delivery('unknown', True))

    def test_different_orders_and_tracking_stay_separate(self):
        first = notice('Dispatched')
        second = notice('Dispatched', order='123-7654321-7654321')
        self.assertNotEqual(state.delivery_id(first), state.delivery_id(second))
        second['order_ref'] = first['order_ref']
        first['tracking_ref'] = 'TBA123456789'
        second['tracking_ref'] = 'TBA987654321'
        self.assertNotEqual(state.delivery_id(first), state.delivery_id(second))

    def test_web_checkbox_roundtrip_and_authentication(self):
        try:
            from flask import Flask
        except ImportError:
            self.skipTest('Flask required')
        from web_control.delivery_tools import register
        from functools import wraps
        from flask import abort, session
        def auth(fn):
            @wraps(fn)
            def wrapped(*args, **kwargs):
                if not session.get('authenticated'):
                    abort(401)
                return fn(*args, **kwargs)
            return wrapped
        app = Flask(__name__)
        app.secret_key = 'test'
        register(app, auth)
        with tempfile.TemporaryDirectory() as folder, patch.object(state, 'FILE', Path(folder) / 'state.json'), app.test_client() as client:
            row = notice('Ordered')
            state.record_deliveries([row], lambda r: r['carrier'], lambda r: 'Expected today')
            key = state.delivery_id(row)
            self.assertEqual(client.post('/deliveries/confirm').status_code, 401)
            with client.session_transaction() as session:
                session['authenticated'] = True
            from werkzeug.datastructures import MultiDict
            response = client.post('/deliveries/confirm', data=MultiDict([('id', key), ('confirmed', '0'), ('confirmed', '1')]))
            self.assertEqual(response.status_code, 302)
            self.assertTrue(state.checklist()[0]['confirmed'])
            client.post('/deliveries/confirm', data={'id': key, 'confirmed': '0'})
            self.assertFalse(state.checklist()[0]['confirmed'])
