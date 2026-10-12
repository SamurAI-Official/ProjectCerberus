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
Locomotion frames are a 16x64 box on a 96x384 canvas; frames that need the width
of an extended limb are a 32x64 box on a 192x384 canvas. Both canvas aspects
equal their declared box exactly, both render the figure at the same scale, and
neither can squash. At 6 px per engine unit the art also lands 1:1 on screen:
node scale 4 times camera zoom 1.5 is exactly the 6 px the canvas already uses.

Hitboxes are therefore authored in our own convention rather than inherited:
a symmetric full-body hurtbox `x_pos=-6, y_pos=0, 12x31`, which spans the figure
from the feet (0, the engine's ground) to the crown (+31). Upstream's boxes are
offset forward of the origin, which does not line up with their own centred art.
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
#
# The height is 64, not 32, because the engine centres the texture on the player
# origin and the origin is the ground. The figure stands 31 units tall *above*
# the origin, so the box has to reach at least 62 units to contain it. The lower
# half of each canvas is therefore below-ground space -- the visible price of the
# engine's centring, and far better than sinking through the floor.
#
# The widths are measured, not chosen, and they were wrong. tools/validate/
# validate_boxes.py renders every frame into an oversized canvas and reports the
# furthest the art actually reaches: 13.5 units forward of the origin for the body
# poses (hurt_high) and 17.5 for the reach poses (hurt_air). Against the old 16 and
# 32 the textures were narrower than the drawings, and PIL clips at the canvas
# edge, so 86 of the 117 frames the spec had at the time had art sliced off flat
# at the boundary -- the idle guard arm lost its hand entirely. The reference Ryu
# art clips on 4 frames of 143, so a margin is what the engine expects; this was a
# regression, not a limitation of the renderer.
#
# Widening cannot move anything. GodotRenderBackend::drawSprite draws the texture
# into a rect centred on the player origin, and figure._to_px centres the canvas on
# that same origin, so the added units are transparent margin on both sides. The
# widths below leave the same ~1.5 units of margin the reference keeps.
BODY_BOX = (30, 64)   # 180x384 canvas
# 40 rather than 38, and the extra unit is a shoe. `figure.render` now draws a
# shoe at the ankle, and a kick is the pose that throws its foot furthest
# forward: with a shoe the striking foot reaches 19.5 units, against the 19 the
# box had. The alternative was a shoe that stops at the ankle, which is a boot
# with no toe. The on-screen hitboxes do not move: `box_at` and `hurtbox_for`
# both derive the YAML x_pos from the declared width, so a wider box means the
# same hitbox in a wider texture, as the comment above explains.
#
# 42 rather than 40, and this time it is the margin the comment above promises.
# 40 units is +-20 against a foot that reaches 19.5, so a reach pose had 0.5
# units where a body pose has 1.5 -- and it is the *generated* frames that need
# it, because the shoe the model draws is a pixel wider than ours and the
# outline ring is a pixel again. Two generated kicks (2kick02, 3kick01) reached
# 19.83 units and put art on the last column of the texture, where
# build/sprite_check.py reads it as clipped; at 42 the same frames sit 6 px
# clear of it.
REACH_BOX = (42, 64)  # 252x384 canvas

FEET = figure.GROUND_Y  # 0.0 -- feet on the origin, which is the engine's ground
CROWN = 31.0

# ---------------------------------------------------------------------------
# Collision boxes are anchored on the sprite's corner, not on the origin
# ---------------------------------------------------------------------------
# `Animation::updateCollisions` does this to every box on every frame:
#
#     float width  = inverted ? sprites[current]->getWidth() / 2
#                             : -sprites[current]->getWidth() / 2;
#     float height = sprites[current]->getHeight();
#     offense[current]->update(x_pos + width, y_pos - height / 2, inverted);
#     defense[current]->update(x_pos + width, y_pos - height / 2, inverted);
#
# So a YAML box's base is the sprite's bottom-left corner when the fighter faces
# right -- `(player_x - sprite_w/2, player_y - sprite_h/2)` -- and the `x_pos` and
# `y_pos` in the file are measured from THAT, not from the player origin. Both
# consequences are load-bearing:
#
#   * The base moves with the DECLARED sprite size, so one `x_pos` means different
#     things in a 30-wide body frame and a 38-wide reach frame. This is visible in
#     the fixture itself: `defense.x_pos` is 4 in `idle`, which declares 20x40,
#     and 14 in `1punch`, which declares 40x40. Both put the box at
#     player_x - 6..+6. The convention below is read from that pair, not inferred
#     from the name `x_pos`, which suggests the origin and is wrong.
#   * The sprite is centred on the player origin and the origin is the ground, so
#     the base sits half a sprite BELOW the ground. `y_pos` therefore has to carry
#     `sprite_h / 2` before it measures anything the art can be checked against.
#
# `box_at` converts a box expressed from the ORIGIN -- the only frame of reference
# in which "feet at 0, crown at 31" is a true statement -- into the file's units.
# It is mirror-safe: `inverted` reflects `x_pos` about the same base this adds, so
# these numbers place the box in front of a fighter facing either way.
#
# Getting this wrong is exactly what the M3.5 regression did. With `y_pos` treated
# as origin-relative and set to CROWN, the hurtbox landed below the fighter's feet
# and nothing could ever connect -- visible in the engine as two blue rectangles
# drawn under the floor, and as a 120-second fight with zero hits. Neither
# validator could see it: validate_boxes.py checks the art against its declared
# canvas, which was right, and never against the engine's anchoring, which was not.
def box_at(canvas, x, y, width, height):
    """A box CENTRED on `(x, y)`, in origin units -> in the file's corner units."""
    box_width, box_height = canvas
    return {
        "x_pos": box_width / 2.0 + x - width / 2.0,
        "y_pos": box_height / 2.0 + y - height / 2.0,
        "width": float(width),
        "height": float(height),
    }


# The full-body hurtbox: feet to crown, centred on the origin. `x` is 0, and
# box_at's mirror symmetry keeps it centred when the fighter turns round.
HURTBOX_WIDTH = 12.0


def hurtbox_for(canvas):
    height = CROWN - FEET
    return box_at(canvas, 0.0, FEET + height / 2.0, HURTBOX_WIDTH, height)


# Spawn height, in engine units. It is the engine's ground: Player::move snaps
# y_pos back to y_initial on landing, and y_initial comes from this value.
#
# It does NOT control where a fighter appears on screen. That was measured, not
# assumed: changing this from 30 to 48 to 66 moved the captured silhouette by
# exactly zero rows. GodotRenderBackend::drawSprite computes the draw position as
# `logical_height - (camera_y + y)`, and the engine's camera tracks the fighters'
# y, so the two terms cancel. Anyone trying to frame the game by editing this
# number is editing a value with no visual effect -- adjust the Camera2D and the
# stage's floor line instead.
SPAWN_Y = 30.0

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
    ("hurt_mid",     "HIT_M",         "idle,walk_forward,walk_back,1punch,2punch,3punch,1kick,2kick,3kick,special,special_lite", "idle"),
    ("hurt_high",    "HIT_H",         "idle,duck,duck_back,walk_forward,1punch,2punch,3punch,1kick,2kick,3kick,special,special_lite", "idle"),
    ("hurt_low",     "HIT_L",         "idle,walk_back,duck,1punch,2punch,3punch,1kick,2kick,3kick,special,special_lite", "idle"),
    ("hurt_air",     "HIT_L,HIT_M,HIT_H", "knocked_down,jump,jump_back,jump_forward,hurt_air", "ground"),
    ("1punch",       "LP",            "idle,walk_back,walk_forward",              "idle"),
    ("2punch",       "MP",            "idle,walk_back,walk_forward,1punch",       "idle"),
    ("3punch",       "HP",            "idle,walk_back,walk_forward,1punch,2punch", "idle"),
    ("1kick",        "LK",            "idle,walk_back,walk_forward",              "idle"),
    ("2kick",        "MK",            "idle,walk_back,walk_forward,1kick",        "idle"),
    ("3kick",        "HK",            "idle,walk_back,walk_forward,1kick,2kick",  "idle"),
    ("special",      "QCF_HP",        "idle,walk_forward,1punch,2punch",          "idle"),
    ("special_lite", "QCF_LP",        "idle,walk_forward,1punch",                 "idle"),
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
        # Arms stay up in a guard and counter-swing, rather than hanging.
        arm_far=(48.0 - swing * 0.4, 76.0),
        arm_near=(36.0 + swing * 0.4, 88.0),
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


## The kick family, which is the punch family with the leg doing the work.
##
## Every strike used to come out of `_strike`, which animates `arm_far` and leaves
## `lift` -- the only parameter that moves a leg -- at 0 for the state called
## `kick`. So the move named for a leg reached out with an arm, and the fist was
## where the game said the foot was. `foot_far` is now the joint a kick's hitbox is
## derived from, so the two cannot come apart again.
##
## The envelope is deliberately the same `sin(pi * min(t / 0.55, 1))` as `_strike`:
## the two families should be timed alike so a player learns one cadence, and what
## distinguishes a jab from a roundhouse should be where the limb goes, not when.
##
## The arms go where a kicker's arms go -- the far arm trailing back for
## counterweight, the near arm across the chest for balance. A pose that moved only
## the leg would read as a leg that had detached rather than a body that kicked.
def _kick(extent, thigh, shin, lean=0.2):
    """Builds a kick: the far leg drives out to `thigh` degrees at the hip while
    the knee extends to `shin`, `extent` scaling how far the foot lands.

    Degrees are from straight down, positive forward -- so 45/30 is a shin-height
    kick, 85/95 is level with the hip, and 120/115 is at head height.
    """
    def build(i, n, profile):
        t = i / float(max(n - 1, 1))
        e = math.sin(math.pi * min(t / 0.55, 1.0)) * extent * profile.get("reach", 1.0)
        return dict(
            crouch=0.05,
            lean=lean * e,
            leg_far=(thigh * e, shin * e),
            leg_near=(-12.0, -24.0),
            arm_far=(-30.0 - 14.0 * e, 26.0),
            arm_near=(16.0 + 10.0 * e, 78.0),
        )
    return build


POSES = {
    "start":        lambda i, n, p: dict(crouch=0.06, arm_far=(54.0, 80.0), arm_near=(40.0, 92.0)),
    "idle":         lambda i, n, p: dict(
        crouch=0.06 + 0.035 * _wave(i, n),
        lean=0.05 * _wave(i, n),
        # A guard, not a hang. Arms left straight down disappear into the torso at
        # this size, which is the difference between a fighter and a mannequin.
        arm_far=(58.0 + 3.0 * _wave(i, n), 84.0),
        arm_near=(44.0 + 3.0 * _wave(i, n), 96.0),
        leg_far=(6.0, -12.0), leg_near=(-6.0, -24.0),
    ),
    "turn":         lambda i, n, p: dict(
        lean=-0.22 + 0.1 * i, crouch=0.12,
        arm_far=(34.0, 66.0), arm_near=(20.0, 80.0),
    ),
    "walk_forward": lambda i, n, p: _walk(i, n, p, 1.0),
    "walk_back":    lambda i, n, p: _walk(i, n, p, -1.0),
    "stop_walk":    lambda i, n, p: dict(crouch=0.16, lean=-0.1, leg_far=(10.0, -8.0),
                                         leg_near=(-12.0, -26.0), arm_far=(50.0, 78.0), arm_near=(38.0, 90.0)),
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
    "3punch":       _strike(1.15, 97.0, -5.0, 8.0),
    "1kick":        _kick(0.8, 45.0, 30.0),
    "2kick":        _kick(1.0, 85.0, 95.0),
    "3kick":        _kick(1.15, 120.0, 115.0, lean=0.28),
    "special":      _strike(1.3, 96.0, 0.0, 6.0),
    "special_lite": _strike(0.72, 84.0, 0.0, 0.0),
}

# ---------------------------------------------------------------------------
# Animation spec: (state, frames, delay, box, continual, pose). `box` picks the
# canvas: BODY is a 96x384 canvas in a 16x64 box, REACH a 192x384 canvas in a
# 32x64 box, both at 6 px per unit.
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
    # Hit-stun, and the numbers here are load-bearing rather than cosmetic.
    #
    # A fighter in a hurt state cannot be hit again until the hurt animation ends, so
    # the length of these three states IS the window in which a combo can continue --
    # and it has to be shorter than a follow-up's start-up, or the follow-up's active
    # frame arrives while the opponent is still unhittable and the move whiffs.
    #
    # At 4 frames x 7 the stun ran 28 ticks, about 17 frames at 60fps, while a
    # follow-up reaches its active frame about 5 frames after its press. A jab
    # therefore left only the band from ~17 frames to the end of the jab's 32-tick
    # cancel window (~19 frames) in which a straight could land -- under five frames
    # wide. Measured with tools/verify/strikes.tscn: a straight cancelled into a jab
    # connected at gap 22 frames and whiffed at 2, 4, 6, 8, 10, 12 and 16, which is
    # the whole of the window a player would actually use. That is the user-visible
    # "the combo only allows light punch and light kick": the cancel always worked,
    # the second hit could not.
    #
    # 3 x 5 is 15 ticks, about 9 frames, so a follow-up pressed from ~10 frames on
    # connects and the usable window is roughly three times as wide. The knockdowns
    # below stay long on purpose: being knocked down should not be punished by a
    # loop, and neither state is part of a ground chain.
    ("hurt_mid",     3,  5, BODY,  False, "hurt_mid"),
    ("hurt_high",    3,  5, BODY,  False, "hurt_high"),
    ("hurt_low",     3,  5, BODY,  False, "hurt_low"),
    ("hurt_air",     4,  7, REACH, False, "hurt_air"),
    ("knocked_down", 4,  9, REACH, False, "knocked_down"),
    ("hit_ground",   3,  8, REACH, False, "hit_ground"),
    ("land",         3,  7, BODY,  False, "land"),
    ("ground",       1, 20, REACH, True,  "ground"),
    ("stand",        3,  7, BODY,  False, "stand"),
    # The four chainable normals. Their frame counts are not just weight, they are
    # the cancel window -- the frames after the active frame are the recovery, and a
    # move may be cancelled out of for as long as it is still playing.
    #
    # That matters because of how this engine gates a second hit: the opponent is
    # unhittable until its own hurt animation ends, which is 15 ticks for a mid-strength
    # hit, and a follow-up reaches its active frame about 5-10 frames after the press.
    # So a follow-up only lands if it is pressed late enough that its active frame
    # arrives after the stun -- and the previous move has to still be running then, or
    # there is nothing to cancel.
    #
    # At four frames a jab plays for 32 ticks (~19 frames) and the stun alone runs to
    # ~14 frames, which left a window a couple of frames wide: measured, a straight
    # cancelled into a jab connected only at a gap of 16 frames and whiffed at 2-12.
    # Six frames plays for 48 ticks (~29 frames) and puts the active frame at ~10, so
    # the follow-up's active frame clears the stun at every gap the sweep tries. This
    # is the standard shape -- fast startup, long recovery, recovery is the window --
    # and it is the difference between a chain that exists in the data and one that
    # exists in the hand.
    ("1punch",       6,  8, REACH, False, "1punch"),
    ("2punch",       8,  8, REACH, False, "2punch"),
    ("3punch",       8,  9, REACH, False, "3punch"),
    ("1kick",        6,  7, REACH, False, "1kick"),
    ("2kick",        8,  8, REACH, False, "2kick"),
    ("3kick",        8, 10, REACH, False, "3kick"),
    ("special",      8,  8, REACH, False, "special"),
    ("special_lite", 5,  7, REACH, False, "special_lite"),
]

