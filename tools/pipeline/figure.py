"""Parametric figure renderer for Project Cerberus fighters.

Why a renderer and not art: there is no artist on this project yet, and a
fighting game needs ~140 frames per fighter with hitboxes that line up frame by
frame. A parametric skeleton gives correct, consistent silhouettes per state,
reproduces exactly, and produces art that flows through the same pipeline real
frames will -- so replacing it later is a swap of the frame source, not a
rewrite of the tooling.

Coordinate system
-----------------
Engine units, +y UP, origin at the player origin. The engine draws the whole
texture centred on that origin, so the canvas centre IS the origin and the
figure must sit around it symmetrically.

Density is a constant 4 px per unit for every frame, and every declared draw box
is canvas/4, so the figure renders at exactly one size in every state. That is
the whole point: the shipped fixture declares different boxes for the same
picture (its `idle` is 12x30 and its `start` is 20x40, both from idle00.png), so
its character changes size between states. This cannot.

Figure proportions: body 12 units wide, 30 units tall, feet 16 below the origin
and head crown 15 above it.
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw

PX_PER_UNIT = 4

FEET_Y = -16.0
PELVIS_Y = 1.0
CHEST_Y = 7.0
NECK_Y = 9.5
HEAD_Y = 12.2
HEAD_R = 2.9
SHOULDER_Y = 8.2
SHOULDER_X = 3.6
HIP_X = 2.2

UPPER_ARM = 4.6
FOREARM = 4.6
THIGH = 8.0
SHIN = 8.2


def _limb(root, upper_len, lower_len, a1, a2, sign):
    """Two-segment limb. a1/a2 are degrees from straight-down, positive = forward
    (+x). sign flips the limb to the other side of the body."""
    a1r = math.radians(a1)
    mid = (root[0] + sign * upper_len * math.sin(a1r), root[1] - upper_len * math.cos(a1r))
    a2r = math.radians(a2)
    tip = (mid[0] + sign * lower_len * math.sin(a2r), mid[1] - lower_len * math.cos(a2r))
    return mid, tip


def _rotate(point, pivot, degrees):
    a = math.radians(degrees)
    dx, dy = point[0] - pivot[0], point[1] - pivot[1]
    return (pivot[0] + dx * math.cos(a) - dy * math.sin(a),
            pivot[1] + dx * math.sin(a) + dy * math.cos(a))


def pose(crouch=0.0, lean=0.0, airborne=0.0, torso_angle=0.0,
         arm_far=(14.0, 24.0), arm_near=(-12.0, 40.0),
         leg_far=(6.0, -6.0), leg_near=(-6.0, 6.0),
         head_shift=0.0):
    """Returns the skeleton as a dict of named engine-unit points.

    crouch     0..1   drops the hips and bends the knees
    lean       -1..1  torso tilt, positive = forward
    airborne   0..1   tucks the legs up
    torso_angle deg   rotates the whole upper body about the pelvis, which is how
                      knockdown and ground poses are built
    """
    drop = crouch * 4.0 + airborne * 3.0
    pelvis = (lean * 0.6, PELVIS_Y - drop)

    torso = {
        "chest": (lean * 1.4, CHEST_Y - drop * 0.75),
        "neck": (lean * 1.8, NECK_Y - drop * 0.65),
        "head": (lean * 2.0 + head_shift, HEAD_Y - drop * 0.6),
        "shoulder_far": (SHOULDER_X + lean * 1.2, SHOULDER_Y - drop * 0.8),
        "shoulder_near": (-SHOULDER_X + lean * 1.2, SHOULDER_Y - drop * 0.8),
    }
    if torso_angle != 0.0:
        torso = {key: _rotate(point, pelvis, torso_angle) for key, point in torso.items()}

    chest = torso["chest"]
    head = torso["head"]
    shoulder_far = torso["shoulder_far"]
    shoulder_near = torso["shoulder_near"]
    neck = torso["neck"]

    # Both arms and both legs use sign=+1 so an angle ALWAYS means the same
    # thing: degrees from straight-down, positive = the direction the fighter
    # faces. The far/near pair is only offset in x (faking depth) and drawn in a
    # darker colour -- in a side view there is no left and right arm.
    elbow_far, hand_far = _limb(shoulder_far, UPPER_ARM, FOREARM, arm_far[0], arm_far[1], 1)
    elbow_near, hand_near = _limb(shoulder_near, UPPER_ARM, FOREARM, arm_near[0], arm_near[1], 1)

    hip_far = (HIP_X + lean * 0.4, pelvis[1])
    hip_near = (-HIP_X + lean * 0.4, pelvis[1])

    leg_len_scale = 1.0 - airborne * 0.25
    knee_far, foot_far = _limb(hip_far, THIGH * leg_len_scale, SHIN * leg_len_scale,
                               leg_far[0], leg_far[1], 1)
    knee_near, foot_near = _limb(hip_near, THIGH * leg_len_scale, SHIN * leg_len_scale,
                                 leg_near[0], leg_near[1], 1)

    return {
        "pelvis": pelvis, "chest": chest, "neck": neck, "head": head,
        "shoulder_far": shoulder_far, "elbow_far": elbow_far, "hand_far": hand_far,
        "shoulder_near": shoulder_near, "elbow_near": elbow_near, "hand_near": hand_near,
        "hip_far": hip_far, "knee_far": knee_far, "foot_far": foot_far,
        "hip_near": hip_near, "knee_near": knee_near, "foot_near": foot_near,
    }


def _to_px(point, size):
    """Engine units -> canvas pixels, with the ORIGIN AT THE CANVAS CENTRE."""
    return (size[0] / 2.0 + point[0] * PX_PER_UNIT,
            size[1] / 2.0 - point[1] * PX_PER_UNIT)


def render(skeleton, canvas, palette):
    """Draws the skeleton into an RGB image of `canvas` pixels.

    The background is pure black, which is the engine's transparency key (see
    GodotRenderBackend::loadTexture). No anti-aliasing: the key is an exact
    match on r==g==b==0, and near-black edge pixels would survive as a dark
    fringe.
    """
    image = Image.new("RGB", canvas, (0, 0, 0))
    draw = ImageDraw.Draw(image)

    limbs = [
        ("hip_near", "knee_near", "foot_near", palette["far_limb"], 3),
        ("shoulder_near", "elbow_near", "hand_near", palette["far_limb"], 3),
        ("hip_far", "knee_far", "foot_far", palette["near_limb"], 4),
        ("shoulder_far", "elbow_far", "hand_far", palette["near_limb"], 4),
    ]
    for a, b, c, colour, width in limbs:
        draw.line([_to_px(skeleton[a], canvas), _to_px(skeleton[b], canvas)], fill=colour, width=width)
        draw.line([_to_px(skeleton[b], canvas), _to_px(skeleton[c], canvas)], fill=colour, width=width)

    # Torso last among the body so it overlaps the limb roots.
    draw.line([_to_px(skeleton["pelvis"], canvas), _to_px(skeleton["chest"], canvas)],
              fill=palette["torso"], width=9)
    draw.line([_to_px(skeleton["chest"], canvas), _to_px(skeleton["neck"], canvas)],
              fill=palette["torso"], width=8)

    head = _to_px(skeleton["head"], canvas)
    radius = HEAD_R * PX_PER_UNIT
    draw.ellipse([head[0] - radius, head[1] - radius, head[0] + radius, head[1] + radius],
                 fill=palette["skin"], outline=palette["accent"], width=2)

    return image
