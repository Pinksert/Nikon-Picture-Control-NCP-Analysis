# Nikon Picture Control (.NCP / .NP2 / .NP3) format analysis and conversion tools

中文版：[README.md](README.md)

Reverse engineering of Nikon's Picture Control file formats, plus tools to
convert newer `.NP2` / `.NP3` presets down to `.NCP` — the only format old
bodies (Nikon D300 / D300S / D90 …) can read.

All numbers in this document were measured on real files, not guessed.
Sample set: 42 factory presets exported by Nikon Picture Control Utility 2
(6 × .NCP, 8 × .NP2, 28 × .NP3).

## 1. The three generations

| | NCP | NP2 | NP3 |
|---|---|---|---|
| Version string | `0100` | `0210` | `0300` |
| Container | header + type/length record | TLV card chain | TLV card chain |
| Size | always 52 bytes (no curve) | 208 + 8 + caption | 248 + 8 + caption |
| Bodies | all PC-capable bodies | D810 and later | Z series, D6, D780 |
| Extra parameters | — | clarity | quick sharp, mid-range sharp, effect level |

All three start with the same magic: `NCP\0`.

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

Monochrome toning enum (cross-checked against public reverse-engineering
docs, matches the D300 menu order): `0 BW, 1 sepia, 2 cyanotype, 3 red,
4 yellow, 5 green, 6 blue-green, 7 blue, 8 purple-blue, 9 red-purple`.
Mono filter: `0 off, 1 yellow, 2 orange, 3 red, 4 green`.

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

### ⚠️ Verify with "camera compatible", not the latest system

Measured in Nikon's own software with the same curve-carrying NCP:

* Under **[camera compatible]** every byte keeps its meaning: `01` is read
  as "handled by curve" and the UDC is applied in full — this is the
  pipeline the file was written for, and the one old bodies actually run.
* Under **[latest Picture Control system]** the app forces the NCP slider
  sequence into the new parameter table **by position**: contrast (`01`)
  shows up as "mid-range sharpening 1.00" and brightness (`01`) as
  "clarity 1.00". The curve sentinel has no slot there and is treated as a
  plain value.

Previews under the latest system are therefore misleading. **Validate
against [camera compatible] — or better, the camera itself.**

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

## 8. Solved

In order of discovery; every item rests on measurements made on real files
or exported images.

1. **Container differences across the three generations** — magic, version
   strings, TLV card chain, record type/length; derived from comparing all
   42 factory presets.
2. **NP2/NP3 → NCP parameter mapping** — 8 slider slots × 6 presets × 2
   formats = **96 bytes hit**; 6 presets rebuilt **byte-identical (52/52)**
   to Nikon's own files.
3. **Base curve id system** — NCP knows only six; flat, auto and the 20
   creative ids have no counterpart. This, not an uncracked format, is why
   creative presets cannot be ported: the curves live in firmware.
4. **Mono filter and toning enums** — cross-checked against public
   reverse-engineering docs.
5. **638-byte layout of curve-carrying NCP** — 64-byte header + 257 × uint16
   LUT, confirmed by rebuilding a real export byte for byte.
6. **Header control point encoding** — byte 8 is the point count, points
   start at byte 9 as (x, y); confirmed by diffing two exports with
   different curves.
7. **Curve corruption from changing the LUT but not the control points** —
   Nikon's software reads the control points. Fix: write the same curve into
   both, and use the full 20 points so interpolation error becomes
   negligible (0.6–14.6 / 32767).
8. **Curve not tuned for the old body** — the first measurement used
   "latest-system standard → latest-system portrait", but the NCP runs on the
   old pipeline, so the LUT landed on a different base. Fix: take the
   reference export from **[camera compatible] + STANDARD**.
9. **Nikon's spline is unknown** — a tension-parameterised Catmull-Rom fit
   failed (best parameter 1.20 vs 0.98 on two samples). Fix: stop guessing
   the algorithm, use a **black-box loop** — export, measure residual, nudge
   the control points. One round converged: luma residual 9.48 → **2.02**,
   and **2.01** on a second photo that never took part in calibration, so the
   curve generalises rather than overfits.
10. **Calibration of the saturation and hue sliders** — measured from four
    calibration NCPs (saturation / hue at ±1). Under a symmetric-linear
    assumption the ±1 ratio and difference solve it without a zero-point
    reference: **saturation is chroma ×1.267 per step, hue is 3.46° per step**.
    The colour demand of all 30 presets was converted into steps with that
    (clamped to ±3).
11. **Header offset bug found and fixed** — while correcting the sliders the
    header was read from `b[64:128]` instead of `b[56:120]`, so the control
    point area was overwritten with misaligned data and the software produced a
    blocky, colour-banded image. Fixed by rebuilding the header with the same
    `hdr_with_delta()` used by the batch path; lesson recorded — offsets always
    go through the parser, never hand-written numbers.

