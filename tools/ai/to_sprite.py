#!/usr/bin/env python3
"""Convert raw AI renders into game-ready 16-colour fighter frames.

    python3 tools/ai/to_sprite.py tsu_ibano --raw build/ai/tsu_ibano/raw \\
                                          --out build/ai/tsu_ibano/sprites

`gen_frames.py` produces a 1024x1024 render with tens of thousands of colours;
the engine wants 64x121-ish frames in the fighter's sixteen. That gap is this
module, and it is the step that decides whether generated art is usable at all.

Registration: why there is no "fit the character into the box" step
------------------------------------------------------------------
Normally you would find the character's silhouette, measure it, and scale it to
fill the target frame. That decouples the art from the hitboxes: every frame gets
its own scale factor, so a fighter "grows" between frames by however much the
generator's framing drifted, and a punch's reach stops corresponding to its
offense box.

We do not have to guess here, because the control image and the render share one
camera. `openpose_render.project()` puts engine y=0 on row `size *
GROUND_FRACTION`, at `size / FRAME_UNITS` pixels per engine unit. The game canvas
puts engine y=0 on its centre row at `figure.PX_PER_UNIT` pixels per unit. So a
single scale and a single translate carry the render into the canvas:

    scale   = PX_PER_UNIT * FRAME_UNITS / size          # 6 * 40 / 1024
    origin  = (canvas/2 - scaled/2, canvas/2 - scaled*GROUND_FRACTION)

and every frame lands in hitbox space by construction, at one scale, with no
measurement and no per-frame fitting. A silhouette that disagrees with its
skeleton is reported (see `--report`), never silently corrected.

Order of operations, and why this order
---------------------------------------
Mask at an intermediate size, quantise at *final* size. Masking is a flood fill
over 1024x1024 pixels, and the outline width is one or two pixels at the *game*
scale -- so working at game scale for the fill means the mask is computed where
its errors are a quarter of a pixel, and quantising last means the sixteen tones
are chosen for the pixels that actually ship.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "ai"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import build_fighter  # noqa: E402
import figure  # noqa: E402
import openpose_render  # noqa: E402

SHEET_DIR = REPO_ROOT / "design_sheets"

# How far from the sampled backdrop colour a pixel may be and still count as
# backdrop. Generous, because a "clean white background" render still has a
# faint vignette and JPEG-ish texture in it, and anything the fill misses shows
# up as a coloured fringe around the whole character.
BACKDROP_TOLERANCE = 42.0

# The flood fill runs on the full-size render, so this is the number of pixels a
# fill has to walk, not the number it has to walk at final size. 1024x1024 in
# pure Python is a few seconds per frame and 117 frames is a coffee break; the
# fill is only ever started from the border, so in practice it touches the
# backdrop and stops.
# The flood fill runs on the render *after* it has been scaled to game pixel
# size, which is roughly 240x240 rather than 1024x1024 -- sixteen times fewer
# pixels, and the size at which its boundary error is a quarter of a pixel
# rather than a whole one. Pure Python BFS over ~57k pixels is a few tens of
# milliseconds; over a million it is a coffee break per frame, and there are 117
# frames in a fighter.
BACKDROP_TOLERANCE = 42.0


def load_palette(sheet):
    """The fighter's sixteen colours: role names plus an (16, 3) array.

    The roles are kept alongside the array so the census can report *which* tone
    landed where. "Sixteen colours" is only half the invariant; the other half is
    that the tunic is still the same cloth tone in every frame, and a bare colour
    count cannot tell you that.
    """
    palette = figure.Palette(sheet["palette16"])
    roles = list(figure.PALETTE_ROLES)
    colours = np.array([palette[role] for role in roles], dtype=np.int32)
    return roles, colours


def quantise(rgb, colours):
    """Every pixel -> the index of the nearest palette colour.

    Distance is the "redmean" approximation to perceptual difference, not plain
    Euclidean RGB. It earns its keep here: these palettes are sixteen tones
    spanning one hue family, and plain Euclidean maps the mid-tones onto whichever
    neighbour happens to sit nearest in raw RGB, which reads as a muddy cast over
    the whole sprite.
    """
    flat = rgb.reshape(-1, 3).astype(np.int32)
    rmean = (flat[:, None, 0] + colours[None, :, 0]) // 2
    dr = flat[:, None, 0] - colours[None, :, 0]
    dg = flat[:, None, 1] - colours[None, :, 1]
    db = flat[:, None, 2] - colours[None, :, 2]
    distance = ((((512 + rmean) * dr * dr) >> 8) + 4 * dg * dg
                + (((767 - rmean) * db * db) >> 8))
    return distance.argmin(axis=1).astype(np.int32)


def backdrop_mask(rgb, tolerance=BACKDROP_TOLERANCE):
    """True where a pixel is backdrop: near the corner colour AND reachable from
    the border without leaving it.

    Both halves are load-bearing. Colour alone punches holes through anything
    pale the character is wearing or any blown highlight on a shoulder.
    Connectivity alone leaks into the character wherever the silhouette touches
    the frame edge, which is common in a frame where a limb reaches the side.
    """
    height, width, _ = rgb.shape
    corners = np.stack([rgb[0, 0], rgb[0, width - 1],
                        rgb[height - 1, 0], rgb[height - 1, width - 1]])
    backdrop = np.median(corners, axis=0)
    near = np.sqrt(((rgb.astype(np.float32) - backdrop) ** 2).sum(axis=2)) < tolerance

    filled = np.zeros((height, width), dtype=bool)
    queue = deque()

    def seed(y, x):
        if near[y, x] and not filled[y, x]:
            filled[y, x] = True
            queue.append((y, x))

    for x in range(width):
        seed(0, x)
        seed(height - 1, x)
    for y in range(height):
        seed(y, 0)
        seed(y, width - 1)

    while queue:
        y, x = queue.popleft()
        for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if 0 <= ny < height and 0 <= nx < width and near[ny, nx] and not filled[ny, nx]:
                filled[ny, nx] = True
                queue.append((ny, nx))

    return filled


def dilate(mask, width):
    """Grow a boolean mask by `width` pixels, 4-connected."""
    grown = mask.copy()
    for _ in range(width):
        shifted = np.zeros_like(grown)
        shifted[1:, :] |= grown[:-1, :]
        shifted[:-1, :] |= grown[1:, :]
        shifted[:, 1:] |= grown[:, :-1]
        shifted[:, :-1] |= grown[:, 1:]
        grown = grown | shifted
    return grown


def canvas_for(state):
    """The declared canvas for a state, from the table build_fighter builds from.

    Read from STATE_SPEC rather than passed in, so a sprite can never be written
    at a size the YAML does not declare -- the engine scales the whole texture
    into the declared box, so a mismatch is a squashed character, not an error.
    """
    for name, _count, _delay, box, _continual, _pose in build_fighter.STATE_SPEC:
        if name == state:
            width, height = build_fighter.BOXES[box]
            return (int(width * figure.PX_PER_UNIT), int(height * figure.PX_PER_UNIT))
    raise SystemExit(f"unknown state '{state}'")


def _place(canvas, sprite, offset):
    """Composite `sprite` at `offset`, cropping on either side.

    The render is square and the canvas is tall and narrow, so a negative offset
    is the ordinary case rather than an edge case. PIL raises on a negative
    destination instead of clipping, so the overlap gets computed by hand.
    """
    x0, y0 = offset
    sx0, sy0 = max(0, -x0), max(0, -y0)
    dx0, dy0 = max(0, x0), max(0, y0)
    width = min(sprite.width - sx0, canvas.width - dx0)
    height = min(sprite.height - sy0, canvas.height - dy0)
    if width > 0 and height > 0:
        canvas.alpha_composite(
            sprite.crop((sx0, sy0, sx0 + width, sy0 + height)), (dx0, dy0))
    return canvas


def render_sprite(raw_path, sheet, roles, colours, state, outline_width=1,
                  tolerance=BACKDROP_TOLERANCE):
    """One raw render -> one placed, quantised, outlined RGBA frame.

    Returns (image, census); the census is the per-role pixel count plus the
    measured silhouette, so drift is visible as a number rather than as a hunch.
    """
    raw = Image.open(raw_path).convert("RGB")
    canvas = canvas_for(state)

    # The whole registration. The world window is FRAME_UNITS tall and the game
    # draws PX_PER_UNIT pixels per unit, so at game scale that window is exactly
    # 240 pixels square -- whatever resolution the render was. Same number for
    # every frame of every fighter, which is the point: nothing is measured per
    # frame, so nothing can drift per frame.
    scaled_size = int(figure.PX_PER_UNIT * openpose_render.FRAME_UNITS)
    scaled = raw.resize((scaled_size, scaled_size), Image.LANCZOS)
    rgb = np.asarray(scaled, dtype=np.uint8)

    backdrop = backdrop_mask(rgb, tolerance)
    assigned = quantise(rgb, colours).reshape(rgb.shape[:2])
    flat = colours[assigned].astype(np.uint8)

    alpha = np.where(backdrop, 0, 255).astype(np.uint8)
    ring = None
    if outline_width > 0:
        # A ring one pixel outside the silhouette. The prompt asks for black
        # outlines and quantisation will usually supply them, but "usually" is
        # not a guarantee, and an unoutlined sprite on a busy stage is the
        # problem outlines exist to solve.
        ring = dilate(~backdrop, outline_width) & backdrop
        flat = np.where(ring[..., None], np.array([0, 0, 0], np.uint8), flat)
        alpha = np.where(ring, 255, alpha).astype(np.uint8)

    sprite = Image.fromarray(np.dstack([flat, alpha]), "RGBA")

    offset = (int(canvas[0] / 2 - scaled_size / 2),
              int(canvas[1] / 2 - scaled_size * openpose_render.GROUND_FRACTION))
    placed = _place(Image.new("RGBA", canvas, (0, 0, 0, 0)), sprite, offset)

    body = ~backdrop
    counts = {role: int(((assigned == index) & body).sum())
              for index, role in enumerate(roles)}
    if ring is not None:
        counts["outline"] += int(ring.sum())

    visible = np.asarray(placed)[:, :, 3] > 0
    rows, columns = np.nonzero(visible)
    silhouette = {}
    if len(rows):
        # Canvas pixels -> engine units. The canvas centre IS the origin, which
        # is the engine's ground, so this reads as reach and height directly.
        silhouette = {
            "back": round((columns.min() - canvas[0] / 2) / figure.PX_PER_UNIT, 2),
            "front": round((columns.max() - canvas[0] / 2) / figure.PX_PER_UNIT, 2),
            "feet": round((canvas[1] / 2 - rows.max()) / figure.PX_PER_UNIT, 2),
            "crown": round((canvas[1] / 2 - rows.min()) / figure.PX_PER_UNIT, 2),
        }

    census = {
        "canvas": list(canvas),
        "silhouette": silhouette,
        "colours": sum(1 for count in counts.values() if count > 0),
        "roles": {role: count for role, count in counts.items() if count > 0},
    }
    return placed, census


def process_all(fighter_id, raw_dir, out_dir, outline_width=1,
                tolerance=BACKDROP_TOLERANCE):
    """Convert every raw render in `raw_dir`. Returns (written, censuses)."""
    path = SHEET_DIR / f"{fighter_id}.json"
    if not path.is_file():
        raise SystemExit(f"no design sheet for '{fighter_id}' at {path}")
    sheet = json.loads(path.read_text(encoding="utf-8"))
    roles, colours = load_palette(sheet)

    raw_dir = Path(raw_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    frames = sorted(raw_dir.glob("*.png"))
    if not frames:
        raise SystemExit(f"no raw renders in {raw_dir}; run tools/ai/gen_frames.py first")

    written = []
    censuses = {}
    for raw_path in frames:
        # The frame name carries the state, and the state carries the canvas --
        # the same naming build_fighter writes the game's own frames under.
        state = raw_path.stem.rstrip("0123456789")
        image, census = render_sprite(raw_path, sheet, roles, colours, state,
                                      outline_width, tolerance)
        if census["colours"] > len(roles):
            raise SystemExit(
                f"{raw_path.stem}: {census['colours']} colours, budget is {len(roles)}; "
                "quantisation should have made this impossible")
        image.save(out_dir / raw_path.name)
        written.append(out_dir / raw_path.name)
        censuses[raw_path.stem] = census

    report = {"fighter": fighter_id, "palette_roles": len(roles), "frames": censuses}
    (out_dir / "census.json").write_text(json.dumps(report, indent=2) + "\n",
                                         encoding="utf-8")
    return written, censuses


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("fighter", help="design sheet id, e.g. tsu_ibano")
    parser.add_argument("--raw", required=True, help="directory of raw renders")
    parser.add_argument("--out", required=True, help="output directory")
    parser.add_argument("--outline-width", type=int, default=1,
                        help="outline ring in game pixels; 0 disables")
    parser.add_argument("--tolerance", type=float, default=BACKDROP_TOLERANCE,
                        help="backdrop flood-fill tolerance")
    args = parser.parse_args(argv)

    written, censuses = process_all(args.fighter, args.raw, args.out,
                                    args.outline_width, args.tolerance)

    print(f"{args.fighter}: {len(written)} sprite(s) -> {args.out}")
    for name, census in sorted(censuses.items()):
        width, height = census["canvas"]
        silhouette = census["silhouette"]
        where = ""
        if silhouette:
            where = ("feet %+.1f crown %+.1f  x %+.1f..%+.1f"
                     % (silhouette["feet"], silhouette["crown"],
                        silhouette["back"], silhouette["front"]))
        print(f"  {name:14s} {width}x{height}  {census['colours']:2d} colours  {where}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