# Which face a state wears, by the *role* the design sheet names rather than the view: the sheet's
# `expressions` block maps each role to one of its frozen face views plus the words that go in the
# prompt. Split this way because which states are angry is the game's business and which panel is
# angry is the artist's -- a second fighter with four completely different face panels needs no
# change in this file, and a new state cannot quietly inherit the wrong face.
STATE_EXPRESSION = {
    "start": "neutral", "idle": "neutral", "turn": "neutral",
    "walk_forward": "neutral", "walk_back": "neutral", "stop_walk": "neutral",
    "start_duck": "neutral", "end_duck": "neutral", "duck": "neutral",
    "duck_back": "neutral",
    "jump": "neutral", "jump_forward": "neutral", "jump_back": "neutral",
    "block_high": "neutral", "block_low": "neutral",
    "hurt_mid": "hurt", "hurt_high": "hurt", "hurt_low": "hurt", "hurt_air": "hurt",
    "land": "hurt", "stand": "hurt",
    "knocked_down": "fail", "hit_ground": "fail", "ground": "fail",
    "1punch": "attack", "2punch": "attack", "3punch": "attack",
    "1kick": "attack", "2kick": "attack", "3kick": "attack",
    "special": "attack", "special_lite": "attack",
}

# Checked here rather than at the point of use, because the failure it prevents is invisible: a
# state missing from the table would wear whatever the fallback is for the whole of its animation,
# in every frame, in a build that would otherwise look finished.
_missing_expressions = [entry[0] for entry in STATE_SPEC if entry[0] not in STATE_EXPRESSION]
if _missing_expressions:
    raise ValueError("STATE_EXPRESSION does not cover: %s"
                     % ", ".join(_missing_expressions))