Final numbers for the portrait preset:

| | before | v2 | v3 | target |
|---|---|---|---|---|
| mean luma | 89.46 | 86.12 | **95.53** | 95.51 |
| per-pixel luma diff | 6.49 | 9.48 | **2.02** | — |

## 9. Still open and not verified

**Open (format level)**

* Purpose of header bytes `0..7`, especially `49 30` — not XMODEM/CCITT/
  MODBUS/Kermit CRC16, not a plain sum.
* Nikon's exact spline between control points (cracking it was abandoned in
  favour of the black-box loop).
* `PINK` toning colour — assumed 9 (red-purple), unconfirmed;
  SEPIA/BLUE/RED are confirmed.
* Semantics of NP3 cards `0x1300`, `0x1400`, `0x1600` (step code is not the
  usual `04`, so the value formula does not apply).
* The 20 creative base curves themselves: they live in firmware, so no file
  format trick will bring them to an old body.

**Open (hard limits of the approach)**

* **Selective colour work cannot be reproduced** — this is the final verdict
  and it is measured. Breaking DREAM's residual down by hue region
  (`data/hue_breakdown.json`):

  | hue band | share | chroma diff (target − ours) | hue shift |
  |---|---|---|---|
  | red | 7.1% | −10.53 | −1.5° |
  | orange | 9.8% | −9.98 | +1.0° |
  | yellow | 33.7% | −0.18 | −0.1° |
  | yellow-green | 31.1% | +3.28 | −4.0° |
  | green | 7.2% | +10.90 | −15.7° |

  The difference swings hard with the hue band (−10.5 to +10.9): yellow is
  nearly perfect while red and green go in opposite directions. That is the
  fingerprint of **selective colour work (a colour matrix)**, and it is exactly
  what creative presets are made of — pull red down, push green up, shift green
  hues by a dozen degrees. Every tool a D300 can run is **global** (saturation
  affects all colours, hue rotates all colours, the curve touches all
  luminances), so "pull down red but leave yellow alone" cannot be expressed.
  **This is not an uncracked format and not a calibration miss — the D300
  processing engine simply cannot do it. It is a generational gap in hardware
  and firmware.**
* **Colour cannot be reproduced by a 1D luminance table** (same root cause).
* **Clarity, quick sharpening and other new parameters** have no slot in NCP
  and must be dropped.
* **Limits of the measurement model**: the "how much saturation is still needed"
  figure comes from a simplified model that scales luminance and holds hue.
  For strongly colour-shifted presets such as DREAM that model breaks down
  (the slider was observed to move the result the wrong way). It is reliable
  only for low-saturation and monochrome presets.

**Not verified**

* ~~Everything so far was verified inside Nikon's desktop software, never on
  an actual D300.~~ **It now runs on the body** (see section 11 and `d300/`):
  card → in-camera load → shooting → pixel-level comparison, 29 frames over
  three rounds. The body does treat control points and LUT the same way, and
  **the firmware applies the same pre-curve transform H as the desktop engine**.
* Only **portrait, DREAM and SILENCE** went through the full export → residual
  → correction loop. The other 27 presets were measured once and never
  individually validated.
* Calibration used two photos. Generalisation was checked on a second image,
  but extreme scenes (very high contrast, night shots, large flat colour
  areas) are untested.

## 10. What this method can and cannot carry over

| can carry | cannot carry |
|---|---|
| tone / luminance mapping (residual down to ~2/255) | selective, per-hue colour work |
| overall saturation and hue bias (calibrated steps) | colour-matrix operations (engine generation gap) |
| monochrome conversion and toning (filter / toning enums) | clarity, quick / mid-range sharpening |
| base carrier (the six known ids) | the creative base curves themselves (in firmware) |

**Verdict**: monochrome and toned presets (charcoal, graphite, binary, carbon,
the monochrome family, sepia, blue, red, pink) come out close enough to use.
Colour creative presets only get the tone right — the colour difference is
principled, not a calibration shortfall.

---

## 11. Real-camera follow-up (D300)

[d300/README.md](d300/README.md) documents pushing this method onto real hardware, including
**corrections to the analysis above**: the in-camera path is `A:/NIKON/CUSTOMPC/PICCON%02d.NCP`
(no root-directory scan in firmware); the name field is ASCII 20 bytes (not UTF-16BE, which is why
`np2ncp.py` emits `????`); the description card is UTF-8; the monochrome toning enumeration is
`FF 00` ("n/a") in source files and cannot be recovered from data; the LUT need not be monotonic.

It also resolves the open "curve header 8 bytes" question (identical across 35 files with very
different curves → a fixed tag, not a checksum), and documents a **fixed pre-curve transform H**
in the NX Studio "compatible with camera" engine (`out = C(H(x))`, −18 in the midtones).

**Three findings that only showed up on the body** (full data:
[d300/docs/07-camera-verification.md](d300/docs/07-camera-verification.md)):

