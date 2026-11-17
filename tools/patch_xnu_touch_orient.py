#!/usr/bin/env python3
"""Brute-force the NT36532 touch orientation (path B).

Re-patches the touch coordinate parse block at 0x524C70 in
kernel.development.sweet.nop with one of 4 axis transforms:

  1  identity        X=a, Y=b                     (current build)
  2  flipX           X=1799-a, Y=b
  3  flipY           X=a, Y=2879-b
  4  rot180          X=1799-a, Y=2879-b

a = (b1<<8|b2)/10, b = (b3<<8|b4)/10 from the 65-byte point frame.
The Y clamp (2879) moves into the block for flipped variants; SweetHID's
own clamp at 0xAEDF78 stays as a backstop. Output: SRC + ".oN".

  python3 tools/patch_xnu_touch_orient.py 2
"""
import os
import re
import subprocess
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.environ.get("NVT_KERNEL", f"{BASE}/xnu/out/kernel.development.sweet.nop")
OFF = 0x524C70


def asm_at(vma, code_lines):
    syms = {}
    patched = []
    for line in code_lines:
        def repl(m):
            sym = f"_abs_{m.group(2)}"
            syms[sym] = m.group(2)
            return f"{m.group(1)} {sym}"
        new = re.sub(r"\b(b(?:\.[a-z]+)?|bl|cbnz\s+\w+,|cbz\s+\w+,|adrp\s+\w+,)\s*(0x[0-9a-fA-F]+)\b", repl, line)
        patched.append(new)
    with tempfile.TemporaryDirectory() as d:
        s, o, e, b = (f"{d}/p{i}" for i in ".s .o .elf .bin".split())
        open(s, "w").write(".text\n" + "\n".join(patched) + "\n")
        subprocess.run(["aarch64-linux-gnu-as", "-march=armv8-a", "-o", o, s], check=True)
        subprocess.run(["aarch64-linux-gnu-ld", f"-Ttext={hex(vma)}", "-N", "-e", "0",
                        "--no-warn-rwx-segments"] + [x for p in sorted(syms.items()) for x in ("--defsym", f"{p[0]}={p[1]}")]
                       + ["-o", e, o], check=True)
        subprocess.run(["aarch64-linux-gnu-objcopy", "-O", "binary", e, b], check=True)
        return open(b, "rb").read()


CURRENT = [  # what patch_xnu_nt36532.py wrote (identity)
    "add x8, x22, x24",
    "ldrb w9, [x8, #1]",
    "ldrb w10, [x8, #2]",
    "orr w9, w10, w9, lsl #8",
    "ldrb w10, [x8, #3]",
    "ldrb w11, [x8, #4]",
    "orr w8, w11, w10, lsl #8",
    "mov w10, #10",
    "udiv w2, w9, w10",
    "udiv w3, w8, w10",
    "mov w10, #0x707",
    "cmp w2, w10",
    "csel w2, w2, w10, cc",
    "nop",
]

NOP = "nop"
VARIANTS = {
    2: [  # flipX: X = 1799 - X
        "mov w10, #10",
        "udiv w2, w9, w10",
        "mov w11, #0x707",
        "cmp w2, w11",
        "csel w2, w2, w11, cc",
        "sub w2, w11, w2",
        "udiv w3, w8, w10",
        NOP, NOP, NOP, NOP, NOP, NOP, NOP,
    ],
    3: [  # flipY: Y = 2879 - Y
        "mov w10, #10",
        "udiv w3, w8, w10",
        "mov w11, #0xb3f",
        "cmp w3, w11",
        "csel w3, w3, w11, cc",
        "sub w3, w11, w3",
        "udiv w2, w9, w10",
        NOP, NOP, NOP, NOP, NOP, NOP, NOP,
    ],
    4: [  # rot180: X = 1799 - X, Y = 2879 - Y
        "mov w10, #10",
        "udiv w3, w8, w10",
        "mov w11, #0xb3f",
        "cmp w3, w11",
        "csel w3, w3, w11, cc",
        "sub w3, w11, w3",
        "udiv w2, w9, w10",
        "mov w11, #0x707",
        "cmp w2, w11",
        "csel w2, w2, w11, cc",
        "sub w2, w11, w2",
        NOP, NOP, NOP,
    ],
    # swap family: canvas X from axis2 (b), canvas Y from axis1 (a)
    5: [  # swap: X = b, Y = a
        "mov w10, #10",
        "udiv w2, w8, w10",
        "mov w11, #0x707",
        "cmp w2, w11",
        "csel w2, w2, w11, cc",
        "udiv w3, w9, w10",
        "mov w11, #0xb3f",
        "cmp w3, w11",
        "csel w3, w3, w11, cc",
        NOP, NOP, NOP, NOP, NOP,
    ],
    6: [  # swap+flipX: X = 1799 - b, Y = a
        "mov w10, #10",
        "udiv w2, w8, w10",
        "mov w11, #0x707",
        "cmp w2, w11",
        "csel w2, w2, w11, cc",
        "sub w2, w11, w2",
        "udiv w3, w9, w10",
        "mov w11, #0xb3f",
        "cmp w3, w11",
        "csel w3, w3, w11, cc",
        NOP, NOP, NOP, NOP,
    ],
    7: [  # swap+flipY: X = b, Y = 2879 - a
        "mov w10, #10",
        "udiv w2, w8, w10",
        "mov w11, #0x707",
        "cmp w2, w11",
        "csel w2, w2, w11, cc",
        "udiv w3, w9, w10",
        "mov w11, #0xb3f",
        "cmp w3, w11",
        "csel w3, w3, w11, cc",
        "sub w3, w11, w3",
        NOP, NOP, NOP, NOP,
    ],
    8: [  # swap+rot180: X = 1799 - b, Y = 2879 - a
        "mov w10, #10",
        "udiv w2, w8, w10",
        "mov w11, #0x707",
        "cmp w2, w11",
        "csel w2, w2, w11, cc",
        "sub w2, w11, w2",
        "udiv w3, w9, w10",
        "mov w11, #0xb3f",
        "cmp w3, w11",
        "csel w3, w3, w11, cc",
        "sub w3, w11, w3",
        NOP, NOP, NOP,
    ],
}


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("2","3","4","5","6","7","8"):
        sys.exit(__doc__)
    orient = int(sys.argv[1])
    data = bytearray(open(SRC, "rb").read())
    expected = asm_at(OFF, CURRENT)
    cur = bytes(data[OFF:OFF + len(expected)])
    assert cur == expected, f"parse block at {hex(OFF)} does not match the identity build ({cur.hex()[:32]}...)"
    new = asm_at(OFF, VARIANTS[orient])
    assert len(new) == len(expected), "size drift"
    data[OFF:OFF + len(new)] = new
    dst = SRC + f".o{orient}"
    open(dst, "wb").write(data)
    print(f"wrote {dst} (orientation {orient})")


if __name__ == "__main__":
    main()
