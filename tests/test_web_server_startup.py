import errno
import unittest
from web_control.run_waitress import main, server_address, bind_error_message


class WebServerStartupTests(unittest.TestCase):
    def test_port_can_be_changed_without_editing_code(self):
        calls = []
        main(serve_fn=lambda app, **kwargs: calls.append(kwargs), application=object(),
             environ={'RECEIPT_WEB_HOST': '127.0.0.1', 'RECEIPT_WEB_PORT': '5051'})
        self.assertEqual(calls, [{'host': '127.0.0.1', 'port': 5051, 'threads': 4}])
        self.assertEqual(server_address({}), ('0.0.0.0', 5050))

    def test_invalid_port_fails_before_binding(self):
        for value in ('abc', '0', '65536'):
            with self.subTest(value=value), self.assertRaises(SystemExit):
                main(serve_fn=lambda *args, **kwargs: None, application=object(),
                     environ={'RECEIPT_WEB_PORT': value})

    def test_address_in_use_explains_how_to_find_listener(self):
        error = OSError(errno.EADDRINUSE, 'Address already in use')
        message = bind_error_message(error, '0.0.0.0', 5050)
        self.assertIn('lsof -nP -iTCP:5050 -sTCP:LISTEN', message)
        self.assertIn('RECEIPT_WEB_PORT=5051', message)

if __name__ == '__main__':
    unittest.main()
