#!/usr/bin/env python3
"""Flip the touch Y axis for Xiaomi Pad 6 (pipa) in the tool-patched kernel.

  python3 tools/patch_xnu_pipa_yflip.py [KERNEL]

Patches KERNEL (default xnu/out/kernel.development.sweet.nop, the output of
tools/patch_xnu_nt36532.py) -> KERNEL.yf. Device-verified 2026-11-18: with the
plain tool mapping, tapping General opened Screen Time and vice versa (the UI
Y mirror). The NT36532 reports Y up from the bottom of the portrait canvas
(raw corner data: top=2875, bottom=52), iOS wants Y down from the top.

The one change, at file offset 0xAEE014 in SweetHID::touch (the normalize the
tool wrote at 0xAEE004):

  lsl  x9, x22, #16          ->  mov  w9, #0xb3f     (2879)
  nop                            sub  w9, w9, w22    (2879 - y)
  nop                            lsl  x9, x9, #16

so ny = ((2879 - y) << 16) / 2880 instead of (y << 16) / 2880. Same 12 bytes,
nothing else moves. X is identity (verified: right-side tap -> x=1796).
"""
import os
import re
import subprocess
import sys
import tempfile


def asm_at(vma, code_lines):
    """Assemble + link AArch64 instructions at a fixed VMA (same as the tool does)."""
    syms = {}
    patched = []
    for line in code_lines:
        def repl(m):
            sym = f"_abs_{m.group(2)}"
            syms[sym] = m.group(2)
            return f"{m.group(1)} {sym}"
        patched.append(re.sub(r"\b(b(?:\.[a-z]+)?|bl|cbnz\s+\w+,|cbz\s+\w+,|adrp\s+\w+,)\s*(0x[0-9a-fA-F]+)\b", repl, line))
    with tempfile.TemporaryDirectory() as d:
        sfile, ofile, efile, bfile = (os.path.join(d, n) for n in ("p.s", "p.o", "p.elf", "p.bin"))
        with open(sfile, "w") as f:
            f.write(".text\n" + "\n".join(patched) + "\n")
        defsym = []
        for sym, addr in sorted(syms.items()):
            defsym += ["--defsym", f"{sym}={addr}"]
        subprocess.run(["aarch64-linux-gnu-as", "-march=armv8-a", "-o", ofile, sfile], check=True)
        subprocess.run(["aarch64-linux-gnu-ld", f"-Ttext={hex(vma)}", "-N", "-e", "0",
                        "--no-warn-rwx-segments"] + defsym + ["-o", efile, ofile], check=True)
        subprocess.run(["aarch64-linux-gnu-objcopy", "-O", "binary", efile, bfile], check=True)
        return open(bfile, "rb").read()

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE, "xnu/out/kernel.development.sweet.nop")
DST = SRC + ".yf"

OFF = 0xAEE014  # the lsl x9, x22, #16 + two nops inside the tool's block
OLD = bytes.fromhex("c9be70d3") + bytes.fromhex("1f2003d5") + bytes.fromhex("1f2003d5")
assert len(OLD) == 12

# 2. The stylus/pen branch off (2026-11-18, device-verified: taps whose contact the
# NT36532 firmware classifies stylus-like took THIS unpatched path — apollo pen math,
# (y - off) * 25 / 10 with apollo offsets — and landed wrong; finger contacts took the
# tool's path. Force the branch down the finger path always: the finger mapping covers
# the whole panel (a stylus maps wrong until its constants are ported; no stylus here).
PEN_OFF = 0xAEDF9C  # ldrb w9, [x19, #192] (the stylus-event flag)
PEN_OLD = bytes.fromhex("69024339")
PEN_NEW = bytes.fromhex("09008052")  # mov w9, #0 -> the cbz below always branches

