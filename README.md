# Nikon Picture Control（.NCP / .NP2 / .NP3）格式分析与转换工具

Reverse engineering of Nikon's Picture Control (优化校准) file formats, plus tools to
convert newer `.NP2` / `.NP3` presets down to `.NCP` — the only format old bodies
(Nikon D300 / D300S / D90 …) can read.

All numbers in this document were measured on real files, not guessed.
Sample set: 42 factory presets exported by Nikon Picture Control Utility 2
(6 × .NCP, 8 × .NP2, 28 × .NP3).

---

## 1. The three generations

| | NCP | NP2 | NP3 |
|---|---|---|---|
| Version string | `0100` | `0210` | `0300` |
| Container | "header + type/length record" | TLV card chain | TLV card chain |
| Size | always 52 bytes (no curve) | 208 + 8 + caption | 248 + 8 + caption |
| Bodies | all PC-capable bodies | D810 and later | Z series, D6, D780 |
| Extra parameters | — | clarity | quick sharp, mid-range sharp, effect level |

All three start with the same magic: `NCP\0`.

---

## 2. NCP (0100) layout

```
offset 0   4   "NCP\0"
offset 4   4   record type = 1 (profile data)
offset 8   4   record length = 36
offset 12  4   version "0100"
offset 16  20  name, ASCII, zero padded
offset 36  2   base curve id (big endian)
offset 38  1   modified flag
offset 39  1   0xFF (purpose unknown)
offset 40  8   the eight sliders
offset 48  4   0x00000000 (end marker)
= 52 bytes
```

Slider byte encoding (`value + 0x80`), range −126…126, plus three sentinels:

| byte | meaning |
|---|---|
| `0x00` | Auto (−128) |
| `0x01` | Curve (−127) — handled by the LUT, seen in contrast / brightness |
| `0xFF` | Not applicable (127) |

Slider order: sharpening, contrast, brightness, saturation, hue,
filter effect (mono), toning (mono), toning strength (mono).

Known base curve ids — there are only six in the NCP era:

```
0001 standard   03C2 neutral   00C3 vivid
0486 portrait   04C7 landscape 064D monochrome
```

`028E` (flat) and `02CF` (auto) and the 20 creative ids `0801`–`0814`
do **not** exist in NCP. A file can still be produced, but old bodies
have no curve to go with those ids.

Monochrome toning enum (from public reverse-engineering docs, matches
D300 menu order): `0 BW, 1 sepia, 2 cyanotype, 3 red, 4 yellow, 5 green,
6 blue-green, 7 blue, 8 purple-blue, 9 red-purple`.
Mono filter: `0 off, 1 yellow, 2 orange, 3 red, 4 green`.

---

## 3. NP2 / NP3 (0210 / 0300) layout

TLV chain starting after the 4-byte magic; each card is
`type(4) + length(4) + data`, terminated by 4 zero bytes.

```
type 0x100  version string ("0210" / "0300")
type 0x200  name, UTF-16BE, 20 bytes
type 0x300  base curve id (2 bytes)          <- same ids as NCP
type 0x400  always 00 00
type 0x500  always FF 01
type 0x600  sharpening
type 0x700  clarity                          <- NP2+, no NCP slot
type 0x800  contrast
type 0x900  brightness
type 0xA00  saturation
type 0xB00  hue
type 0xC00  filter effect (mono)
type 0xD00  toning (mono)
type 0xE00  toning strength (mono)
type 0xF00..0x1200  reserved, FF 01
type 0x1300..0x1600 NP3 only (quick sharp / mid-range sharp / effect level …)
type 0x10100 caption text
```

Value encoding: `value = (v - 0x80) * step / 16`.
Step code `04` means a 0.25 increment; `0xFF` means not applicable.

---

## 4. NP2 / NP3 → NCP mapping

```
card 0x600 sharpening  -> NCP[40]
card 0x800 contrast    -> NCP[41]
card 0x900 brightness  -> NCP[42]
card 0xA00 saturation  -> NCP[43]
card 0xB00 hue         -> NCP[44]
card 0xC00 filter      -> NCP[45]
card 0xD00 toning      -> NCP[46]
card 0xE00 toning str. -> NCP[47]
card 0x300 base id     -> NCP[36:38]
```

Verified: 8 slots × 6 presets × 2 formats = **96 bytes, 96 hits**.
End-to-end: 6 presets × NP2/NP3 = 12 files rebuilt **byte-identical
(52/52)** to Nikon's own NCP files.

### What cannot be converted

* **card 0x700 (clarity)** — NCP has no slot for it.
* **cards 0x1300–0x1600** — NP3-only, no slot.
* **0.25 steps** — NCP is integer-only, e.g. neutral's +0.50 can only become 0 or 1.
* **Ranges** — NP2/NP3 brightness reaches ±1.5 (NCP ±1); NP3 sharpening reaches −3 (NCP 0).
* **Base curves** — flat / auto / 20 creative ids have no NCP equivalent. The
  base TRC lives in camera firmware and can never be exported; the NCP only
  stores its id. This is the real reason creative presets cannot be ported.

