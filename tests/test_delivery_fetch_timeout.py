import ast
import contextlib
import imaplib
import io
from pathlib import Path
import unittest
from unittest.mock import Mock, patch


class DeliveryFetchTimeoutTests(unittest.TestCase):
    def test_stalled_login_returns_fallback_and_closes_mailbox(self):
        source = ast.parse(Path('services/live_pipeline.py').read_text())
        function = next(node for node in source.body if isinstance(node, ast.FunctionDef)
                        and node.name == 'get_gmail_delivery_emails')
        namespace = {'imaplib': imaplib, 'GMAIL_ADDRESS': 'test@example.invalid',
                     'GMAIL_APP_PASSWORD': 'test-only', 'GMAIL_IMAP_HOST': 'example.invalid'}
        exec(compile(ast.Module(body=[function], type_ignores=[]), '<delivery>', 'exec'), namespace)
        mailbox = Mock()
        mailbox.login.side_effect = TimeoutError('test timeout')
        with patch.object(imaplib, 'IMAP4_SSL', return_value=mailbox) as connect, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(namespace['get_gmail_delivery_emails'](), [])
        connect.assert_called_once_with('example.invalid', timeout=15)
        mailbox.logout.assert_called_once()