# 3. The finger-state gate (2026-11-18, the 0171 "validity gate" from NOTES, done at
# last): the tool's parse emits EVERY slot without reading the id/state byte, so a
# released slot keeps re-firing its last cell — phantom taps (tapping Photos opened
# App Store, a cell the finger had never touched). State byte semantics per the
# project's own clean-room decoder (tools/touch-nt36523/nt36523.c): raw = id<<3|event,
# event 1/2 = down/moving, 0 = release/empty. Gate: skip the slot when (raw & 7) == 0.
# Replaces the tool's X clamp (the HID-level clamp at 0xAEDF68 still bounds x).
GATE_OFF = 0x524C98  # mov w10,#1799; cmp; csel; nop  ->  ldrb w13,[x8]; tst w13,#7; b.eq next; nop
GATE_OLD = bytes.fromhex("eae08052" + "5f000a6b" + "42308a1a" + "1f2003d5")
GATE_NEW = bytes.fromhex("0d014039" + "ad090072" + "00fcff54" + "1f2003d5")
assert len(GATE_OLD) == len(GATE_NEW) == 16
GATE_NEXT = 0x524C20  # the parse loop's next-finger path (b.eq target)

# Assembled at OFF so the branch-range check is honest (none of these branch).
with tempfile.TemporaryDirectory() as d:
    sfile, ofile, efile, bfile = (os.path.join(d, n) for n in ("p.s", "p.o", "p.elf", "p.bin"))
    with open(sfile, "w") as f:
        f.write(".text\n" + "\n".join([
            "mov w9, #0xb3f",
            "sub w9, w9, w22",
            "lsl x9, x9, #16",
        ]) + "\n")
    subprocess.run(["aarch64-linux-gnu-as", "-march=armv8-a", "-o", ofile, sfile], check=True)
    subprocess.run(["aarch64-linux-gnu-ld", f"-Ttext={hex(OFF)}", "-N", "-e", "0",
                    "--no-warn-rwx-segments", "-o", efile, ofile], check=True)
    subprocess.run(["aarch64-linux-gnu-objcopy", "-O", "binary", efile, bfile], check=True)
    NEW = open(bfile, "rb").read()
assert len(NEW) == 12, f"assembler produced {len(NEW)} bytes, want 12"

data = bytearray(open(SRC, "rb").read())
cur = bytes(data[OFF:OFF + 12])
if cur == NEW:
    print(f"{SRC} already carries the Y flip")
elif cur != OLD:
    raise SystemExit(f"unexpected bytes at {hex(OFF)}: {cur.hex()} (want {OLD.hex()})")
else:
    data[OFF:OFF + 12] = NEW
    print(f"Y flip patched @ {hex(OFF)}")

cur_pen = bytes(data[PEN_OFF:PEN_OFF + 4])
if cur_pen == PEN_NEW:
    print(f"pen branch already off @ {hex(PEN_OFF)}")
elif cur_pen != PEN_OLD:
    raise SystemExit(f"unexpected bytes at {hex(PEN_OFF)}: {cur_pen.hex()} (want {PEN_OLD.hex()})")
else:
    data[PEN_OFF:PEN_OFF + 4] = PEN_NEW
    print(f"pen branch disabled @ {hex(PEN_OFF)} (all touches take the finger path)")

# 4. Active-area normalize (2026-11-18): the measured glass span is raw x 16..1771,
# y 52..2875 (the cal corner data in NOTES.md) but the tool divides the raw value by
# the full 1800/2880 — the error is ~0 at the left edge (why the left "works great")
# and grows to ~30 px across the screen (neighbor-cell taps on the right). Fold the
# active area in: x -> x-16 and divisors 1800->1755 (1771-16), 2879->2875, 2880->2824
# (2823 * 2880 / 2879). The X clamp stays (raw x <= 1771 < 1799: never triggers on
# real touches, so overwriting its first instruction with the -16 is safe).
AREA_X_CLAMP = 0xAEDF68  # the tool's X clamp stays INTACT (its write-back is the bic below)
AREA_BIC = 0xAEDF74  # bic w23, w8, w8, asr #31 = the clamp's write-back; the -16 goes HERE
SPAN_RIGHT = int(os.environ.get("NVT_SPAN_RIGHT", "1771"))
SPAN_LEFT = int(os.environ.get("NVT_SPAN_LEFT", "16"))
Y_BOTTOM = int(os.environ.get("NVT_Y_BOTTOM", "2875"))
Y_TOP = int(os.environ.get("NVT_Y_TOP", "52"))
LEFT_ROW = int(os.environ.get("NVT_LEFT_ROW", "314"))
Y_BOTTOM = int(os.environ.get("NVT_Y_BOTTOM", "2875"))
AREA_BIC_OLD = bytes.fromhex("177da80a")
AREA_BIC_NEW = asm_at(AREA_BIC, ["sub w23, w23, #16"])
AREA_NORM = 0xAEE004  # mov w12,#1800 | ... | mov w8,#2880 | ... | mov w9,#2879
AREA_NORM_OLD = asm_at(0xAEE004, ["mov w12, #1800"]) + asm_at(0xAEE00C, ["mov w8, #2880"]) + \
    bytes.fromhex("e9678152")  # mov w9, #0xb3f (2879), from the Y flip block above
