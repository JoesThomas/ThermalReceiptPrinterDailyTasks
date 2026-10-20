# Centred receipt content

The 80mm, 203dpi printer has a 576-dot printable line. Font A has a 12-dot
character cell: the existing 42-column content fits within a 48-column physical
line. `ContentPrinter` adds a three-space inset at the hardware boundary for
left-aligned body lines, giving the 42-column block equal side margins.
Native-centred headings and full-width graphs share its midpoint.

This physical adapter is used by the deferred live printer, including custom
page ordering, saved-receipt reprints and short printer tests. It preserves
partial text writes, list indentation, amounts and blank lines. Saved text and
web previews remain at 42 columns, so reprinting never adds the inset twice.

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
