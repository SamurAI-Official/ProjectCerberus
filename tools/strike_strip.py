"""One strip: every strike, on the frame its hitbox is live, in L/M/H order.

    python3 tools/strike_strip.py [fighter]

Writes build/strike_strip.png. The active frame is the one the builder will put
the hitbox on, so this is the picture of what the game will test -- which is the
thing worth looking at, not the frame that looks best.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import build_fighter as bf  # noqa: E402

ORDER = ["1punch", "2punch", "3punch", "1kick", "2kick", "3kick", "special", "special_lite"]
GUTTER = 6

fighter = sys.argv[1] if len(sys.argv) > 1 else "tsu_ibano"
sheet = json.loads((REPO_ROOT / "design_sheets" / f"{fighter}.json").read_text())
counts = {s: c for s, c, _d, _b, _k, _p in bf.STATE_SPEC}
canvas = {s: bf.BOXES[b] for s, _c, _d, b, _k, _p in bf.STATE_SPEC}

frames = []
for state in ORDER:
    index, trigger, _box = bf.strike_box(state, counts[state], sheet.get("profile", {}), canvas[state])
    image = Image.open(REPO_ROOT / "data" / fighter / f"{state}{index:02d}.png").convert("RGBA")
    frames.append((state, trigger, index, image))

width = sum(f[3].width for f in frames) + GUTTER * (len(frames) + 1)
height = max(f[3].height for f in frames) + GUTTER * 2
strip = Image.new("RGBA", (width, height), (30, 30, 38, 255))

x = GUTTER
for state, trigger, index, image in frames:
    strip.alpha_composite(image, (x, GUTTER))
    print(f"{state:13} frame {index}  {trigger}")
    x += image.width + GUTTER

out = REPO_ROOT / "build" / "strike_strip.png"
out.parent.mkdir(parents=True, exist_ok=True)
strip.save(out)
print(f"\nwrote {out}  ({strip.width}x{strip.height})")
print("order left to right: " + ", ".join(ORDER))
