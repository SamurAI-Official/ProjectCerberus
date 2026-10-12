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

# 6 px per engine unit, not 4. The engine draws at node scale 4 and the match
# camera is at zoom 1.5, so one engine unit is exactly 6 screen pixels.
# Authoring at 6 px per unit therefore lands every art pixel on exactly one
# screen pixel. The old 4 px per unit meant each art pixel straddled 1.5 screen
# pixels, which no filter setting can make crisp.
PX_PER_UNIT = 6

# Feet sit ON the origin. The engine centres the texture on the player origin,
# and while standing that origin IS the ground (Player::move snaps y_pos back to
# y_initial). Art hanging below the origin therefore sinks through the floor --
# which is precisely what the previous 16-units-below arrangement did, and why
# the fighters rendered clipped off the bottom of the screen.
#
# Feet at 0 and a crown at ~31 means the figure occupies the upper half of the
# canvas and the lower half is below-ground space. That is the price of the
# engine centring the texture; the alternative is sinking through the floor.
GROUND_Y = 0.0
FEET_Y = GROUND_Y
PELVIS_Y = 17.0
CHEST_Y = 23.0
# The neck reaches ABOVE the head's centre-line minus its radius, so the head and
# torso overlap by ~1.1 units (~7 px). They used to meet with just over a pixel to
# spare, which rendered as a hairline of pure ink -- technically attached, but it
# read as a floating head at this size.
NECK_Y = 26.2
HEAD_Y = 27.8
HEAD_R = 2.7
SHOULDER_Y = 24.2
# Half-width of the chest, in engine units. At 3.6 the torso came out ~32% of the
# figure's height, which reads as a box rather than a body; 3.0 brings it to ~27%,
# which is roughly life proportion and leaves room for the arms to be visible
# against it rather than merging into it.
SHOULDER_X = 3.0
HIP_X = 2.4

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


def _lerp(point, other, t):
    """A point `t` of the way from `point` to `other`, in pixels.

    Used to place the collar and the tie *inside* the torso quad rather than at
    fixed pixel offsets from it: the torso leans and drops with the pose, so a
    tie pinned to the skeleton at a constant offset would slide off the chest in
    a crouch.
    """
    return (point[0] + (other[0] - point[0]) * t,
            point[1] + (other[1] - point[1]) * t)


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


OUTLINE_PX = 2

# The sixteen tones a fighter is allowed, addressed by role rather than by index
# so the renderer never needs to know what shade of teal "cloth" happens to be.
#
# Sixteen is not nostalgia. Guilty Gear's PS1 characters are 16-colour 64x121
# sprites (Ishiwatari / Abe, NDC18), and that budget is a large part of why they
# read as one character instead of a pile of parts. Enforcing it *structurally*
# -- the renderer can only ask for a role -- means the count cannot drift, and a
# 2P palette swap becomes a table substitution rather than a re-render. A
# post-hoc quantiser would instead silently merge whichever two tones happened
# to be closest, which is the one thing you cannot recover.
PALETTE_ROLES = (
    "outline",
    "skin_light", "skin", "skin_shadow",
    "cloth_light", "cloth", "cloth_shadow",
    "limb_light", "limb", "limb_shadow",
    "far", "far_shadow",
    "accent", "accent_shadow",
    "highlight", "eye",
)


class Palette:
    """A fighter's 16 colours, addressed by role.

    The ink is always pure black and is not negotiable: outlines are what make a
    low-colour figure legible, and they are only drawable at all now that the
    renderer honours source alpha (patches/openfight/0002). Under the black key
    that preceded it, "black" and "nothing" were the same value.
    """

    def __init__(self, colours):
        """`colours` maps role -> [r, g, b]; every role must be present.

        Keyed rather than positional so that a design sheet states which tone is
        which. A bare list of sixteen triples is unreadable and unreviewable, and
        the whole point of the budget is that a human can hold it in their head.
        """
        missing = [role for role in PALETTE_ROLES if role not in colours]
        unknown = [role for role in colours if role not in PALETTE_ROLES]
        if missing or unknown:
            raise ValueError(
                "palette must define exactly the %d known roles (missing: %s; unknown: %s)"
                % (len(PALETTE_ROLES), ", ".join(missing) or "none", ", ".join(unknown) or "none"))

        self.colours = {role: tuple(int(c) for c in colours[role]) for role in PALETTE_ROLES}
        self.colours["outline"] = (0, 0, 0)

    def __getitem__(self, role):
        try:
            return self.colours[role]
        except KeyError:
            raise KeyError("unknown palette role %r; known: %s"
                           % (role, ", ".join(PALETTE_ROLES))) from None

    def rgba(self, role):
        return self[role] + (255,)

    def unique_count(self):
        return len(set(self.colours.values()))