_states = {entry[0] for entry in STATE_SPEC}
_unknown_expressions = [state for state in STATE_EXPRESSION if state not in _states]
if _unknown_expressions:
    raise ValueError("STATE_EXPRESSION names states that do not exist: %s"
                     % ", ".join(sorted(_unknown_expressions)))

# Per-frame physics. Only the states that move are listed; the rest stand still,
# which is what "no move block" means to the engine.
MOVES = {
    "walk_forward": lambda i, n, p: (0.34, 0.0),
    "walk_back":    lambda i, n, p: (-0.30, 0.0),
    "jump":         lambda i, n, p: (0.0, [3.0, 1.5, -0.7, -2.2, -2.6][min(i, 4)]),
    "jump_forward": lambda i, n, p: (0.62, [3.0, 1.6, -0.5, -2.0, -2.6, -2.6, -2.6, -2.6][min(i, 7)]),
    "jump_back":    lambda i, n, p: (-0.5, [3.0, 1.5, -0.7, -2.2, -2.6][min(i, 4)]),
    "back_kick":    lambda i, n, p: (0.20 if 1 <= i <= 4 else 0.0, 0.0),
    "3punch":       lambda i, n, p: (0.22 if 1 <= i <= 4 else 0.0, 0.0),
    "2kick":        lambda i, n, p: (0.18 if 1 <= i <= 3 else 0.0, 0.0),
    "3kick":        lambda i, n, p: (0.28 if 1 <= i <= 5 else 0.0, 0.0),
    "special":      lambda i, n, p: (0.55 if 1 <= i <= 5 else 0.0, 0.0),
    "special_lite": lambda i, n, p: (0.34 if 1 <= i <= 3 else 0.0, 0.0),
}

