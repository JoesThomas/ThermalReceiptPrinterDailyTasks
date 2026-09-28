"""The event list prints locations while Villa travel keeps its own renderer."""
import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def calendar_renderer():
    """Load only the renderer, without importing the live service clients."""
    source = (ROOT / "services" / "live_pipeline.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    function = next(node for node in module.body if isinstance(node, ast.FunctionDef)
                    and node.name == "print_calendar")
    namespace = {}

    def left(printer, value):
        printer.lines.append(value)

    def print_line(printer, character="-"):
        left(printer, character * 42)

    def print_wrapped(printer, value, width=40):
        words, line = value.split(), ""
        for word in words:
            if line and len(line) + len(word) + 1 > width:
                left(printer, line)
                line = word
            else:
                line = f"{line} {word}".strip()
        if line:
            left(printer, line)

    namespace.update(left=left, print_line=print_line, print_wrapped=print_wrapped)
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(ROOT), "exec"), namespace)
    return namespace["print_calendar"]


class CalendarReceiptTests(unittest.TestCase):
    def test_event_location_follows_title_and_no_travel_section(self):
        class Printer:
            def __init__(self):
                self.lines = []

            def set(self, **kwargs):
                pass

        printer = Printer()
        calendar_renderer()(printer, [
            {"time": "10:00", "title": "Dentist", "location": "High Street, Birmingham"},
            {"time": "ALL DAY", "title": "Birthday", "location": ""},
            {"time": "14:00", "title": "Call", "location": " https://meet.google.com/abc "},
        ])
        self.assertEqual(printer.lines[3:6], [
            "[ ] 10:00 Dentist", "LOCATION: High Street, Birmingham", "[ ] ALL DAY Birthday"])
        self.assertIn("LOCATION: https://meet.google.com/abc", printer.lines)
        self.assertNotIn("TRAVEL", printer.lines)
        self.assertNotIn("LEAVE BY", "\n".join(printer.lines))

    def test_villa_train_renderer_remains_separate(self):
        source = (ROOT / "services" / "villa.py").read_text(encoding="utf-8")
        self.assertIn("def print_villa_matchday(", source)
        self.assertIn("get_villa_matchday_trains(", source)


if __name__ == "__main__":
    unittest.main()