def _ink_and_fill(draw, points, colour, width):
    """Strokes a segment as ink-then-fill so every limb carries its own outline.

    Overdrawing a thicker black stroke beneath the colour is the cheap version of
    the separate inking pass hand-drawn sprite art uses, and it is what keeps a
    flat figure reading against a busy background.
    """
    draw.line(points, fill=(0, 0, 0, 255), width=width + OUTLINE_PX * 2, joint="curve")
    draw.line(points, fill=tuple(colour) + (255,), width=width, joint="curve")


def _torso_shape(skeleton, canvas):
    """The torso as a quad: narrow at the hips, broad at the shoulders.

    A stroked line of uniform width gives the body no silhouette, and at this
    size silhouette is most of what makes a character identifiable.
    """
    pelvis = _to_px(skeleton["pelvis"], canvas)
    neck = _to_px(skeleton["neck"], canvas)
    half_hips = HIP_X * PX_PER_UNIT * 1.2
    half_chest = SHOULDER_X * PX_PER_UNIT * 1.35
    return [(pelvis[0] - half_hips, pelvis[1]),
            (neck[0] - half_chest, neck[1]),
            (neck[0] + half_chest, neck[1]),
            (pelvis[0] + half_hips, pelvis[1])]


def _panel(quad, scale, shift_x=0.0):
    """Scales a quad toward its own centre and slides it sideways.

    Used to drop the lit and shadowed panels inside the torso so the body has a
    light direction rather than being one flat tone.
    """
    centre_x = sum(point[0] for point in quad) / len(quad)
    centre_y = sum(point[1] for point in quad) / len(quad)
    span = abs(quad[2][1] - quad[0][1]) or 1.0
    return [(centre_x + (x - centre_x) * scale + shift_x * span,
             centre_y + (y - centre_y) * scale) for x, y in quad]