# Where each strike lands: the strength handed to the defender, the joint that
# does the hitting, and how big the box is. The DEFENDER's own state machine
# decides whether that becomes a hit or a block -- damage is applied by the engine
# at that single resolution point (see patches/openfight/0001).
#
# Nothing here is a position, and nothing here is a frame number. Both are derived
# from the pose by `strike_box` below:
#
#   * the active frame is the frame where `joint` reaches furthest forward;
#   * the box is centred on that joint at that frame.
#
# The previous version of this table hand-authored both, and both were wrong.
# Every `y_pos` in it was written as if y were measured DOWN from the crown rather
# than up from the feet, so `1punch` declared a hitbox at y 5..11 -- shin height --
# while its pose holds the punching hand at y 23.3. The frames were wrong in the
# same direction: POSES builds all five strikes with `_strike`, whose envelope is
# `sin(pi * min(t / 0.55, 1))` -- a sine *of* a value that itself reaches 1 at
# t=0.55, where the sine is zero again -- so the extension peaks at 27.5% of the
# animation and is fully retracted by 55%. `2punch` declared frame 3 of 6, a frame
# on which the arm has already come back. The result was a hitbox floating beside
# a withdrawn arm, and any later re-timing of an animation would have silently
# re-timed the hitbox away from the limb again. Derived, it cannot.
#
# Every joint named here is a hand, and that is not a copy-paste: `_strike`
# animates `arm_far` toward `horizontal` degrees and `lift` -- the only parameter
# that moves a leg -- is 0 for `kick` and only 6 for `back_kick` and `special`. So
# `kick` presently extends a forward arm to y 25.6 with both feet planted 0.5
# units in front of the origin. When the kick becomes a kick, this table gains
# `foot_far` for it and the box follows the leg with nothing else to change.
## Where every strike box begins: the body's front edge, in origin units forward of
## the origin. HURTBOX_WIDTH is 12 and centred, so the body ends at +6.
##
## This constant is the fix for a combo that could not exist. The box used to be
## CENTRED on the striking joint, which makes a move's reach a by-product of where a
## pose happens to put that joint -- and the generated poses put the straight's fist
## 0.36 units behind the jab's, so with the two boxes the same size the straight
## reached less far than the jab it was meant to follow. Measured in the engine: the
## jab connected at a spacing of 12.8-13.1 units, the straight only at 11.9-12.5, so
## cancelling a jab into a straight whiffed every time the jab landed at the jab's
## own reach. That is the "the combo only allows light punch and light kick" report,
## and it was never the combo system -- the cancel itself worked the whole time.
##
## Pinning the near edge to the body makes it identical for every strike in the set
## and makes reach monotonic: the far edge follows the joint, so a heavier move
## extends further than a lighter one and never less far inward. The resulting ladder
## is reported by tools/verify/strikes.tscn, which is also what caught the above.
STRIKE_NEAR = 6.0