`np2ncp.py --approx` substitutes the closest of the six known bases
(flat → neutral, auto → standard, monochrome-style → monochrome,
everything else → standard) so the file at least loads. It is an
approximation, not a conversion.

---

## 5. User-defined curve (UDC)

An NCP may carry a user curve as record type 2. Structure confirmed
byte-for-byte by rebuilding a real PCU2 export:

```
"NCP\0"
type=1  len=36   profile data
type=2  len=578  ├─ 0..63   header
                 └─ 64..577 257 × uint16 big endian, 0..32767
type=0
= 638 bytes
```

* LUT input index `i` (0…256) corresponds to input `i/256`.
* Output is 15-bit, full scale 32767, must be monotonic.
* The UDC is applied **after** sRGB (1/2.4) gamma, i.e. it is the last step
  of the pipeline — a luminosity-only 1D LUT, so it cannot express colour shifts.

### Header

```
bytes 0-7   49 30 00 FF 00 FF 01 00   constant in all observed files
                                      (first two bytes are not any common CRC16)
byte  8     number of control points
byte  9..   points, 2 bytes each: (x, y), 8-bit, x increasing
```

Examples read from real files:

* 3 points → `(0,0) (73,140) (255,255)`; the LUT at x=73 reads 54.7%,
  and 140/255 = 54.9% ✓
* 4 points → `(0,0) (69,175) (179,81) (255,255)` — up, down, up, i.e. the
  non-monotonic wave that was drawn in the editor ✓

**Important:** the editing software rebuilds the curve from these control
points. If you write a new LUT but keep someone else's control points, the
displayed and applied curve will not match what you wrote. Always write both.

Nikon's exact spline is not confirmed. Measured reconstruction error from
3 control points (full scale 32767): linear 2031, Catmull-Rom 1673,
natural cubic 9783, monotone cubic 612. Rather than depend on that, this
toolkit emits **20 control points** sampled from the target LUT, which
drops the error to 0.6–14.6 — negligible either way.

---

## 6. Fitting a preset's tone response from photos

Because the UDC is the last pipeline step, the curve that turns "standard"
into "target preset" can be measured:

1. Export the same NEF twice from Nikon's software, sliders at default:
   once with STANDARD, once with the target preset.
   Keep every export setting identical (sRGB, 8-bit, same size).
2. `make_curve_batch.py` recognises which preset each JPEG used (it reads the
   MakerNote `03100310` marker; name at +8, base id at +48 little endian),
   bins pixels by luminance, and produces a 257-point LUT.
3. It writes a 638-byte NCP with matching control points.

Accuracy measured on portrait vs standard (12,212,224 pixels):

| | before | after curve | target |
|---|---|---|---|
| mean luminance | 91.25 | 95.52 | 95.51 |
| per-pixel luma diff | 7.73 | 2.56 | — |

Colour is a different story — chroma a\* 2.21→1.93, saturation 2.41→2.17,
roughly **10%** of the difference. A 1D luminance LUT cannot reproduce the
colour work a preset does. Monochrome and toned presets are where this
approach pays off; colourful creative presets will get the tone right and
the colour wrong.

---

## 7. Usage

```bash
# plain downgrade (base ids copied as-is, unknown ones flagged)
python np2ncp.py <dir with .NP2/.NP3> [out dir]

# approximation: substitute the closest of the six NCP-recognised bases
python np2ncp.py <dir> [out dir] --approx

# inspect a real .NCP (dumps every record and the curve hex)
python np2ncp_curve.py dump <file.ncp> [out.txt]

# rebuild a real .NCP from its own fields and diff byte by byte
python np2ncp_curve.py rebuild <file.ncp>

# measure a curve from two exports
python np2ncp_curve.py measure <standard.jpg> <target.jpg> <lut.json>

# batch: one directory of exports, STANDARD as reference
python make_curve_batch.py <jpg dir> [out dir]

# how much of the preset did the curve actually recover
python verify_curve.py <standard.jpg> <target.jpg> <lut.json>
```

---

## 8. Still open

* Purpose of header bytes `0..7`, especially `49 30` — not XMODEM/CCITT/
  MODBUS/Kermit CRC16, not a plain sum.
* Nikon's exact spline between control points.
* `PINK` toning colour — assumed 9 (red-purple), unconfirmed;
  SEPIA/BLUE/RED are confirmed.
* Semantics of NP3 cards `0x1300`, `0x1400`, `0x1600` (step code is not the
  usual `04`, so the value formula does not apply).
* The 20 creative base curves themselves: they live in firmware, so no file
  format trick will bring them to an old body.