def render(skeleton, canvas, palette):
    """Draws the skeleton into an RGBA image of `canvas` pixels.

    Fully transparent background, pure black ink. Both are only safe because
    patches/openfight/0002 makes the renderer honour a source alpha channel; the
    black key it replaced made black and nothing the same value, so ink and
    shadow could not be drawn at all -- black outlines were punched straight
    through the character.
    """
    image = Image.new("RGBA", canvas, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    def at(name):
        return _to_px(skeleton[name], canvas)

    # Back to front. Far side in the darker tones, near side in the lighter ones:
    # that contrast is what reads as depth on a flat sprite.
    #
    # Stroke widths are per-limb and generous -- at 6 px per unit an arm is a
    # little over a unit thick, and anything thinner than ~8 px stops reading as
    # a limb once the 2 px ink is subtracted from it.
    _ink_and_fill(draw, [at("shoulder_near"), at("elbow_near"), at("hand_near")],
                  palette["far_shadow"], 8)
    _ink_and_fill(draw, [at("hip_near"), at("knee_near"), at("foot_near")],
                  palette["far"], 10)

    # Torso, then the lit panel down the front edge and the shadow down the back.
    torso = _torso_shape(skeleton, canvas)
    draw.polygon(torso, fill=palette.rgba("cloth"),
                 outline=palette.rgba("outline"), width=OUTLINE_PX)
    draw.polygon(_panel(torso, 0.78, -0.16), fill=palette.rgba("cloth_light"))
    draw.polygon(_panel(torso, 0.68, 0.26), fill=palette.rgba("cloth_shadow"))

    # Collar and necktie, on the chest and under the chin.
    #
    # This replaces a band of `accent` drawn across the brow. That band was the
    # palette's only use of the character's signature colour, and at this size it
    # read as a headband on a blank-headed mannequin -- the fighters are academy
    # students in a blazer, so the signature colour belongs on the tie. `accent`
    # and `accent_shadow` are the tie's red, and the collar is the shirt the
    # reference sheet draws under it.
    neck_px = at("neck")
    front_top, front_bottom = torso[2], torso[3]
    knot = _lerp(front_top, torso[0], 0.34)
    waist = _lerp(front_bottom, torso[1], 0.34)
    tie_tip = (knot[0] - 2, knot[1] + (waist[1] - knot[1]) * 0.55)

    collar = [(neck_px[0] - 7, neck_px[1] + 1), (neck_px[0] + 9, neck_px[1] + 1),
              (neck_px[0] + 1, neck_px[1] + 11)]
    draw.polygon(collar, fill=palette.rgba("highlight"),
                 outline=palette.rgba("outline"), width=OUTLINE_PX)
    draw.polygon([(knot[0] - 5, knot[1] + 1), (knot[0] + 5, knot[1] + 1),
                  (tie_tip[0] + 3, tie_tip[1]), (tie_tip[0] - 4, tie_tip[1])],
                 fill=palette.rgba("accent"), outline=palette.rgba("outline"),
                 width=OUTLINE_PX)
    draw.line([(knot[0] - 2, knot[1] + 3), (tie_tip[0] - 2, tie_tip[1] - 2)],
              fill=palette.rgba("accent_shadow"), width=3)

    # Near leg, then the shin in the shadow tone so the knee bend is readable --
    # one flat tone turns a limb into a pipe.
    knee_far = at("knee_far")
    _ink_and_fill(draw, [at("hip_far"), knee_far], palette["limb"], 11)
    _ink_and_fill(draw, [knee_far, at("foot_far")], palette["limb_shadow"], 11)
    _ink_and_fill(draw, [at("shoulder_far"), at("elbow_far"), at("hand_far")],
                  palette["limb_light"], 9)

    # Head: skull, highlight, jaw shadow, eye, catchlight, and a cap of hair.
    # At this size a face is a handful of pixels, and those pixels carry most of
    # the character.
    head = at("head")
    radius = HEAD_R * PX_PER_UNIT
    box = [head[0] - radius, head[1] - radius, head[0] + radius, head[1] + radius]
    draw.ellipse(box, fill=palette.rgba("skin"),
                 outline=palette.rgba("outline"), width=OUTLINE_PX)
    draw.ellipse([box[0] + 2, box[1] + 2, head[0] + radius * 0.4, head[1] + radius * 0.3],
                 fill=palette.rgba("skin_light"))
    draw.rectangle([box[0] + 2, head[1] + radius * 0.5, box[2] - 2, box[3] - 3],
                   fill=palette.rgba("skin_shadow"))

    eye_x = head[0] + radius * 0.25
    draw.rectangle([eye_x, head[1] - 2, eye_x + 3, head[1] + 2], fill=palette.rgba("eye"))
    draw.rectangle([eye_x + 1, head[1] - 2, eye_x + 2, head[1] - 1],
                   fill=palette.rgba("highlight"))

    # Hair, in `eye`. The role is the darkest tone the character owns -- on both
    # reference sheets that is the hair, and the eyes are drawn in it too -- and
    # a cap over the top half of the skull is what turns a bare oval into a head
    # with a hairline. It is drawn two pixels proud of the skull so the hair
    # reads as volume sitting on the head rather than paint on it.
    draw.pieslice([box[0], box[1] - 2, box[2], box[3]], 180, 360,
                  fill=palette.rgba("eye"))

    # Shoes, last so they sit over the ankles. Both reference sheets draw dark
    # brown shoes, and a foot-coloured boot at the end of a tan trouser leg is
    # the difference between a student in shoes and a mannequin on stilts.
    for foot in ("foot_near", "foot_far"):
        fx, fy = at(foot)
        draw.line([(fx - 4, fy), (fx + 6, fy)], fill=palette.rgba("outline"), width=9)
        draw.line([(fx - 3, fy), (fx + 5, fy)], fill=palette.rgba("eye"), width=6)

    return image