# `margin` is how far past the joint the box reaches; the near edge is STRIKE_NEAR.
STRIKES = {
    # state:        (trigger,      joint,       margin, half_height)
    "1punch":       ("HIT_M",       "hand_far",   3.5, 3.0),
    "2punch":       ("HIT_M",       "hand_far",   4.0, 3.0),
    "3punch":       ("HIT_H",       "hand_far",   4.5, 3.5),
    "1kick":        ("HIT_L",       "foot_far",   3.5, 3.0),
    "2kick":        ("HIT_M",       "foot_far",   4.5, 3.5),
    "3kick":        ("KNOCK_DOWN",  "foot_far",   5.0, 4.0),
    "special":      ("KNOCK_DOWN",  "hand_far",   5.0, 4.5),
    "special_lite": ("HIT_M",       "hand_far",   4.0, 3.0),
}

## The states a chain may be cancelled out of, and the reason the `from` lists
## above name the move before them.
##
## The engine reads `combo: true` in `updateState`: when the current animation is a
## combo, a command only takes effect if the opponent is in a hurt state. So the
## chain is enforced by the engine rather than by a timer here -- a jab confirms
## into a straight only if the jab actually connected, and a whiffed one plays out
## and returns to idle like any other move.
##
## The enders are deliberately absent. `3punch` and `3kick` are the heaviest thing
## each limb has and they complete on their own; a chain that could cancel out of
## its own ender has no ender.
COMBO_STATES = {"1punch", "2punch", "1kick", "2kick"}

