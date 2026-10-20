# Centred receipt content

The default 80mm, 203dpi printer has a 576-dot printable line. Font A has a
12-dot character cell: the standard profile now uses all 48 columns, based on
the physical alignment test with both end markers visible. It adds no leading
character inset. Narrower custom and historical layouts retain their balancing
inset inside the physical print area. Hardware margins remain printer-dependent.

This physical adapter is used by the deferred live printer, including custom
page ordering, saved-receipt reprints and short printer tests. It preserves
partial text writes, list indentation, amounts and blank lines. Saved text and
web previews use the configured columns, so reprinting never adds the inset twice.

Earlier positioning used GS L / GS W and switched the native area around raster
images. Some ESC/POS-compatible devices do not reliably restore that state at
the image boundary. Receipt initialization now resets the device to its normal
full print area; no renderer switches native margins. Each body line gets its
inset independently of image state.

The adapter also ends a raster line before reasserting text justification. If
the renderer already supplies a leading newline, that newline is reused, so
this does not add an extra blank line after each graph. Tests use a printer
model that deliberately loses alignment after a bitmap and rejects text until
that raster line is finished, across immediate/deferred/reordered/archive paths.

The layout assumes the configured 80mm/203dpi Font A profile. A fresh physical
receipt remains the final check on a particular printer's firmware.

Section headings are explicitly centred within that same configured column block.
Historical archive pages retain their recorded rule width when reprinted.

Weather uses one local heading, followed by centred two-line tables: column
names and aligned values. Current conditions use abbreviated headings Temp,
Feels, Hum, Wind, Press and Dir so all six measurements fit in one header row
and one value row on the standard 48-column profile. Pressure includes hPa;
direction includes a compass point and degrees (for example SW220deg). Missing
or invalid optional readings are omitted rather than shown as zero. Narrow
profiles split the table into smaller groups. Hourly
conditions wrap inside their final column, with the current reading hour bold
on the physical printer and no extra marker or legend. Plain-text captures
retain the table spacing but do not store printer bold styling. The gigs
heading uses the same centred, bold style and dividers as other sections.

Daily settings, preview and print planning no longer offer compact/full detail.
Use the headline-count settings to control news length; Test finance retains
its separate compact/detailed selector. Old saved daily detail fields and CLI
`--detail` arguments remain accepted but have no effect.

There is no opening feed or cut. Blank lines at the beginning of each physical
page are discarded, and footer/section renderers no longer add three blank
lines before cutting. On profiles that support ESC/POS cutting, `ContentPrinter`
uses GS V Function B with zero extra feed, preserving full/partial cutter
capabilities. This feeds to the cutter position without the library's extra six
lines. Explicit cut options and unknown profiles retain the library behavior.
The last text/raster line is completed before cutting. This applies to live,
reordered and saved-receipt prints as well as the short paper test.

The gap between print head and cutter still sets a physical minimum margin;
no reverse feed is used. Verify the final footer and cut on a fresh physical
receipt, since compatible printer firmware varies.
Reference: https://download4.epson.biz/sec_pubs/pos/reference_en/escpos/gs_cv.html