AREA_NORM_NEW = asm_at(0xAEE004, [f"mov w12, #{SPAN_RIGHT-SPAN_LEFT}"]) + asm_at(0xAEE00C, ["mov w8, #2824"]) + \
    asm_at(0xAEE014, ["mov w9, #2875"])

def apply(off, old, new, label):
    cur = bytes(data[off:off + len(old)])
    if cur == new:
        print(f"{label} already in @ {hex(off)}")
    elif cur != old:
        raise SystemExit(f"unexpected bytes at {hex(off)}: {cur.hex()}")
    else:
        data[off:off + len(new)] = new
        print(f"{label} @ {hex(off)}")

# (the piecewise binary patch is RETIRED: two panics — the fix moves to source patch 0171, CI-built)
cur_gate = bytes(data[GATE_OFF:GATE_OFF + 16])
if cur_gate == GATE_NEW:
    # 2026-11-18: the gate PANICKED the kernel on right-side touches — its jump target
    # was wrong for the loop's register state. The state validation ALREADY exists
    # upstream at 0x524c50 (and w9, w8, #0x7; cmn w9, #2; b.cc — event in {1,2}), so
    # the gate was redundant. Restore the tool's X clamp.
    data[GATE_OFF:GATE_OFF + 16] = GATE_OLD
    print(f"gate REVERTED @ {hex(GATE_OFF)} (the upstream event gate already covers it)")
elif cur_gate != GATE_OLD:
    raise SystemExit(f"unexpected bytes at {hex(GATE_OFF)}: {cur_gate.hex()} (want {GATE_OLD.hex()})")

# 5. Final layout (2026-11-18, gesture-verified): raw Y is TOP-DOWN (no flip — the
# gestures proved it: bottom-right swipe-up must give Home), X is MIRRORED (left-right
# swapped). Glass spans x 16..1771, y 52..2875. The normalize block becomes:
#   x' = x - 16 ;  y' = y - 52            (offsets, in the recycled dead Y-clamp slots)
#   nx  = (1755 - x') << 16 / 1755        (mirror)
#   ny  = y' << 16 / 2823
apply(0xAEDF78, asm_at(0xAEDF78, ["mov w8, #2879", "cmp w22, #2879", "csel w8, w22, w8, lt", "bic w22, w8, w8, asr #31"]),
               asm_at(0xAEDF78, [f"sub w23, w23, #{SPAN_LEFT}", f"sub w22, w22, #{Y_TOP}", "nop", "nop"]), "offsets x-16 y-52 (recycled dead Y clamp)")

apply(0xAEE004, asm_at(0xAEE004, ["mov w12, #1800"]), asm_at(0xAEE004, [f"mov w12, #{SPAN_RIGHT-SPAN_LEFT}"]), "x divisor 1755")
apply(0xAEE008, asm_at(0xAEE008, ["lsl x11, x23, #16"]), asm_at(0xAEE008, [f"mov w8, #{Y_BOTTOM-Y_TOP}"]), "y divisor 2823")
apply(0xAEE00C, asm_at(0xAEE00C, ["mov w8, #2880"]), asm_at(0xAEE00C, ["lsl x11, x23, #16"]), "x numerator (x-16, straight)")
apply(0xAEE010, asm_at(0xAEE010, ["mov w8, #2880"]), asm_at(0xAEE010, ["sdiv x10, x11, x12"]), "x sdiv")
apply(0xAEE014, asm_at(0xAEE014, ["mov w9, #2879"]), asm_at(0xAEE014, ["lsl x9, x22, #16"]), "y numerator (y-52)")
apply(0xAEE018, asm_at(0xAEE018, ["sub w9, w9, w22"]), asm_at(0xAEE018, ["nop"]), "pad")
apply(0xAEE01C, asm_at(0xAEE01C, ["lsl x9, x9, #16"]), asm_at(0xAEE01C, ["nop"]), "pad")

open(DST, "wb").write(bytes(data))
print(f"written: {DST} ({len(data)} bytes)")