# The engine's shared hit-spark object, `type: temporary`, one frame set reused
# by every attack. Referenced rather than copied: it is engine-owned VFX data,
# like the ground collision.
HIT_VFX = "data/collision/collision.yml"

BOXES = {"body": BODY_BOX, "reach": REACH_BOX}


def strike_box(state, count, profile, canvas):
    """The active frame and the offensive box for a strike, both taken from the pose.

    The frame is the one on which `state`'s striking joint is furthest forward;
    the box is centred on that joint there. `rest` is the joint's position on
    frame 0, and the pose has to beat it, so naming a joint that a pose never
    moves is a build error instead of a hitbox parked on a stationary limb.

    `canvas` is the frame's declared box, because the engine anchors collision
    boxes on the sprite's corner and the declared size is part of that (see
    `box_at`). The joint's position is in origin units; box_at converts.
    """
    trigger, joint, half_width, half_height = STRIKES[state]
    build = POSES[state]

    rest = figure.pose(**build(0, count, profile))[joint][0]

    best_index, best_point = 0, None
    for index in range(count):
        point = figure.pose(**build(index, count, profile))[joint]
        if best_point is None or point[0] > best_point[0]:
            best_index, best_point = index, point

    if best_point[0] <= rest:
        raise ValueError(
            "%s: %s never moves forward (rest x=%.1f, best x=%.1f)"
            % (state, joint, rest, best_point[0])
        )

    # The box runs from the body's front edge out to the joint, plus this move's own
    # margin. See STRIKE_NEAR for why the near edge is fixed rather than derived.
    far = best_point[0] + half_width
    width = max(far - STRIKE_NEAR, half_width)
    box = box_at(canvas, STRIKE_NEAR + width / 2.0, best_point[1], width, 2.0 * half_height)
    return best_index, trigger, box


