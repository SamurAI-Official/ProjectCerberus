#!/usr/bin/env python3
"""Render our authoritative fighter skeletons as OpenPose control images.

    python3 tools/ai/openpose_render.py tsu_ibano --state idle --out /tmp/poses
    python3 tools/ai/openpose_render.py tsu_ibano --out /tmp/poses

Writes `<out>/<state><NN>.png`: black background, OpenPose BODY_18 colour coding
-- the conditioning format the SDXL openpose ControlNets were trained on.

Why we do not run Openpose_Detector_Preprocessor
-----------------------------------------------
The obvious workflow -- and the one the RPG project's
`taldor_sdxl_controlnet.json` uses -- runs a pose *detector* over a reference
picture. That makes the pose a black box's guess at a drawing: it costs an extra
pass, it is non-deterministic, and, fatally for a fighting game, the pose it
recovers has no relationship to the boxes the engine actually resolves. A punch
whose art reaches x=13 but whose hitbox was authored against a different pose is
a game that lies to the player about its own reach.

We do not have to guess. `figure.pose()` already returns the exact skeleton the
renderer draws, in engine units, for every frame of every state. This module
projects that skeleton into OpenPose's encoding, so the conditioning image and
the hitboxes descend from one source of truth and a pose is reproducible from a
state name and a frame index.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import build_fighter  # noqa: E402
import figure  # noqa: E402

SHEET_DIR = REPO_ROOT / "design_sheets"

# Canonical OpenPose BODY_18 (COCO-18) joint order. This is the encoding the
# SDXL openpose ControlNets were trained against; the indices are fixed by the
# trained model, so this tuple is not ours to reorder.
JOINTS = (
    "nose", "neck",
    "right_shoulder", "right_elbow", "right_wrist",
    "left_shoulder", "left_elbow", "left_wrist",
    "right_hip", "right_knee", "right_ankle",
    "left_hip", "left_knee", "left_ankle",
    "right_eye", "left_eye", "right_ear", "left_ear",
)

# Limb segments as 0-based pairs into JOINTS, in the order the reference
# implementation draws them -- the colours are position-indexed, so a different
# order would recolour the skeleton into something the net has never seen.
#
# The reference (and OpenPose itself) lists these 1-based as `limbSeq` and
# dereferences with `limbSeq[i] - 1`. Ours are converted to 0-based here and
# dereferenced raw, because a 0 sitting in a list that gets `- 1`ed does not
# fail -- it silently reads the LAST joint. That is exactly how the first version
# of this file drew a bone from the nose to the left ear while still looking
# plausible at a glance, so the range check below is not ceremony.
LIMBS = (
    (1, 2), (1, 5), (2, 3), (3, 4), (5, 6), (6, 7),
    (1, 8), (8, 9), (9, 10), (1, 11), (11, 12), (12, 13), (1, 0),
)

if any(not 0 <= joint < len(JOINTS) for limb in LIMBS for joint in limb):
    raise ValueError("LIMBS must hold 0-based indices into JOINTS")

# OpenPose's own 18-entry demo palette, in RGB.
COLORS = (
    (255, 0, 0), (255, 85, 0), (255, 170, 0), (255, 255, 0), (170, 255, 0),
    (85, 255, 0), (0, 255, 0), (0, 255, 85), (0, 255, 170), (0, 255, 255),
    (0, 170, 255), (0, 85, 255), (0, 0, 255), (85, 0, 255), (170, 0, 255),
    (255, 0, 255), (255, 0, 170), (255, 0, 85),
)

# The reference draws limbs bright, dims the whole canvas, then draws joints at
# full brightness on top. That contrast is what the net reads as joint-vs-bone;
# skipping the dim pass produces a skeleton it recognises far less reliably.
LIMB_DIM = 0.6
STICK_RADIUS = 4   # of a 512 px image, per the reference implementation
JOINT_RADIUS = 4   # ditto
REFERENCE_SIZE = 512

FRAME_UNITS = 40.0
GROUND_FRACTION = 0.90

# Which of our named skeleton points fills each OpenPose joint. Our skeleton has
# one head point -- at 64x121 the face is a handful of pixels -- but OpenPose
# wants eyes and ears, so those are derived below. `_far`/`_near` are the two
# sides of the side-view body; OpenPose wants left/right and either assignment
# trains the same, so the mapping is fixed once, here, and is reviewable.
SIDE_MAP = {
    "nose": "head",
    "neck": "neck",
    "right_shoulder": "shoulder_far",
    "right_elbow": "elbow_far",
    "right_wrist": "hand_far",
    "left_shoulder": "shoulder_near",
    "left_elbow": "elbow_near",
    "left_wrist": "hand_near",
    "right_hip": "hip_far",
    "right_knee": "knee_far",
    "right_ankle": "foot_far",
    "left_hip": "hip_near",
    "left_knee": "knee_near",
    "left_ankle": "foot_near",
}

# Derived face joints, in engine units from the head point. The fighter faces +x,
# so both eyes sit forward of the head centre and both ears behind it. Without
# them the net is handed a bare head and invents its own facing.
FACE_OFFSETS = {
    "right_eye": (0.95, 0.35),
    "left_eye": (0.25, 0.35),
    "right_ear": (-0.45, 0.25),
    "left_ear": (-1.70, 0.05),
}


def joint_points(skeleton):
    """Our named skeleton -> the 18 OpenPose joints, still in engine units."""
    points = {joint: skeleton[source] for joint, source in SIDE_MAP.items()}
    head_x, head_y = skeleton["head"]
    for joint, (dx, dy) in FACE_OFFSETS.items():
        points[joint] = (head_x + dx, head_y + dy)
    return points


def project(point, size):
    """Engine units (+y up, origin at the feet) -> image pixels (+y down).

    One fixed window for every pose. Varying the framing between frames would
    read to the net as the character changing size, which is precisely the bug
    the sprite spec exists to prevent.
    """
    scale = size / FRAME_UNITS
    return (size / 2.0 + point[0] * scale,
            size * GROUND_FRACTION - point[1] * scale)


def _capsule(draw, a, b, colour, radius):
    """A thick segment with rounded ends.

    PIL's `joint="curve"` alone is not enough: a limb shorter than its own width
    degrades to a blob, and the short stubs of a tucked airborne or grounded pose
    hit exactly that case, so the round caps are load-bearing.
    """
    draw.line([a, b], fill=colour, width=int(radius * 2), joint="curve")
    for point in (a, b):
        draw.ellipse([point[0] - radius, point[1] - radius,
                      point[0] + radius, point[1] + radius], fill=colour)


def render_pose(skeleton, size=1024):
    """Draw one OpenPose control image. Returns an RGB image."""
    scale = size / float(REFERENCE_SIZE)
    stick = STICK_RADIUS * scale
    joint_r = JOINT_RADIUS * scale

    pixels = {joint: project(point, size)
              for joint, point in joint_points(skeleton).items()}

    # Limbs go on their own layer so they can be dimmed as a group before the
    # joints land -- dimming afterwards would dim the joints too, and the
    # bright-joint/dim-bone contrast is most of what makes the encoding legible
    # to the net.
    bones = Image.new("RGB", (size, size), (0, 0, 0))
    bones_draw = ImageDraw.Draw(bones)
    for index, (a, b) in enumerate(LIMBS):
        _capsule(bones_draw, pixels[JOINTS[a]], pixels[JOINTS[b]],
                 COLORS[index], stick)
    bones = bones.point(lambda value: int(value * LIMB_DIM))

    image = Image.new("RGB", (size, size), (0, 0, 0))
    image = ImageChops.lighter(image, bones)

    joints_draw = ImageDraw.Draw(image)
    for index, joint in enumerate(JOINTS):
        x, y = pixels[joint]
        joints_draw.ellipse([x - joint_r, y - joint_r, x + joint_r, y + joint_r],
                            fill=COLORS[index])
    return image


def load_sheet(fighter_id):
    path = SHEET_DIR / f"{fighter_id}.json"
    if not path.is_file():
        raise SystemExit(f"no design sheet for '{fighter_id}' at {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def select_states(wanted):
    """STATE_SPEC entries filtered by state name (None = every state).

    Order and contents come from build_fighter.STATE_SPEC, so the pose set cannot
    drift out of step with the frame set the game is actually built from.
    """
    if not wanted:
        return list(build_fighter.STATE_SPEC)

    known = {state for state, *_ in build_fighter.STATE_SPEC}
    unknown = [name for name in wanted if name not in known]
    if unknown:
        raise SystemExit("unknown state(s): %s\nknown: %s"
                         % (", ".join(unknown), ", ".join(sorted(known))))
    return [entry for entry in build_fighter.STATE_SPEC if entry[0] in wanted]


def write_poses(fighter_id, out_dir, states=None, size=1024, limit=None):
    """Write the control image for every selected frame. Returns the paths."""
    sheet = load_sheet(fighter_id)
    profile = sheet.get("profile", {})
    out_dir.mkdir(parents=True, exist_ok=True)

    written = []
    for state, count, _delay, _box, _continual, pose_name in select_states(states):
        builder = build_fighter.POSES.get(pose_name, build_fighter.POSES["idle"])
        for index in range(count):
            if limit is not None and len(written) >= limit:
                return written
            skeleton = figure.pose(**builder(index, count, profile))
            path = out_dir / f"{state}{index:02d}.png"
            render_pose(skeleton, size).save(path)
            written.append(path)

    return written


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("fighter", help="design sheet id, e.g. tsu_ibano")
    parser.add_argument("--state", default=None,
                        help="comma-separated states (default: every state)")
    parser.add_argument("--out", required=True, help="output directory")
    parser.add_argument("--size", type=int, default=1024, help="square image size")
    parser.add_argument("--limit", type=int, default=None, help="stop after N images")
    args = parser.parse_args(argv)

    states = None if not args.state else [
        name.strip() for name in args.state.split(",") if name.strip()]
    written = write_poses(args.fighter, Path(args.out), states, args.size, args.limit)

    print(f"{args.fighter}: {len(written)} control image(s) at {args.size}px -> {args.out}")
    for path in written[:6]:
        print(f"  {path.name}")
    if len(written) > 6:
        print(f"  ... +{len(written) - 6} more")
    return 0


if __name__ == "__main__":
    sys.exit(main())
