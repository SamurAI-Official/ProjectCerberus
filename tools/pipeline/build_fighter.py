#!/usr/bin/env python3
"""Build a complete playable fighter from a design sheet.

    python3 tools/pipeline/build_fighter.py design_sheets/tsu_ibano.json
    python3 tools/pipeline/build_fighter.py --all

Writes `data/<id>/<state><NN>.png` and `data/<id>/<id>.yml` plus `moves.yml`.

Frame geometry, and why it is not the fixture's
-----------------------------------------------
The engine scales the WHOLE texture into the box the YAML declares, so the
declared box's aspect has to match the canvas or the art comes out squashed.
The shipped fixture gets this wrong: the same idle00.png is declared `20x40` in
`start` and `12x30` in `idle`, and `1punch` puts a 128x128 canvas in a `12x30`
box. Its character therefore changes size between states.

This builder uses one rule instead: **4 px per engine unit, everywhere.**
Locomotion frames are a 16x32 box on a 64x128 canvas; frames that need the width
of an extended limb are a 32x32 box on a 128x128 canvas. Both canvas aspects
equal their declared box exactly (0.5 and 1.0), both render the figure at the
same scale, and neither can squash.

Hitboxes are therefore authored in our own convention rather than inherited:
a symmetric full-body hurtbox `x_pos=-6, y_pos=-16, 12x30`, which spans the
figure from the feet (-16) to the crown (+15). Upstream's boxes are offset
forward of the origin, which does not line up with their own centred art.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import figure  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
SHEET_DIR = REPO_ROOT / "design_sheets"

# Box sizes, in engine units. Canvas = box * figure.PX_PER_UNIT.
BODY_BOX = (16, 32)   # 64x128 canvas
REACH_BOX = (32, 32)  # 128x128 canvas

FEET = -16.0
CROWN = 15.0
HURTBOX = {"x_pos": -6, "y_pos": FEET, "width": 12, "height": CROWN - FEET}

# The engine's trigger vocabulary, as `(state, trigger, from, to)`. `to` is the
# state a non-continual animation falls through to when it completes. This is
# transcribed from the shipped fixture so the fighters obey the same contract;
# states the vertical slice does not need (run, dash, grab/throw, duck_punch,
# jump_kick) are omitted, and every `from` that named them has been updated
# rather than left dangling.
ACTION_TABLE = [
    ("start",        "NONE",          "start",                              "idle"),
    ("idle",         "NONE",          "start",                              "idle"),
    ("turn",         "INVERT",        "idle,walk_back,walk_forward",        "idle"),
    ("walk_back",    "B",             "idle",                               "idle"),
    ("walk_forward", "F",             "idle",                               "idle"),
    ("stop_walk",    "~F,~B",         "walk_forward,walk_back",             "idle"),
    ("start_duck",   "DB,D",          "idle,walk_back,walk_forward",        "duck"),
    ("end_duck",     "NONE,~D",       "duck,duck_back",                     "idle"),
    ("duck",         "D",             "duck_back",                          "idle"),
    ("duck_back",    "DB",            "duck",                               "idle"),
    ("jump",         "U",             "idle,walk_back,walk_forward,duck",   "idle"),
    ("jump_forward", "UF",            "idle,walk_forward,duck",             "idle"),
    ("jump_forward", "U",             "walk_forward",                       "idle"),
    ("jump_back",    "UB",            "idle,walk_back,duck",                "idle"),
    ("jump_back",    "U",             "walk_back",                          "idle"),
    ("block_low",    "HIT_L,HIT_M",   "duck_back",                          "duck_back"),
    ("block_high",   "HIT_H,HIT_M",   "walk_back",                          "idle"),
    ("hurt_mid",     "HIT_M",         "idle,walk_forward,walk_back,1punch,2punch,kick,back_kick,special", "idle"),
    ("hurt_high",    "HIT_H",         "idle,duck,duck_back,walk_forward,1punch,2punch,kick,back_kick,special", "idle"),
    ("hurt_low",     "HIT_L",         "idle,walk_back,duck,1punch,2punch,kick,back_kick,special", "idle"),
    ("hurt_air",     "HIT_L,HIT_M,HIT_H", "knocked_down,jump,jump_back,jump_forward,hurt_air", "ground"),
    ("1punch",       "LP",            "idle,walk_back,walk_forward",        "idle"),
    ("2punch",       "MP",            "idle,walk_back,walk_forward,1punch", "idle"),
    ("back_kick",    "MK",            "idle,walk_back,walk_forward",        "idle"),
    ("kick",         "LK",            "idle,walk_back,walk_forward,2punch", "idle"),
    ("special",      "QCF_HP",        "idle,walk_forward,1punch",           "idle"),
    ("knocked_down", "KNOCK_DOWN",    "idle,knocked_down",                  "idle"),
    ("hit_ground",   "GROUND",        "hurt_air,knocked_down",              "ground"),
    ("land",         "GROUND",        "jump,jump_back,jump_forward",        "idle"),
    ("ground",       "",              "hurt_air",                           "stand"),
    ("stand",        "",              "ground",                             "idle"),
]

# ---------------------------------------------------------------------------
# Poses. Each takes (frame_index, frame_count, profile) and returns kwargs for
# figure.pose(). Angles are degrees from straight-down, positive = the way the
# fighter faces.
# ---------------------------------------------------------------------------

def _wave(i, n, phase=0.0):
    """One full sine cycle across the frames -- for cycles and bobs."""
    return math.sin(2.0 * math.pi * (i / float(max(n, 1))) + phase)


def _walk(i, n, profile, direction):
    swing = 26.0 * _wave(i, n)
    return dict(
        crouch=0.07,
        lean=0.12 * direction,
        leg_far=(swing, swing - 18.0),
        leg_near=(-swing, -swing - 18.0),
        arm_far=(14.0 - swing * 0.4, 26.0),
        arm_near=(-10.0 + swing * 0.4, 44.0),
    )


def _strike(extent, horizontal, vertical, lift):
    """Builds a strike pose: the far arm drives out to `horizontal` degrees while
    the elbow straightens, `extent` scaling how far past the shoulder it lands."""
    def build(i, n, profile):
        t = i / float(max(n - 1, 1))
        e = math.sin(math.pi * min(t / 0.55, 1.0)) * extent * profile.get("reach", 1.0)
        return dict(
            crouch=0.06 + 0.05 * (1.0 - e),
            lean=0.16 * e,
            torso_angle=vertical * e,
            arm_far=(38.0 + (horizontal - 38.0) * e, 108.0 + (92.0 - 108.0) * e),
            arm_near=(-22.0 + 20.0 * e, 62.0 - 14.0 * e),
            leg_far=(lift * 0.4, lift * 0.15 - 14.0),
            leg_near=(-10.0, -22.0),
        )
    return build


POSES = {
    "start":        lambda i, n, p: dict(crouch=0.06, arm_far=(12.0, 26.0), arm_near=(-10.0, 44.0)),
    "idle":         lambda i, n, p: dict(
        crouch=0.05 + 0.035 * _wave(i, n),
        lean=0.05 * _wave(i, n),
        arm_far=(16.0 + 3.0 * _wave(i, n), 28.0),
        arm_near=(-14.0 + 3.0 * _wave(i, n), 46.0),
        leg_far=(6.0, -12.0), leg_near=(-6.0, -24.0),
    ),
    "turn":         lambda i, n, p: dict(
        lean=-0.22 + 0.1 * i, crouch=0.12,
        arm_far=(4.0, 34.0), arm_near=(-18.0, 58.0),
    ),
    "walk_forward": lambda i, n, p: _walk(i, n, p, 1.0),
    "walk_back":    lambda i, n, p: _walk(i, n, p, -1.0),
    "stop_walk":    lambda i, n, p: dict(crouch=0.16, lean=-0.1, leg_far=(10.0, -8.0), leg_near=(-12.0, -26.0)),
    "start_duck":   lambda i, n, p: dict(crouch=0.75 * (i + 1) / n, leg_far=(22.0, 4.0), leg_near=(-6.0, -30.0)),
    "end_duck":     lambda i, n, p: dict(crouch=0.75 * (1.0 - (i + 1) / n), leg_far=(18.0, 2.0), leg_near=(-6.0, -26.0)),
    "duck":         lambda i, n, p: dict(
        crouch=0.82, lean=0.05 * _wave(i, n), leg_far=(24.0, 6.0), leg_near=(-8.0, -32.0),
        arm_far=(26.0, 40.0), arm_near=(-20.0, 56.0),
    ),
    "duck_back":    lambda i, n, p: dict(
        crouch=0.82, lean=-0.3, leg_far=(26.0, 8.0), leg_near=(-6.0, -30.0),
        arm_far=(34.0, 52.0), arm_near=(-28.0, 66.0),
    ),
    "jump":         lambda i, n, p: dict(
        airborne=1.0, leg_far=(38.0, 6.0), leg_near=(-12.0, -34.0),
        arm_far=(52.0, 66.0), arm_near=(-44.0, 74.0),
    ),
    "jump_forward": lambda i, n, p: dict(
        airborne=1.0, lean=0.3, leg_far=(50.0, 16.0), leg_near=(-24.0, -30.0),
        arm_far=(64.0, 74.0), arm_near=(-30.0, 60.0),
    ),
    "jump_back":    lambda i, n, p: dict(
        airborne=1.0, lean=-0.3, leg_far=(20.0, -6.0), leg_near=(-34.0, -18.0),
        arm_far=(40.0, 62.0), arm_near=(-56.0, 80.0),
    ),
    "block_high":   lambda i, n, p: dict(
        crouch=0.1 + 0.03 * _wave(i, n), lean=-0.24,
        arm_far=(96.0, 244.0), arm_near=(86.0, 238.0),
        leg_far=(14.0, -8.0), leg_near=(-14.0, -30.0),
    ),
    "block_low":    lambda i, n, p: dict(
        crouch=0.7 + 0.03 * _wave(i, n), lean=-0.16,
        arm_far=(92.0, 240.0), arm_near=(82.0, 234.0),
        leg_far=(24.0, 4.0), leg_near=(-8.0, -32.0),
    ),
    "hurt_mid":     lambda i, n, p: dict(
        lean=-0.45, torso_angle=-12.0, crouch=0.1,
        arm_far=(58.0, 78.0), arm_near=(-44.0, 72.0), head_shift=-1.4,
    ),
    "hurt_high":    lambda i, n, p: dict(
        lean=-0.6, torso_angle=-20.0, crouch=0.08,
        arm_far=(72.0, 86.0), arm_near=(-56.0, 80.0), head_shift=-2.0,
    ),
    "hurt_low":     lambda i, n, p: dict(
        lean=-0.36, torso_angle=-8.0, crouch=0.55,
        arm_far=(52.0, 72.0), arm_near=(-38.0, 66.0), head_shift=-1.0,
        leg_far=(26.0, 6.0), leg_near=(-10.0, -30.0),
    ),
    "hurt_air":     lambda i, n, p: dict(
        airborne=1.0, torso_angle=-58.0,
        arm_far=(84.0, 96.0), arm_near=(-70.0, 92.0),
        leg_far=(54.0, 20.0), leg_near=(-30.0, 10.0),
    ),
    "knocked_down": lambda i, n, p: dict(
        torso_angle=-80.0 - 4.0 * i, crouch=0.2,
        arm_far=(96.0, 104.0), arm_near=(-84.0, 100.0),
        leg_far=(74.0, 30.0), leg_near=(-46.0, 18.0),
    ),
    "hit_ground":   lambda i, n, p: dict(
        torso_angle=-86.0, crouch=0.15,
        arm_far=(100.0, 108.0), arm_near=(-88.0, 104.0),
        leg_far=(78.0, 34.0), leg_near=(-50.0, 22.0),
    ),
    "ground":       lambda i, n, p: dict(
        torso_angle=-88.0, crouch=0.12,
        arm_far=(102.0, 110.0), arm_near=(-90.0, 106.0),
        leg_far=(80.0, 36.0), leg_near=(-52.0, 24.0),
    ),
    "stand":        lambda i, n, p: dict(
        crouch=0.7 * (1.0 - i / float(max(n - 1, 1))),
        leg_far=(20.0, 0.0), leg_near=(-8.0, -28.0),
    ),
    "land":         lambda i, n, p: dict(
        crouch=0.66 - 0.2 * i, leg_far=(24.0, 4.0), leg_near=(-10.0, -30.0),
        arm_far=(34.0, 52.0), arm_near=(-28.0, 60.0),
    ),
    "1punch":       _strike(0.85, 88.0, 0.0, 0.0),
    "2punch":       _strike(1.0, 92.0, 0.0, 4.0),
    "kick":         _strike(0.9, 118.0, 0.0, 0.0),
    "back_kick":    _strike(1.0, 126.0, 6.0, 10.0),
    "special":      _strike(1.3, 96.0, 0.0, 6.0),
}

# ---------------------------------------------------------------------------
# Animation spec: (state, frames, delay, box, continual, pose). `box` picks the
# canvas: BODY is a 64x128 canvas in a 16x32 box, REACH a 128x128 canvas in a
# 32x32 box, both at 4 px per unit.
# ---------------------------------------------------------------------------

BODY, REACH = "body", "reach"

STATE_SPEC = [
    ("start",        1, 10, BODY,  False, "start"),
    ("idle",         6, 10, BODY,  True,  "idle"),
    ("turn",         3,  8, BODY,  False, "turn"),
    ("walk_forward", 8,  7, BODY,  True,  "walk_forward"),
    ("walk_back",    8,  7, BODY,  True,  "walk_back"),
    ("stop_walk",    2,  8, BODY,  False, "stop_walk"),
    ("start_duck",   2,  6, BODY,  False, "start_duck"),
    ("end_duck",     2,  6, BODY,  False, "end_duck"),
    ("duck",         2, 12, BODY,  True,  "duck"),
    ("duck_back",    2, 12, BODY,  True,  "duck_back"),
    ("jump",         5,  8, BODY,  False, "jump"),
    ("jump_forward", 8,  6, BODY,  False, "jump_forward"),
    ("jump_back",    5,  6, BODY,  False, "jump_back"),
    ("block_high",   2, 12, BODY,  True,  "block_high"),
    ("block_low",    2, 12, BODY,  True,  "block_low"),
    ("hurt_mid",     4,  7, BODY,  False, "hurt_mid"),
    ("hurt_high",    4,  7, BODY,  False, "hurt_high"),
    ("hurt_low",     4,  7, BODY,  False, "hurt_low"),
    ("hurt_air",     4,  7, REACH, False, "hurt_air"),
    ("knocked_down", 4,  9, REACH, False, "knocked_down"),
    ("hit_ground",   3,  8, REACH, False, "hit_ground"),
    ("land",         3,  7, BODY,  False, "land"),
    ("ground",       1, 20, REACH, True,  "ground"),
    ("stand",        3,  7, BODY,  False, "stand"),
    ("1punch",       4,  8, REACH, False, "1punch"),
    ("2punch",       6,  8, REACH, False, "2punch"),
    ("kick",         5,  8, REACH, False, "kick"),
    ("back_kick",    6,  8, REACH, False, "back_kick"),
    ("special",      8,  8, REACH, False, "special"),
]

# Per-frame physics. Only the states that move are listed; the rest stand still,
# which is what "no move block" means to the engine.
MOVES = {
    "walk_forward": lambda i, n, p: (0.34, 0.0),
    "walk_back":    lambda i, n, p: (-0.30, 0.0),
    "jump":         lambda i, n, p: (0.0, [3.0, 1.5, -0.7, -2.2, -2.6][min(i, 4)]),
    "jump_forward": lambda i, n, p: (0.62, [3.0, 1.6, -0.5, -2.0, -2.6, -2.6, -2.6, -2.6][min(i, 7)]),
    "jump_back":    lambda i, n, p: (-0.5, [3.0, 1.5, -0.7, -2.2, -2.6][min(i, 4)]),
    "back_kick":    lambda i, n, p: (0.20 if 1 <= i <= 4 else 0.0, 0.0),
    "special":      lambda i, n, p: (0.55 if 1 <= i <= 5 else 0.0, 0.0),
}

# Where each strike lands: (frame_index, trigger, offensive box). The trigger is
# the strength handed to the defender, and the DEFENDER's own state machine
# decides whether it becomes a hit or a block -- damage is applied by the engine
# at that single resolution point (see patches/openfight/0001).
#
# Boxes are in the frame's own units, measured from the player origin, extending
# forward. A punching hand lands near x=13 and a kick near x=18, so these are
# sized to the poses in POSES rather than guessed.
HITS = {
    "1punch":    [(2, "HIT_M", {"x_pos": 7, "y_pos": 5, "width": 7, "height": 6})],
    "2punch":    [(3, "HIT_H", {"x_pos": 7, "y_pos": 4, "width": 9, "height": 7})],
    "kick":      [(2, "HIT_M", {"x_pos": 11, "y_pos": -4, "width": 8, "height": 6})],
    "back_kick": [(3, "KNOCK_DOWN", {"x_pos": 11, "y_pos": -2, "width": 9, "height": 8})],
    "special":   [(4, "KNOCK_DOWN", {"x_pos": 9, "y_pos": 2, "width": 9, "height": 8})],
}

# The engine's shared hit-spark object, `type: temporary`, one frame set reused
# by every attack. Referenced rather than copied: it is engine-owned VFX data,
# like the ground collision.
HIT_VFX = "data/collision/collision.yml"

BOXES = {"body": BODY_BOX, "reach": REACH_BOX}


def render_frames(sheet, frames_dir):
    """Writes every frame of every state. Returns how many were written."""
    palette = {key: tuple(value) for key, value in sheet["palette"].items()}
    profile = sheet.get("profile", {})
    frames_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    for state, count, _delay, box, _continual, pose_name in STATE_SPEC:
        builder = POSES.get(pose_name, POSES["idle"])
        canvas = tuple(int(dim * figure.PX_PER_UNIT) for dim in BOXES[box])

        for index in range(count):
            skeleton = figure.pose(**builder(index, count, profile))
            figure.render(skeleton, canvas, palette).save(frames_dir / f"{state}{index:02d}.png")
            written += 1

    return written





def _num(value):
    """Engine-side floats are read with as<float>, but integers keep the file
    readable and diffable."""
    return str(int(value)) if float(value) == int(value) else f"{float(value):g}"


def write_character_yaml(sheet, out_path):
    identifier = sheet["id"]
    lines = [
        "character:",
        f"  name: {identifier}",
        "  type: player",
        f"  health: {sheet.get('health', 100)}",
        "  position:",
        "    x_pos: 0",
        "    y_pos: 30",
        "    alpha: 1.0",
        "    scale: 1",
        "  action:",
    ]

    for name, trigger, from_states, to_state in ACTION_TABLE:
        lines += [f"  - name: {name}", f"    trigger: {trigger}",
                  f"    from: {from_states}", f"    to: {to_state}"]

    lines.append("  animation:")

    for state, count, delay, box, continual, _pose in STATE_SPEC:
        box_width, box_height = BOXES[box]
        hits = {index: (trigger, offsets) for index, trigger, offsets in HITS.get(state, [])}

        lines.append(f"  - name: {state}")
        if continual:
            lines.append("    continual: true")
        # Hitboxes are drawn by the engine when this is true. Left on during
        # development so a pose and its boxes can be checked against each other;
        # flip it off for a presentation build.
        lines.append("    show_hitbox: true")
        lines.append("    frame:")

        for index in range(count):
            lines.append(f"    - path: data/{identifier}/{state}{index:02d}.png")
            lines.append(f"      width: {box_width}")
            lines.append(f"      height: {box_height}")
            lines.append(f"      delay: {delay}")

            move = MOVES.get(state)
            if move:
                x_vel, y_vel = move(index, count, sheet.get("profile", {}))
                lines += ["      move:", f"        x_vel: {_num(x_vel)}", f"        y_vel: {_num(y_vel)}"]

            lines += [
                "      defense:",
                f"        x_pos: {HURTBOX['x_pos']}",
                f"        y_pos: {HURTBOX['y_pos']}",
                f"        width: {HURTBOX['width']}",
                f"        height: {HURTBOX['height']}",
            ]

            if index in hits:
                trigger, offsets = hits[index]
                lines.append("      offense:")
                for key in ("x_pos", "y_pos", "width", "height"):
                    lines.append(f"        {key}: {offsets[key]}")
                lines += [
                    "      collision:",
                    f"        path: {HIT_VFX}",
                    f"        opponent: {trigger}",
                    "        x_pos: 0",
                    "        y_pos: 6",
                    "        index: 2",
                ]

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_moves_yaml(out_path):
    """The input-buffer table. Needed because a trigger the action table answers
    to that no key sequence ever produces is a state that can never be entered --
    the special move in particular."""
    motion = [
        ("F,~D,c", "QCF_HP"), ("F,~D,~c", "QCF_HP"),
    ]
    lines = ["moves:", "  move:"]
    for keys, trigger in motion:
        lines += [f"  - trigger: {trigger}", f"    keys: {keys}"]

    for keys, trigger in [
        ("/D,/B", "DB"), ("/B,/D", "DB"), ("D,B", "DB"), ("B,D", "DB"),
        ("/U,/B", "UB"), ("/B,/U", "UB"), ("U,B", "UB"), ("B,U", "UB"),
        ("/U,/F", "UF"), ("/F,/U", "UF"), ("U,F", "UF"), ("F,U", "UF"),
        ("/F", "F"), ("F", "F"), ("/B", "B"), ("B", "B"),
        ("/U", "U"), ("U", "U"), ("/D", "D"), ("D", "D"),
        ("~F", "~F"), ("~B", "~B"), ("~D", "~D"),
        ("a", "LP"), ("b", "MP"), ("c", "HP"), ("x", "LK"), ("y", "MK"), ("z", "HK"),
    ]:
        lines += [f"  - trigger: {trigger}", f"    keys: {keys}"]

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv):
    if len(argv) > 1 and argv[1] == "--all":
        sheets = sorted(SHEET_DIR.glob("*.json"))
    elif len(argv) > 1:
        sheets = [Path(argv[1])]
    else:
        print(__doc__, file=sys.stderr)
        return 2

    if not sheets:
        print(f"no design sheets in {SHEET_DIR}", file=sys.stderr)
        return 2

    total = 0
    print(f"building {len(sheets)} fighter(s)")
    for sheet_path in sheets:
        if not sheet_path.is_absolute():
            sheet_path = REPO_ROOT / sheet_path
        sheet = json.loads(sheet_path.read_text(encoding="utf-8"))

        out_dir = REPO_ROOT / "data" / sheet["id"]
        frames = render_frames(sheet, out_dir)
        write_character_yaml(sheet, out_dir / f"{sheet['id']}.yml")
        write_moves_yaml(out_dir / "moves.yml")

        print(f"  {sheet['id']:16s} {frames:3d} frames, {len(STATE_SPEC)} states -> data/{sheet['id']}/")
        total += frames

    print(f"{total} frames written")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
