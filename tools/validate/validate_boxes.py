#!/usr/bin/env python3
"""Validate that every frame's declared box actually contains its art.

    python3 tools/validate/validate_boxes.py

The box in STATE_SPEC is both the size of the frame texture and the logical size
the engine draws it at. PIL clips drawing at the canvas edge, so a box narrower
than the figure does not error -- it shears the fighter off flat at the boundary.
That is exactly what had been happening: BODY_BOX was 16 units wide against poses
reaching 13.5 units from the origin, so 86 of 117 frames had art sitting on the
texture edge and the idle guard arm had lost its hand. The reference Ryu art
clips on 4 frames of 143, so a margin is the intended behaviour, not a luxury.

Two checks, because they fail independently:

  * **Source.** Every pose is rendered into an oversized canvas and measured, and
    the declared box must contain the result with a pixel to spare. This catches a
    pose that outgrew its box before anything gets built.
  * **Artifacts.** Every built PNG must be exactly box * PX_PER_UNIT, and must not
    have opaque pixels on its own border. This catches a stale build.

Both widths were widened to satisfy this once; the numbers are in build_fighter.

Exit code 0 when every frame fits, 1 otherwise, so this can gate a build.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import build_fighter  # noqa: E402
import figure  # noqa: E402

SHEET_DIR = REPO_ROOT / "design_sheets"

# Render poses into a canvas this many engine units per side. The origin sits at
# the centre, so nothing a fighter does reaches +-32 units and the measurement is
# of the drawing, not of the crop.
MEASURE_UNITS = 64

# Require at least this much empty canvas between the outermost art and the edge.
# One pixel is the floor: art exactly on the boundary is already at risk from any
# future rounding, and the reference keeps whole pixels of margin.
MARGIN_PX = 1


def fail(message: str) -> None:
    print(f"  FAIL  {message}")


def measure(sheet: dict) -> dict:
    """Widest extent of every pose, in engine units from the origin.

    Returns {state: {front, back, crown, feet, frame}}, where each value is the
    largest over that state's frames and `frame` names the frame that set it.
    """
    palette = figure.Palette(sheet["palette16"])
    profile = sheet.get("profile", {})
    canvas = (MEASURE_UNITS * figure.PX_PER_UNIT, MEASURE_UNITS * figure.PX_PER_UNIT)
    half = canvas[0] / 2
    scale = float(figure.PX_PER_UNIT)

    worst = {}
    for state, count, _delay, _box, _continual, pose_name in build_fighter.STATE_SPEC:
        builder = build_fighter.POSES.get(pose_name, build_fighter.POSES["idle"])
        for index in range(count):
            skeleton = figure.pose(**builder(index, count, profile))
            solid = np.asarray(figure.render(skeleton, canvas, palette))[:, :, 3] > 0
            rows, cols = np.nonzero(solid)
            extent = {
                "front": (cols.max() - half) / scale,
                "back": (half - cols.min()) / scale,
                "crown": (canvas[1] / 2 - rows.min()) / scale,
                "feet": (canvas[1] / 2 - rows.max()) / scale,
                "frame": f"{state}{index:02d}",
            }
            if state not in worst:
                worst[state] = extent
                continue
            for key in ("front", "back", "crown", "feet"):
                if extent[key] > worst[state][key]:
                    worst[state][key] = extent[key]
                    worst[state]["frame"] = extent["frame"]
    return worst


def check_source(sheet: dict, failures: int) -> int:
    """Every pose must fit the box its own state declares."""
    worst = measure(sheet)
    label = sheet["id"]
    before = failures

    for state, _count, _delay, box, _continual, _pose in build_fighter.STATE_SPEC:
        box_width, box_height = build_fighter.BOXES[box]
        slack = MARGIN_PX / figure.PX_PER_UNIT
        allowed_x = box_width / 2 - slack
        allowed_y = box_height / 2 - slack
        extent = worst[state]

        over = []
        for key, allowed in (("front", allowed_x), ("back", allowed_x),
                             ("crown", allowed_y), ("feet", allowed_y)):
            if extent[key] > allowed:
                over.append(f"{key} {extent[key]:.2f} > {allowed:.2f}")

        if over:
            fail(f"{label}/{extent['frame']} ({state}) leaves its '{box}' box "
                 f"{box_width}x{box_height}: {', '.join(over)}")
            failures += 1

    if failures == before:
        print(f"  OK    {label} every pose fits its declared box")
    return failures


def check_artifacts(sheet: dict, failures: int) -> int:
    """Built frames must be the declared size and must not touch their border."""
    label = sheet["id"]
    frames_dir = REPO_ROOT / "data" / label
    if not frames_dir.is_dir():
        print(f"  note  {label} is not built; skipping the artifact check")
        return failures

    boxes = {}
    for state, count, _delay, box, _continual, _pose in build_fighter.STATE_SPEC:
        for index in range(count):
            boxes[f"{state}{index:02d}"] = build_fighter.BOXES[box]

    checked = 0
    before = failures
    for name, (box_width, box_height) in sorted(boxes.items()):
        path = frames_dir / f"{name}.png"
        if not path.is_file():
            continue
        checked += 1

        image = Image.open(path)
        expected = (box_width * figure.PX_PER_UNIT, box_height * figure.PX_PER_UNIT)
        if image.size != expected:
            fail(f"{label}/{name}.png is {image.size[0]}x{image.size[1]}, but its "
                 f"'{box_width}x{box_height}' box is {expected[0]}x{expected[1]}")
            failures += 1
            continue

        border = np.asarray(image.convert("RGBA"))[:, :, 3]
        touching = (int((border[0, :] > 0).sum()) + int((border[-1, :] > 0).sum())
                    + int((border[:, 0] > 0).sum()) + int((border[:, -1] > 0).sum()))
        if touching:
            fail(f"{label}/{name}.png has {touching} pixel(s) of art on its border "
                 f"-- the figure is clipped by the texture")
            failures += 1

    if checked and failures == before:
        print(f"  OK    {label} all {checked} built frames sit inside their texture")
    return failures


def main() -> int:
    print(f"validating sprite boxes under {REPO_ROOT}")
    failures = 0

    sheets = sorted(SHEET_DIR.glob("*.json"))
    if not sheets:
        fail(f"no design sheets in {SHEET_DIR}")
        return 1

    for path in sheets:
        sheet = json.loads(path.read_text(encoding="utf-8"))
        failures = check_source(sheet, failures)
        failures = check_artifacts(sheet, failures)

    if failures == 0:
        return 0
    print(f"  {failures} problem(s) found")
    return 1


if __name__ == "__main__":
    sys.exit(main())
