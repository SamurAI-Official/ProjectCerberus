#!/usr/bin/env python3
"""How much of the drawing did the generator actually keep?

    python3 tools/ai/frame_fidelity.py build/ai/probe_canny

`to_sprite.py` registers a generated frame into the game canvas by scaling and
translating it, on the assumption that the frame carries the same camera as the
drawing it was conditioned on: engine y=0 on the 90% line, `size / FRAME_UNITS`
pixels per engine unit. That is only true if the sampler painted the figure where
the drawing put it. A mode that re-frames breaks the registration *silently* --
the sprite still lands inside its texture, it just no longer sits on the hitboxes
that were measured from the skeleton.

So each raw render is compared against the conditioning image it came from, on
the figure's mask, and the answer is reported as:

  * **IoU** of the two masks. 1.0 means the generated frame occupies the same
    pixels as the drawing. This is the number that matters: a punch whose fist
    moved is an IoU drop exactly where the offense box is.
  * **extent** of each mask in engine units, on the drawing's camera, so a
    frame that drifted can be read as "0.8 units too tall" rather than "different".

Below about 0.75 the silhouette has moved enough that reach changes; the hitboxes
are calibrated in units of reach, so a frame like that is a whiff waiting to
happen. The threshold is a judgement; the number is not.

What this cannot tell you
-------------------------
It scores the render against whatever `init/` holds, and that is `gen_frames.py`'s choice. For
img2img, canny and controlnet it holds the *posed drawing*, so the number means "kept the pose".
For the `reference` arm it holds the composed *design sheet* -- a standing figure -- so the same
number means "kept the drawing", and a frame that ignores the skeleton and redraws the sheet scores
*better* than one that adopts the pose. That arm did exactly that: 0.911 against the composed sheet
while every frame's front reach stayed at +5.5..+6.0 engine units against a skeleton whose punching
hand is at +12.4. The pose is measured in the other direction by
`tools/validate/validate_reach.py` (does the art reach the box the skeleton put out there), and
`build/pose_check.py` prints all three silhouettes -- skeleton, composed, render -- side by side.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "ai"))

import openpose_render  # noqa: E402

# How far a pixel has to be from the backdrop to count as the figure. The
# backdrop is found, not assumed: it is the median colour of the image's border,
# which survives the generator repainting it (it does, to a slightly different
# grey) as long as it stays uniform.
BACKDROP_DISTANCE = 28.0

# A frame's silhouette has to agree with the drawing at least this well before
# it is worth quantising. See the module docstring.
GOOD_IOU = 0.75

# Speck size, in pixels, below which a component of the mask is a decoder artifact rather than the
# figure. Measured rather than guessed: the reference arm's frames come back with three off-backdrop
# pixels in one corner of a 512x512 frame -- the composed init has none, so it is the sampler's or the
# VAE's edge and not the compositor's -- and three pixels were enough to decide the mask's bounding
# box on two sides and to make every frame read as unscorable.
MIN_FIGURE_PIXELS = 32

# How much of the frame's own border may be off-backdrop before the frame counts as having no
# backdrop left to separate the figure from. Not zero, for the reason above: a handful of edge pixels
# is not an illustration, and a full-bleed render has essentially all of its border off.
EDGE_TOLERANCE = 0.02


def largest_components(mask: np.ndarray) -> np.ndarray:
    """The mask's figure-sized components: a speck in a corner is not the figure.

    The same idea as `sheet_views.trim_mask`, one threshold lower. There the question was "is this a
    word of annotation beside the drawing"; here it is "is this a pixel of drawing at all".
    """
    from scipy import ndimage

    labels, count = ndimage.label(mask, structure=np.ones((3, 3), dtype=int))
    if count <= 1:
        return mask
    sizes = np.asarray(ndimage.sum(mask, labels, index=np.arange(1, count + 1)))
    keep = np.flatnonzero(sizes >= MIN_FIGURE_PIXELS) + 1
    return np.isin(labels, keep)


def mask_of(image: Image.Image) -> np.ndarray:
    """The figure's pixels: everything that is not the border's colour."""
    rgb = np.asarray(image.convert("RGB")).astype(float)
    border = np.concatenate([rgb[0, :], rgb[-1, :], rgb[:, 0], rgb[:, -1]])
    backdrop = np.median(border, axis=0)
    distance = np.sqrt(((rgb - backdrop) ** 2).sum(axis=2))
    return largest_components(distance > BACKDROP_DISTANCE)


def extent(mask: np.ndarray) -> dict:
    """The mask's outermost pixels, in engine units, on the drawing's camera.

    `edge` says whether the mask runs into the frame's own border, which is the
    case that makes this whole comparison meaningless: a generator that paints a
    full-bleed illustration (a room, a city, a panel) has no backdrop left to
    separate from, so "the figure" measures as the frame and the extent comes back
    pinned to the canvas edge. Reporting the resulting near-zero IoU as a pose
    failure would be a lie, and this flag is what stops it being told.
    """
    height, width = mask.shape
    rows, cols = np.nonzero(mask)
    if not len(rows):
        return {"front": 0.0, "back": 0.0, "crown": 0.0, "feet": 0.0,
                "empty": True, "edge": False}
    scale = width / openpose_render.FRAME_UNITS
    ground = height * openpose_render.GROUND_FRACTION
    centre = width / 2.0
    result = {
        "front": (cols.max() - centre) / scale,
        "back": (centre - cols.min()) / scale,
        "crown": (ground - rows.min()) / scale,
        "feet": (rows.max() - ground) / scale,
        "empty": False,
    }
    # The four sides have different bounds: the figure may span half the canvas
    # sideways but 0.9 of it upward, because the ground plane sits at 90%.
    #
    # Measured as a fraction of the border rather than as "the mask touches it", because one artifact
    # pixel in a corner used to be enough to declare a frame that is 89% backdrop unscoreable. What
    # the flag is for is a frame with no backdrop left in it, and that shows up as a border that is
    # almost entirely figure.
    border = np.concatenate([mask[0, :], mask[-1, :], mask[:, 0], mask[:, -1]])
    result["edge"] = float(border.mean()) > EDGE_TOLERANCE
    return result


def compare(drawn: np.ndarray, generated: np.ndarray) -> dict:
    """IoU, and where the two disagree, in units."""
    a, b = extent(drawn), extent(generated)
    union = (drawn | generated).sum()
    iou = float((drawn & generated).sum()) / union if union else 0.0
    return {
        "iou": iou,
        "separable": not (b["edge"] and not a["edge"]),
        "drift": {key: b[key] - a[key] for key in ("front", "back", "crown", "feet")},
        "drawn": a,
        "generated": b,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("out_dir",
                        help="a gen_frames.py output directory (needs init/ and raw/)")
    parser.add_argument("--quiet", action="store_true",
                        help="only the summary line")
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = REPO_ROOT / out_dir
    raws = sorted((out_dir / "raw").glob("*.png"))
    if not raws:
        raise SystemExit(f"no raw renders under {out_dir / 'raw'}")

    rows = []
    for raw in raws:
        drawn_path = out_dir / "init" / raw.name
        if not drawn_path.is_file():
            drawn_path = out_dir / "poses" / raw.name
        drawn = mask_of(Image.open(drawn_path))
        generated = mask_of(Image.open(raw))
        if generated.shape != drawn.shape:
            generated = np.asarray(
                Image.open(raw).resize((drawn.shape[1], drawn.shape[0])))
        result = compare(drawn, generated)
        rows.append((raw.stem, result))
        if not args.quiet:
            if result["separable"]:
                print(f"  {raw.stem:16s} iou={result['iou']:.3f}  " + "  ".join(
                    f"{key} {result['drawn'][key]:+.1f}->{result['generated'][key]:+.1f}"
                    for key in ("front", "back", "crown", "feet")))
            else:
                print(f"  {raw.stem:16s} iou=n/a    no backdrop: the generated frame "
                      f"reaches the canvas edge (front {result['generated']['front']:+.1f} "
                      f"back {result['generated']['back']:+.1f})")

    separable = [(stem, result) for stem, result in rows if result["separable"]]
    print(f"\n{len(rows)} frame(s) under {out_dir.relative_to(REPO_ROOT)}")
    if not separable:
        print("  no frame has a flat backdrop, so the figure cannot be separated from\n"
              "  it and no pose can be said to have been held or lost. Two causes have\n"
              "  been seen here: a sampler painting a full-bleed illustration (edges\n"
              "  as the only conditioning, an empty latent), and a sampler painting a\n"
              "  gradient or banded backdrop behind a figure that is in the right\n"
              "  place. The second still quantises if `to_sprite.py`'s flood fill can\n"
              "  follow it -- this only says the masks cannot be compared.")
        return 2
    if len(separable) < len(rows):
        print(f"  {len(rows) - len(separable)} frame(s) unmeasurable (full-bleed)")

    values = sorted(result["iou"] for _stem, result in separable)
    median = values[len(values) // 2]
    worst = min(separable, key=lambda row: row[1]["iou"])
    print(f"  IoU   median {median:.3f}  min {values[0]:.3f}  ({worst[0]})")
    print(f"  verdict {'OK' if median >= GOOD_IOU else 'FAIL'} "
          f"({GOOD_IOU:.2f} is the floor for a frame whose hitboxes still apply)")
    return 0 if median >= GOOD_IOU else 1


if __name__ == "__main__":
    sys.exit(main())
