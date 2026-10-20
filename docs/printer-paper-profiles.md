# Printer widths and annual paper use

Settings → Printer size & paper rolls controls the local `data/printer_paper.json`
file. It is included in private backups; no printer or cloud requests are needed
to edit these values.

The roll length defaults to an **unverified 80 m assumption**. Double Dragon
80 × 80 mm identifies the roll width and diameter, not its usable length. Enter
the metres stated on the package/supplier specification. The estimate also
accepts prints per week and a percentage allowance for unusable paper (5% by
default). It is not a live sensor or a remaining-paper counter.

Receipt preview and Prepare print show the saved bundle's length, annual metres,
roll equivalents, whole rolls to budget for, days per roll, and replacement
changes after starting with a full roll. For example, 200 m/year with 80 m rolls
and 5% waste means 2.63 rolls, a budget of three whole rolls and two changes
after the initial full roll. Weekly/occasional pages and extra tests can differ
from repeating the whole saved bundle at the selected frequency. Empty/sample
previews do not invent a consumption figure. Zero prints/week gives zero usage.

## Printer geometry

- 80 mm preset: 46 text columns, 576 printable dots, 203 dpi, 12-dot Font A.
- 58 mm preset: 30 text columns, 384 printable dots, 203 dpi, 12-dot Font A.
- Custom: paper width, text columns, printable dots, resolution and Font A dot
  width from the printer manual. Width must be byte-aligned, columns must fit
  the printable dots and the printable area must fit the physical paper.

Restart Receipt Control after a geometry change: renderer constants are shared
for the life of the process. Until restart, generation/print requests are blocked
and the interface displays a restart notice; scheduled prints are also withheld.
Roll length, frequency, waste and estimate calibration update without restarting.
The configured width is applied to the physical ESC/POS device as well as graphs.

Captures wrap oversized rows within the selected width. Narrow weather summaries
split into smaller labelled tables; hourly readings retain their values and put
weather descriptions on a following line. Finance amounts and labels wrap within
the chosen width in both compact and detailed test receipts. Saved wider receipts
are wrapped and oversized images scaled down when reprinted on a narrower printer;
regenerating is preferable for a newly designed narrow layout. Old narrower receipts
retain their narrower layout on wider printers.

Web receipt paper width and column blocks follow the active profile. The estimate
uses image resolution, scaled image height, editable line height and cutter allowance.
The default line height is 3.75 mm and cutter allowance 15 mm; calibrate against a
physical print if necessary. These two values affect the estimate, not printer feed
commands. Some margin remains between the print head and cutter.

Only ESC/POS-compatible printers using the existing USB/network connections are
supported. A paper preset does not add a driver, change a printer's physical paper
size or validate its firmware. Use the short paper test after changing printers.
