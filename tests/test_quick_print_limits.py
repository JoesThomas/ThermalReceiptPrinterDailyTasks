"""User limits persist and long notes remain printable without silent truncation."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from flask import Flask, jsonify

from receipt import quick_note
from web_control.quick_print import register


class QuickPrintLimitsTests(unittest.TestCase):
    def test_default_accepts_20000_characters_and_rejects_the_next(self):
        text = "x " * 10000
        note = quick_note.format_note(text, True, title="A long list")
        self.assertGreater(len(note.splitlines()), 80)
        self.assertTrue(quick_note.length_advice(note))
        with self.assertRaisesRegex(ValueError, "20,000"):
            quick_note.format_note(text + "x")
        with self.assertRaises(ValueError):
            quick_note.format_note("x", max_chars=True)
        self.assertFalse(quick_note.length_advice("A short note\n"))

    def test_worker_prints_long_note_and_removes_spool(self):
        note = quick_note.format_note("A task\n" * 100, True, title="Tasks")
        with tempfile.TemporaryDirectory() as root:
            key = quick_note.spool(root, note)
            with patch("receipt.printer.open_printer", return_value=Mock()),                  patch("receipt.printer_layout.ContentPrinter") as printer:
                quick_note.send(root, key)
                printer.return_value.text.assert_called_once_with(note)
            self.assertFalse(quick_note.path_for(root, key).exists())

    def test_setting_changes_apply_on_server_and_keep_the_draft(self):
        with tempfile.TemporaryDirectory() as root:
            app = Flask(__name__)
            app.secret_key = "test"
            app.testing = True
            start = Mock(return_value=(True, ""))
            register(app, lambda f: f, start, Path(root))
            with patch("web_control.quick_print.render_template",
                       side_effect=lambda template, **args: jsonify(args)):
                client = app.test_client()
                self.assertEqual(client.get("/quick-print").json["max_chars"], 20000)
                draft = "draft " * 700
                response = client.post("/quick-print", data=dict(
                    intent="save_settings", max_chars=2000, text=draft,
                    title="Keep this", checklist="on",
                ))
                self.assertEqual(response.json["text"], draft)
                self.assertEqual(response.json["title"], "Keep this")
                self.assertTrue(response.json["checklist"])
                self.assertEqual(client.get("/quick-print").json["max_chars"], 2000)
                response = client.post("/quick-print", data=dict(
                    intent="print", max_chars=100000, text=draft,
                ))
                self.assertEqual(response.json["text"], draft)
                self.assertEqual(response.json["preview"], "")
                start.assert_not_called()
                for invalid in ("0", "100001", "3.5", "nonsense"):
                    client.post("/quick-print", data=dict(intent="save_settings", max_chars=invalid))
                    self.assertEqual(quick_note.settings_store(root).read()["max_chars"], 2000)
                client.post("/quick-print", data=dict(intent="save_settings", max_chars=20000))
                response = client.post("/quick-print", data=dict(
                    intent="preview", text=draft, title="Heading", checklist="on",
                ))
                self.assertTrue(response.json["preview"].lstrip().startswith("Heading"))
                self.assertTrue(response.json["advice"])
                response = client.post("/quick-print", data=dict(
                    intent="print", text=draft, title="Heading", checklist="on",
                ))
                self.assertEqual(response.status_code, 302)
                key = start.call_args.args[0][1]
                self.assertIn("Heading", quick_note.path_for(root, key).read_text())

    def test_invalid_saved_settings_do_not_get_overwritten(self):
        with tempfile.TemporaryDirectory() as root:
            store = quick_note.settings_store(root)
            store.path.parent.mkdir(parents=True)
            store.path.write_text('{"version": 1, "max_chars": -1}')
            before = store.path.read_text()
            with self.assertRaises(ValueError):
                store.update(lambda value: value.update(max_chars=20000))
            self.assertEqual(store.path.read_text(), before)
