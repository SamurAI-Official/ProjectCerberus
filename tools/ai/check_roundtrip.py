#!/usr/bin/env python3
"""Round-trip a figure through the AI post-process and check it lands where it started.

    python3 tools/ai/check_roundtrip.py tsu_ibano

Builds a fake *generator output* -- our own figure drawn with the ControlNet's
exact camera, on a white background, at 1024x1024 -- pushes it through
`to_sprite.py`, and asserts the sprite that comes out still has its feet on the
engine's ground and its crown where `figure` puts it.

Why this earns a test rather than a glance: the registration is two constants
(`openpose_render.FRAME_UNITS`, `GROUND_FRACTION`) and one ratio. Change any of
them and every generated frame silently slides or scales against its hitboxes --
the art still renders, still animates, and is quietly wrong. That is the kind of
bug you find a month later, on a frame you were not looking at. This finds it in
a second, with no GPU and no ComfyUI.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "ai"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import build_fighter  # noqa: E402
import figure  # noqa: E402
import openpose_render  # noqa: E402
import to_sprite  # noqa: E402

# How far the measured silhouette may sit from where figure.pose() put the
# skeleton, in engine units.
#
# The two bounds differ because the two ends of the figure do. The crown is the
# top of a head drawn as an ellipse whose radius scales with PX_PER_UNIT, so it
# is a clean scale check and can be held tight. The feet are the end of a *leg
# stroke*: `figure.pose` places the ankle joint anywhere from ~0.5 to ~1.3 units
# above the ground line depending on the pose, and the visible foot is that joint
# plus half a stroke width, so the silhouette bottom is a property of the pose's
# angles rather than a constant. Holding it to the same bound would just be
# asserting today's leg angles.
CROWN_TOLERANCE = 0.8
FOOT_TOLERANCE = 1.0


def fake_render(skeleton, palette, size=1024):
    """Our figure at game scale, on the ControlNet's camera, upscaled to `size`.

    Rendered at `figure.PX_PER_UNIT` and *then* upscaled, rather than drawn
    directly at the control camera's 25.6 px/unit. `figure.render`'s stroke
    widths are in absolute pixels, so drawing at 4x the scale gives limbs whose
    outlines are four times thinner relative to the body than the game's own
    frames have -- and the foot positions this test checks are exactly the
    difference between a joint and the stroke that reaches past it. Upscaling a
    game-scale render keeps those proportions honest, which is the entire point
    of a round trip.
    """
    window = int(figure.PX_PER_UNIT * openpose_render.FRAME_UNITS)
    ground_row = window * openpose_render.GROUND_FRACTION
    # figure.render centres the origin on the canvas, so the canvas has to be
    # twice as tall as the ground line; cropping the window back out of the top
    # then leaves the origin at GROUND_FRACTION of the way down, where the
    # control image has it.
    drawn = figure.render(skeleton, (window, int(round(2 * ground_row))), palette)
    drawn = drawn.crop((0, 0, window, window))

    flat = Image.new("RGB", (window, window), (255, 255, 255))
    flat.paste(drawn, (0, 0), drawn)
    return flat.resize((size, size), Image.LANCZOS)


def check(fighter_id):
    path = REPO_ROOT / "design_sheets" / f"{fighter_id}.json"
    sheet = json.loads(path.read_text(encoding="utf-8"))
    palette = figure.Palette(sheet["palette16"])
    roles, colours = to_sprite.load_palette(sheet)
    profile = sheet.get("profile", {})
    counts = {state: count for state, count, *_ in build_fighter.STATE_SPEC}

    print(f"round-tripping {fighter_id} through the sprite post-process")
    failures = 0

    for state, index in [("idle", 0), ("1punch", 2)]:
        skeleton = figure.pose(**build_fighter.POSES[state](index, counts[state], profile))
        expected_crown = figure.HEAD_Y + figure.HEAD_R
        expected_feet = figure.GROUND_Y

        with tempfile.TemporaryDirectory() as scratch:
            raw_path = Path(scratch) / f"{state}{index:02d}.png"
            fake_render(skeleton, palette).save(raw_path)
            image, census = to_sprite.render_sprite(raw_path, sheet, roles, colours, state)

        measured = census["silhouette"]
        canvas = census["canvas"]
        want_canvas = to_sprite.canvas_for(state)

        problems = []
        if canvas != list(want_canvas):
            problems.append(f"canvas {canvas}, STATE_SPEC declares {list(want_canvas)}")
        if census["colours"] > len(roles):
            problems.append(f"{census['colours']} colours, budget {len(roles)}")
        if not measured:
            problems.append("empty silhouette -- nothing was drawn")
        else:
            if abs(measured["feet"] - expected_feet) > FOOT_TOLERANCE:
                problems.append(f"feet at {measured['feet']:+.2f}, expected "
                                f"{expected_feet:+.2f} within {FOOT_TOLERANCE}")
            if abs(measured["crown"] - expected_crown) > CROWN_TOLERANCE:
                problems.append(f"crown at {measured['crown']:+.2f}, expected "
                                f"{expected_crown:+.2f} within {CROWN_TOLERANCE}")

        if problems:
            failures += len(problems)
            for problem in problems:
                print(f"  FAIL  {state}{index:02d}: {problem}")
        else:
            print(f"  OK    {state}{index:02d}  {canvas[0]}x{canvas[1]}  "
                  f"{census['colours']:2d} colours  "
                  f"feet {measured['feet']:+.2f} crown {measured['crown']:+.2f} "
                  f"(expected {expected_feet:+.2f} / {expected_crown:+.2f})")

    print(f"\n{failures} problem(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(check(sys.argv[1] if len(sys.argv) > 1 else "tsu_ibano"))
