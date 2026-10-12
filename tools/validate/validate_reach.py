#!/usr/bin/env python3
"""Validate that a strike's art actually reaches the hitbox derived from its pose.

    python3 tools/validate/validate_reach.py
    python3 tools/validate/validate_reach.py tsu_ibano --dir build/ai/refA/sprite

`strike_box` in build_fighter.py puts a move's offense box out where the *skeleton's* striking
joint reaches -- 2punch's far hand at +12.4 units, so its box runs from +6 to about +16. That is
sound while the art and the skeleton are one thing, which is true of the puppet: `figure.render`
draws the skeleton. It is exactly what an AI arm can break, and one did: every frame of the
reference arm reproduces the *design sheet's* standing figure (front reach +5.5..+6.0 units) while
the skeleton it was conditioned on puts the punching hand at +12.4, so the box covers space no limb
is drawn in. Nothing else in this repository can see that -- `validate_boxes.py` checks that the art
fits *inside* its texture, `frame_fidelity.py` compares a render against the image it was
conditioned on (for that arm, the sheet, so "kept the drawing" reads as "kept the pose"), and the
hitboxes are derived from the skeleton, which is not in question.

So this is the missing direction of the same check: the art has to reach *out* to the box as well as
fit inside the texture. For each strike state it measures the sprite's furthest-forward ink, in
engine units, and compares it against the striking joint's position in the frozen pose table.

Exit code 0 when every strike's art reaches its box, 1 otherwise.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "ai"))

import build_fighter  # noqa: E402
import figure  # noqa: E402
import frame_fidelity  # noqa: E402

TABLE_PATH = REPO_ROOT / "design_sheets" / "poses" / "pose_table.json"

# How far short of the joint the ink may stop. A limb has thickness: the drawn hand is a blob
# centred on the joint, and the *outline* of that blob reaches a little behind the joint's centre,
# so the puppet's own art finishes 0.2 units short of `hand_far` on its best frame. 1.5 units is a
# third of the figure's body width, which is as much as a limb's own width can excuse.
REACH_TOLERANCE = 1.5


def art_front(path: Path) -> float:
    """The sprite's furthest-forward ink, in engine units, or nan for an empty frame."""
    mask = frame_fidelity.mask_of(Image.open(path))
    rows, cols = np.nonzero(mask)
    if not len(rows):
        return float("nan")
    return (cols.max() - mask.shape[1] / 2.0) / figure.PX_PER_UNIT


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    fighters = [argv[0]] if argv and not argv[0].startswith("-") else \
        sorted(path.stem for path in (REPO_ROOT / "design_sheets").glob("*.json"))
    override = None
    if "--dir" in argv:
        override = Path(argv[argv.index("--dir") + 1])

    if not TABLE_PATH.is_file():
        raise SystemExit(f"no pose table at {TABLE_PATH.relative_to(REPO_ROOT)}: run "
                         "tools/pipeline/pose_table.py --write")
    table = json.loads(TABLE_PATH.read_text(encoding="utf-8"))

    print(f"validating that each strike's art reaches its box (tolerance "
          f"{REACH_TOLERANCE:.1f} units)")
    failures = 0
    for fighter in fighters:
        frames_dir = override if override else REPO_ROOT / "data" / fighter
        states = table.get(fighter, {}).get("states", {})
        strikes = [(name, entry) for name, entry in sorted(states.items())
                   if "strike" in entry]
        if not strikes:
            print(f"  note  {fighter} has no strike in the pose table; nothing to check")
            continue

        checked = 0
        for name, entry in strikes:
            joint = build_fighter.STRIKES[name][1]
            active = entry["strike"]["frame"]
            path = frames_dir / f"{name}{active:02d}.png"
            if not path.is_file():
                built = sorted(frames_dir.glob(f"{name}*.png"))
                if built:
                    print(f"  FAIL  {fighter}/{name}: the box is placed on frame {active:02d}, "
                          f"and only {', '.join(p.name for p in built)} exist -- the strike is "
                          f"unchecked, which is not the same as correct")
                    failures += 1
                continue
            reach = entry["joints"][active][joint][0]
            front = art_front(path)
            checked += 1
            if np.isnan(front):
                print(f"  FAIL  {fighter}/{path.name} ({name}) is empty: no art to reach "
                      f"{reach:.1f} units with")
                failures += 1
            elif front < reach - REACH_TOLERANCE:
                print(f"  FAIL  {fighter}/{path.name} ({name}) reaches {front:.1f} units, but "
                      f"'{joint}' is at {reach:.1f} and the box starts at +6.0 -- the offense box "
                      f"is out where no limb is drawn")
                failures += 1
            else:
                print(f"  OK    {fighter}/{path.name} ({name}) reaches {front:.1f} against "
                      f"'{joint}' at {reach:.1f}")
        if not checked:
            print(f"  note  {fighter} is not built under {frames_dir}; nothing to check")

    if not failures:
        print("  every strike's art reaches the joint its box was derived from")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
