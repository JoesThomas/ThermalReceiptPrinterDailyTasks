"""Consistent 42-column text for compact and detailed finance receipts."""

from textwrap import wrap
from finance.money import format_pounds


class ReceiptText:
    def __init__(self, width=42):
        self.width = width
        self.lines = []

    def text(self, value=""):
        self.lines.extend(wrap(str(value), self.width) or [""])

    def rule(self):
        self.lines.append("-" * self.width)

    def section(self, title):
        self.rule()
        self.text(title.center(self.width))
        self.rule()

    def amount(self, label, value):
        right = format_pounds(value)
        if len(label) + len(right) + 1 <= self.width:
            self.lines.append(label + right.rjust(self.width - len(label)))
        else:
            self.text(label)
            self.lines.append(right.rjust(self.width))

    def render(self):
        return "\n".join(self.lines) + "\n"
