from __future__ import annotations
from dataclasses import dataclass, field

@dataclass
class ReceiptSection:
    key: str
    title: str
    lines: list[str] = field(default_factory=list)
    priority: int = 50
    optional: bool = False

    def add(self, text: object = "") -> None:
        self.lines.append(str(text))

    def extend(self, lines) -> None:
        self.lines.extend(str(x) for x in lines)

    @property
    def line_count(self) -> int:
        return len(self.lines) + (2 if self.title else 0)

@dataclass
class ReceiptDocument:
    name: str
    sections: list[ReceiptSection] = field(default_factory=list)

    def add(self, section: ReceiptSection) -> None:
        if section.optional and not section.lines:
            return
        self.sections.append(section)

    @property
    def line_count(self) -> int:
        return sum(section.line_count for section in self.sections)