* **Base id must match the slider type**: `0x0001` for colour, `0x064D` for monochrome
  (saturation/hue = `FF FF`). `0x0002/0x0003/0x0004` and the new-system four-digit ids
  are silently dropped from the in-camera load list — individually skipped, not fatal to
  the rest of the card.
* **A single flag decides whether the stored curve is used at all**: bytes `[41][42]` of the
  eight sliders must be `01 01` in any 638-byte file. `0x01` is a *sentinel* meaning "hand this
  over to the custom curve"; `0x80` (numeric 0, linear) makes the body ignore the whole
  578-byte curve block — no error, no warning, the file still lists normally.
  Across 116 factory files: 52-byte → always `80 80`, 638-byte → always `01 01`.
* **The body has the same H as the desktop engine**: a hard step at v=128 crosses 50 % at
  input 144.6 (model `H⁻¹(128) = 146.1`); reconstructing the whole H from a gamma 0.45 curve
  gives **+0.95 ± 1.04 levels** against the workshop H. So the compensation only needs to
  exist once — card output and NX Studio output agree.

Final deliverable: **`d300/ncp/release/`**, 30 compensated NCP files ready to copy to the card.
Note the body only holds **9 custom Picture Controls (C-1…C-9)**, so import in batches.

### How close does the result actually look?

30 same-frame sample pairs, filters 01–30 in full (one RAW, exported once with NX Studio's newest
Picture Controls and once with the compensated NCP files), were compared pixel by pixel — see
[`d300/samples/`](d300/samples/README.md).

* **Tone is essentially solved**: every filter's mean luminance deviation is within ±4.2 levels (median 1.4), and
  the tone-curve RMS is 3.6 levels at the median.
* **Colour is not** (first revision): the overall mean absolute difference is 8.4 levels, and nearly all of it is
  colour. `DREAM` is the cleanest example — tone-curve RMS just 2.2 levels and ΔL +0.7, yet it still
  lands at 9.8 levels because of one warm cast (R−B off by −26). Saturation sits at `0x80`
  (numeric 0) in every generated file, so presets that lean on desaturation (`SILENCE` 4.35×,
  `BLEACH` 4.03×, `DRAMA` 2.92× more chromatic than the original) or on a global cast
  (`PURE` +32, `DENIM` +31, `MORNING` +27 R−B) cannot be reproduced: an NCP curve is a
  **single luminance LUT**, with no per-channel curve to tint with.

### Second revision (current `d300/ncp/release/`)

The first revision left the saturation and hue sliders at `0x80` (numeric 0). The second revision
puts them to work:

* saturation/hue calibrated from four in-camera test shots — **×1.13 chroma per step, 3.5° hue per
  step** (measured 1.1274/step for `SAT-1 → SD`, 1.1351/step for `SAT-1 → SAT+1`, 7.00° across
  two hue steps);
* tone curves refitted with a **held-out half-frame**: parameters are chosen on the top half and
  only accepted if they also improve the bottom half, which is never seen during fitting;
* curve end-points extrapolated from the slope of the last valid bins (the shadows used to be
  lifted by 3–6 levels when the darkest bins had too few pixels to fit).

Result over the same 30 pairs, recomputed **from the files themselves** by
`d300/tools/audit_release.py` (not self-reported by the optimiser):

| Group | n | v1 | v2 |
|---|---|---|---|
| Mono 17–20 | 4 | 3.92 | **2.77** |
| New-system 21–30 | 10 | 5.06 | **4.28** |
| Creative colour 01–12 | 12 | 9.52 | **8.20** |
| Toning 13–16 | 4 | 14.38 | **8.19** |
| **All 30** | **30** | **7.94** | **6.17 (−22.3 %)** |

**22 improved, 8 unchanged, 0 worse.** On the held-out half: **9.08 → 7.08 (−22.0 %)**, i.e. the
gain is not an artefact of fitting. The toning group is the biggest win (14.4 → 8.2): those four
were built as "true monochrome + heavy toning (`0x84`)", while the originals are "low saturation,
some colour left + light toning" — dropping the toning strength to `0x81–0x82` fixed the approach.

Still out of reach: **casts** (`DENIM` 13.24 → 13.17, `MORNING` unchanged at 11.81) and **per-hue
saturation**. Seven filters are already at the −3 hardware limit on saturation and still not low
enough. Methodology: `d300/docs/08-tone-color-v2.md`.
* **Best group**: pure monochrome (charcoal / graphite / binary / carbon / monochrome), 3.5–5.8 levels.
  **Worst group**: sepia / blue / red / pink at 13–16 levels — those were built as
  "monochrome base + heavy toning", while the originals are "low saturation, colour partly retained,
  light toning". That route needs rebuilding.

Bottom line: monochrome filters are usable as-is; colour Creative Picture Controls are
*same-mood approximations*, not reproductions.
