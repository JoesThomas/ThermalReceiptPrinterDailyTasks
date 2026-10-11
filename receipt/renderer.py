from __future__ import annotations
from pathlib import Path
import textwrap
from config import RECEIPT_WIDTH, MAX_RECEIPT_LINES
from receipt.model import ReceiptDocument

def _wrap(text: str) -> list[str]:
    if not text:
        return [""]
    return textwrap.wrap(
        text, width=RECEIPT_WIDTH,
        break_long_words=False, break_on_hyphens=False
    ) or [""]

def render_text(document: ReceiptDocument) -> str:
    out = []
    for section in document.sections:
        if section.title:
            out.append("=" * RECEIPT_WIDTH)
            out.extend(_wrap(section.title.upper()))
            out.append("-" * RECEIPT_WIDTH)
        for line in section.lines:
            out.extend(_wrap(line))
    return "\n".join(out).rstrip() + "\n"

def compress_if_needed(document: ReceiptDocument) -> ReceiptDocument:
    limit = MAX_RECEIPT_LINES.get(document.name)
    if not limit or document.line_count <= limit:
        return document
    # Remove empty spacer lines first, then optional low-priority sections.
    for section in document.sections:
        section.lines = [x for x in section.lines if x != ""]
    if document.line_count <= limit:
        return document
    # Remove optional sections by priority while preserving the chosen page order.
    remaining = document.line_count
    remove = set()
    for index, section in sorted(enumerate(document.sections), key=lambda row: row[1].priority):
        if remaining <= limit:
            break
        if section.optional:
            remove.add(index)
            remaining -= section.line_count
    document.sections = [section for index, section in enumerate(document.sections) if index not in remove]
    return document

def write_preview(documents: list[ReceiptDocument], path: Path) -> Path:
    chunks = []
    for i, document in enumerate(documents, 1):
        chunks.append(f"\n{'#' * RECEIPT_WIDTH}\nRECEIPT {i}: {document.name.upper()}\n{'#' * RECEIPT_WIDTH}\n")
        chunks.append(render_text(compress_if_needed(document)))
        chunks.append("\n--- CUT ---\n")
    path.write_text("".join(chunks), encoding="utf-8")
    return path

def print_document(printer, document: ReceiptDocument, cut: bool = True) -> None:
    text = render_text(compress_if_needed(document))
    if hasattr(printer, "text"):
        printer.text(text)
    else:
        print(text)
    if cut and hasattr(printer, "cut"):
        printer.cut()
