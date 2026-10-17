# E-Paper Hub Dashboard — Implementation Spec

## Hardware / display
- Panel: 296×152 px, 1-bit mono (black/white), SSD1680-class controller.
- Orientation: **portrait, 152 wide × 296 tall**. Implement a `px(x,y)` writer that maps portrait coords to the native landscape buffer (rotate 90°); all layout below is in portrait coords.
- Refresh: **full refresh only**, once per rotation slot. No partial refresh.
- Margins: 6 px all sides. Content width = 140 px.

## Fonts (3 sizes only)
- `F12` — 8×16 body/header values.
- `F10` — 5×7 / 6×10 labels, log rows, detail rows.
- Hero numerals — 8×16 upscaled 3× to 24×48 (nearest-neighbour, no anti-alias). Denominator uses `F10` upscaled 2× to 16 px.
- Fixed-width only. No smoothing, no anti-aliasing anywhere.

## Tag ID rendering
- 16-bit identifier shown as **4 uppercase hex chars** (`A3F2`), no `0x` prefix.
- Column is fixed 4 chars. Optional alias mode replaces hex 1:1 with a 4-char alias (`S3P4`) — **all-or-nothing**, config flag `LOG_IDS=hex|alias`. Never mix.
- 6-char aliases (`S03-P4`) allowed: shift event column to x=86, cap event text at 9 chars.

---

## Screen A — Control Room + recent log (primary)
