# Centred receipt content

The 80mm, 203dpi printer has a 576-dot printable line. Standard Font A is
12 dots wide, so the existing 42-column content occupies 504 dots. Receipt
setup centres that block with 36-dot side margins (about 4.5mm each inside
the printable area). Lists and amounts stay left/right aligned within the
block; native centred headings share its midpoint. No leading spaces are
added to stored text, so saved previews and later reprints keep their layout.

Setup sends ESC/POS `GS P` (203 horizontal/vertical units per inch), `GS L`
(left margin) and `GS W` (print width) after `ESC @`. The recorder buffers these
commands along with text, so generation does not connect to the printer early.
Divider lines explicitly select left justification to avoid inheriting it from
a title or symbol. This matters on hardware wider than the web's 42-column view.

Existing full-width graph images temporarily use the full printable area;
text margins are restored immediately afterwards. Archive reprints initialise
the same Font A and margins, including for old saved receipts and images.
This preserves graph detail and avoids clipping images to the narrower text area.

The printer must support standard ESC/POS margin commands and the configured
80mm/203dpi Font A profile. Tests inspect the emitted bytes and deferred ordering;
a fresh physical receipt is still the final check on the specific printer.

Command references:
- https://download4.epson.biz/sec_pubs/pos/reference_en/escpos/gs_cp.html
- https://download4.epson.biz/sec_pubs/pos/reference_en/escpos/gs_cl.html
- https://download4.epson.biz/sec_pubs/pos/reference_en/escpos/gs_cw.html