def render_frames(sheet, frames_dir):
    """Writes every frame of every state. Returns how many were written.

    Frames that the specification no longer declares are deleted. That is not
    housekeeping: a state's frame count *is* its length in ticks, so shortening
    one -- which is how the cancel window was widened -- leaves the old last
    frame on disk. Nothing plays it, because the character YAML lists its frames
    explicitly, but `validate_manifest.py` reads the directory and then reports
    the orphan as a frame over the colour budget in a palette that no longer
    exists: a true report of a false problem.
    """
    palette = figure.Palette(sheet["palette16"])
    profile = sheet.get("profile", {})
    frames_dir.mkdir(parents=True, exist_ok=True)

    written, names = 0, set()
    for state, count, _delay, box, _continual, pose_name in STATE_SPEC:
        builder = POSES.get(pose_name, POSES["idle"])
        canvas = tuple(int(dim * figure.PX_PER_UNIT) for dim in BOXES[box])

        for index in range(count):
            skeleton = figure.pose(**builder(index, count, profile))
            name = f"{state}{index:02d}.png"
            figure.render(skeleton, canvas, palette).save(frames_dir / name)
            names.add(name)
            written += 1

    pruned = []
    for path in sorted(frames_dir.glob("*.png")):
        if path.name in names:
            continue
        pruned.append(path.name)
        path.unlink()
        # Godot's import cache is a separate file beside the frame; leaving it
        # behind leaves the editor reporting an import for an image that is not
        # there.
        (frames_dir / f"{path.name}.import").unlink(missing_ok=True)

    if pruned:
        print(f"  pruned {len(pruned)} stale frame(s): {', '.join(pruned)}")

    return written





def _num(value):
    """Engine-side floats are read with as<float>, but integers keep the file
    readable and diffable."""
    return str(int(value)) if float(value) == int(value) else f"{float(value):g}"


def write_character_yaml(sheet, out_path):
    identifier = sheet["id"]
    profile = sheet.get("profile", {})
    lines = [
        "character:",
        f"  name: {identifier}",
        "  type: player",
        f"  health: {sheet.get('health', 100)}",
        "  position:",
        "    x_pos: 0",
        f"    y_pos: {_num(SPAWN_Y)}",
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
        defense = hurtbox_for(BOXES[box])
        # A strike's active frame and its box both come from its pose (see
        # STRIKES), so the hitbox is wherever the striking limb actually is.
        strike = strike_box(state, count, profile, BOXES[box]) if state in STRIKES else None

        lines.append(f"  - name: {state}")
        if continual:
            lines.append("    continual: true")
        # A chain may only be cancelled out of while the opponent is hurt; the
        # engine enforces that, not this builder. See COMBO_STATES.
        if state in COMBO_STATES:
            lines.append("    combo: true")
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

            lines.append("      defense:")
            for key in ("x_pos", "y_pos", "width", "height"):
                lines.append(f"        {key}: {_num(defense[key])}")

            if strike is not None and index == strike[0]:
                _, trigger, offsets = strike
                lines.append("      offense:")
                for key in ("x_pos", "y_pos", "width", "height"):
                    lines.append(f"        {key}: {_num(offsets[key])}")
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
        # Two specials off one motion, which is the shape the fixture already uses
        # -- its own QCF_LP and QCF_HP are the same F,~D prefix with the punch
        # button deciding which one fires. The `~c`/`~a` pair covers the press and
        # the release, so a player who does not let go in the same frame, or who
        # lets go early, still gets the move either way.
        ("F,~D,c", "QCF_HP"), ("F,~D,~c", "QCF_HP"),
        ("F,~D,a", "QCF_LP"), ("F,~D,~a", "QCF_LP"),
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
