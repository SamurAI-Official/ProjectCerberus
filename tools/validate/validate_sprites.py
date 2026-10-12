#!/usr/bin/env python3
"""Check a directory of finished sprites against the contract the engine assumes.

    python3 tools/validate/validate_sprites.py data/tsu_ibano
    python3 tools/validate/validate_sprites.py build/ai/tsu_ibano/sprite --fighter tsu_ibano

Three things, and they are the three a scratch directory gets wrong: every frame is
the canvas size its state declares in `design_sheets/poses/pose_table.json`, no frame
has art on its own border (art there is art the texture cut off), and no frame is over
the sixteen-colour budget the engine's palette swap assumes.

`validate_manifest.py` checks the same things for `data/<fighter>/`, but it reads the
manifest, so it can only be run after an install. This one reads the frames, which is
what you have while a generated batch is still a scratch directory -- and it is the
cheaper place to find a clipped frame, because the fix belongs to the run's `--bound`
rather than to the install.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
COLOUR_BUDGET = 16
FIGHTERS = ("tsu_ibano", "fei_young")


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("directory", help="a directory of <state><n>.png frames")
    parser.add_argument("--fighter", choices=FIGHTERS, default=None,
                        help="whose pose table to check against; inferred from the "
                             "directory name when it is named after a fighter")
    return parser.parse_args(argv)


def infer_fighter(directory):
    for fighter in FIGHTERS:
        if fighter in str(directory):
            return fighter
    return None


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    sprite_dir = Path(args.directory)
    if not sprite_dir.is_dir():
        raise SystemExit(f"not a directory: {sprite_dir}")
    fighter = args.fighter or infer_fighter(sprite_dir)
    if fighter is None:
        raise SystemExit("cannot tell whose frames these are: pass --fighter "
                         + "|".join(FIGHTERS))
    table = json.loads((REPO_ROOT / "design_sheets" / "poses" / "pose_table.json")
                       .read_text(encoding="utf-8"))[fighter]["states"]

    failures = 0
    paths = sorted(sprite_dir.glob("*.png"))
    for path in paths:
        state = path.stem.rstrip("0123456789")
        if state not in table:
            print(f"  FAIL {path.stem:12s} '{state}' is not a state in the pose table")
            failures += 1
            continue
        expected = tuple(table[state]["canvas"])
        image = Image.open(path)
        rgba = np.asarray(image.convert("RGBA"))
        alpha = rgba[:, :, 3]
        # Opaque pixels only, and RGB rather than RGBA: this is what
        # `validate_manifest.frame_colours` counts, so the scratch check and the build
        # gate agree on what "seventeen colours" means. Counting every RGBA value
        # instead reports 17 for a perfect frame, because the empty pixels are a value
        # too.
        colours = len({tuple(px[:3]) for px in rgba.reshape(-1, 4).tolist() if px[3] > 0})
        border = (int((alpha[0, :] > 0).sum()) + int((alpha[-1, :] > 0).sum())
                  + int((alpha[:, 0] > 0).sum()) + int((alpha[:, -1] > 0).sum()))

        problems = []
        if image.size != expected:
            problems.append(f"{image.size[0]}x{image.size[1]} but '{state}' declares "
                            f"{expected[0]}x{expected[1]}")
        if border:
            problems.append(f"{border} pixel(s) of art on its own border -- clipped "
                            f"by the texture")
        if colours > COLOUR_BUDGET:
            problems.append(f"{colours} colours, over the {COLOUR_BUDGET} budget")
        if problems:
            failures += 1
            print(f"  FAIL {path.stem:12s} " + "; ".join(problems))
        else:
            print(f"  OK   {path.stem:12s} {image.size[0]}x{image.size[1]}, "
                  f"{colours} colours")

    print(f"\n{len(paths)} sprite(s) under {sprite_dir}, {failures} problem(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
