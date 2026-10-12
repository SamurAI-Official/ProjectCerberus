#!/usr/bin/env python3
"""Derive a fighter's sixteen colours from the reference sheet they were drawn from.

    python3 tools/ai/ref_palette.py --qc build/ai/refs tsu_ibano
    python3 tools/ai/ref_palette.py --write tsu_ibano
    python3 tools/ai/ref_palette.py --check

The palette is not an opinion, it is a measurement. Every role is a tone of a
named region of the reference sheet -- the front view's jacket, the side view's
trousers, the tie, the hair -- so "what colour is Tsu's blazer" has an answer you
can re-run rather than an answer somebody typed. The sample boxes live in the
design sheet (`reference.samples`, in sheet pixels) because they are specific to
one drawing; the role -> (box, tone) table lives here because it is the same for
every fighter.

Why this matters more than it looks
------------------------------------
`figure.render` bakes these sixteen tones into the puppet, and `gen_frames.py`
repaints that puppet with img2img. The sampler inherits the palette from the
init image, so a role that is the wrong colour is a character who is the wrong
colour in every frame of every state -- and, because each frame is a separate
sample, a *different* wrong colour from frame to frame. Getting the sixteen right
up front is what makes the generated sheet look like one person.

Tones, and why 16 distinct ones
-------------------------------
Only nine regions get sampled, but there are sixteen roles: each material
contributes a lit, a base and a shaded tone. `validate_manifest.py` requires the
sixteen to be *distinct* -- a duplicate is a tone that would go missing in a 2P
palette swap -- so `derive` refuses to return a palette with a collision and
says which two roles collided and which boxes they came from.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import figure  # noqa: E402

SHEET_DIR = REPO_ROOT / "design_sheets"

# role -> (sample name, tone). The sample names are resolved against
# `reference.samples` in the design sheet.
ROLE_SOURCE = {
    "skin_light": ("face", "light"),
    "skin": ("face", "mid"),
    "skin_shadow": ("face", "shadow"),

    # The blazer is the biggest flat area on the sheet and the one that has to
    # hold still, so all three of its tones come from the front view.
    "cloth_light": ("jacket", "light"),
    "cloth": ("jacket", "mid"),
    "cloth_shadow": ("jacket", "shadow"),

    # `figure.render` paints the far arm with `limb_light` and the far leg with
    # `limb`/`limb_shadow`, so those two roles are different materials: a sleeve
    # and a pair of trousers. Naming them by the material rather than by the role
    # is the only way this table stays readable.
    "limb_light": ("sleeve", "mid"),
    "limb": ("trousers", "mid"),
    "limb_shadow": ("trousers", "shadow"),

    # The near leg and near arm are drawn in front of the body, so they need
    # tones that separate from the ones behind them. They are the shaded band of
    # the same two materials -- a leg in front of a leg, an arm in front of a
    # jacket -- and `derive` steps them clear of `limb_shadow`/`cloth_shadow`
    # rather than pretending the sheet has a fourth tone for each.
    "far": ("trousers", "shadow"),
    "far_shadow": ("jacket", "shadow"),

    "accent": ("tie", "mid"),
    "accent_shadow": ("tie", "shadow"),

    "highlight": ("collar", "light"),
    "eye": ("hair", "mid"),
    # outline is forced to pure black by figure.Palette; listed here so the
    # count of derived roles is stated rather than implied.
    "outline": ("hair", "mid"),
}

# Roles whose tone is allowed to be nudged when two of them collide, and which
# way to move them. Light tones step lighter, shadow tones step darker, and the
# base tones are the ones defended -- a nudge on a base tone would change what
# the character *is*, while a nudge on a highlight is a lighting decision.
NUDGE = {
    "skin_light": +1, "skin": 0, "skin_shadow": -1,
    "cloth_light": +1, "cloth": 0, "cloth_shadow": -1,
    "limb_light": +1, "limb": 0, "limb_shadow": -1,
    "far": -1, "far_shadow": -1,
    "accent": 0, "accent_shadow": -1,
    "highlight": +1, "eye": 0,
}

# Order collisions are resolved in: the base tones are claimed first, so a
# highlight is the role that moves, never the jacket.
RESOLVE_ORDER = ("outline", "cloth", "skin", "limb", "far", "eye", "accent",
                 "cloth_light", "cloth_shadow", "skin_light", "skin_shadow",
                 "limb_light", "limb_shadow", "far_shadow", "accent_shadow",
                 "highlight")

MAX_NUDGE = 24


def load_sheet(fighter_id: str) -> tuple[Path, dict]:
    path = SHEET_DIR / f"{fighter_id}.json"
    if not path.is_file():
        raise SystemExit(f"no design sheet for '{fighter_id}' at {path}")
    return path, json.loads(path.read_text(encoding="utf-8"))


"""Materials, as hue predicates.

A sample region is chosen generously -- the whole front of the blazer, both legs
-- and then narrowed by *what the material is made of*. That matters more than it
sounds: a character sheet is a busy drawing, and the school satchel's strap
crosses the chest of both fighters. A box placed to dodge the strap is a box that
has to be re-placed whenever the drawing changes; a predicate that says "blue"
cannot be fooled by a grey strap at all.

The predicates are deliberately loose. Two hues that are genuinely adjacent --
skin and khaki trousers are both warm oranges -- cannot be separated by colour, so
the *region* is what separates them: the face box is on the head, the trousers box
is on the legs. Colour alone decides within a region; the region decides between
them.
"""

MATERIALS = {
    # Cerulean blazer: blue dominant, and light enough to be a garment rather
    # than a shadow.
    "blue": lambda px: (px[:, 2] > px[:, 0] + 30) & (px[:, 2] > 90),
    # Tan trousers: warm, with green above blue, which is what makes it tan
    # rather than orange.
    "khaki": lambda px: ((px[:, 0] > px[:, 2] + 30) & (px[:, 0] > 120)
                         & (px[:, 1] > px[:, 2]) & (px[:, 1] < px[:, 0])),
    # The necktie.
    "red": lambda px: (px[:, 0] > px[:, 1] + 45) & (px[:, 0] > px[:, 2] + 45),
    # The shirt collar. Paper is the same white, which is why the collar region
    # is on the neck and not, say, "the top of the sheet".
    "white": lambda px: px.min(axis=1) > 195,
    # Skin. The lightness floor is doing real work here: a dark warm red (a
    # necktie, a badge, a mouth line) satisfies "warm and orange-ish" perfectly
    # well, and on Fei Young's sheet the flung tie crosses the face region. Skin
    # is the only warm thing on either sheet that is also *pale*, so requiring a
    # floor of 110 on the darkest channel separates it from the tie, from the
    # tan trousers, and from the ink, without a region having to dodge any of
    # them.
    "skin": lambda px: ((px[:, 0] > px[:, 2] + 35) & (px[:, 0] > 165)
                        & (px[:, 0] > px[:, 1]) & (px[:, 1] > px[:, 2])
                        & (px.min(axis=1) > 110)),
    # Hair, and only hair: darker than 120 but NOT ink. Ink is pure black, so
    # requiring at least 48 separates hair from the outlines drawn around it --
    # without that the hair's darkest band would be the line art.
    "dark": lambda px: (px.max(axis=1) >= 48) & (px.max(axis=1) < 120),
}


def sample_pixels(sheet_px: np.ndarray, spec: dict) -> np.ndarray:
    """The pixels of one material inside one region of the sheet."""
    box = spec["box"] if isinstance(spec, dict) else spec
    material = spec.get("material") if isinstance(spec, dict) else None
    x0, y0, x1, y1 = (int(v) for v in box)
    sub = sheet_px[y0:y1, x0:x1].reshape(-1, 3).astype(int)
    if not len(sub):
        raise SystemExit(f"sample region {box} is empty")

    if material is None:
        # Not every region needs a predicate -- the face and the hair are the
        # only warm-dark things on a head -- but the ink and the paper always
        # have to go, or the darkest band is an outline and the lightest is the
        # grid the sheet is drawn on.
        hi, lo = sub.max(axis=1), sub.min(axis=1)
        keep = sub[~((hi < 48) | ((hi - lo < 22) & (lo > 150)))]
    else:
        try:
            predicate = MATERIALS[material]
        except KeyError:
            raise SystemExit(
                f"unknown material '{material}'; known: "
                f"{', '.join(sorted(MATERIALS))}") from None
        keep = sub[predicate(sub)]

    if len(keep) < 24:
        raise SystemExit(
            f"sample region {box} ({material or 'unfiltered'}) holds {len(keep)} "
            "usable pixel(s). Either the region is off the drawing, or the "
            "material predicate does not match what is inside it.")
    return keep


def tone(pixels: np.ndarray, which: str) -> tuple:
    """One tone out of a region: its lit, base or shaded band."""
    lum = pixels @ np.array([0.299, 0.587, 0.114])
    order = np.argsort(lum)
    n = len(order)
    if which == "light":
        band = order[max(n - max(4, n // 7), 0):]
    elif which == "shadow":
        band = order[:max(4, n // 8)]
    else:
        lo = int(n * 0.42)
        band = order[lo:max(int(n * 0.58), lo + 1)]
    return tuple(int(v) for v in np.median(pixels[band], axis=0))


def _step(colour: tuple, direction: int) -> tuple:
    return tuple(int(v) + direction for v in colour)


def derive(sheet: dict) -> dict:
    """The sixteen roles, measured. Raises rather than returning a collision."""
    sheet_px, path = sheet_image(sheet)
    samples = sheet["reference"]["samples"]

    palette = {}
    for role, (sample, which) in ROLE_SOURCE.items():
        if sample not in samples:
            raise SystemExit(
                f"design sheet '{sheet['id']}' is missing sample '{sample}' "
                f"(needed for role '{role}') from {path}")
        palette[role] = tone(sample_pixels(sheet_px, samples[sample]), which)

    # Two roles may not share a tone, and with three tones taken from each of a
    # handful of regions a collision is a real possibility -- the flat cel fill
    # of a jacket is a wide plateau, so its "lit" band can be the same colour as
    # its "base" band. Resolve in a fixed priority order so the outcome does not
    # depend on dict ordering, and report every move.
    notes = []
    for role in RESOLVE_ORDER:
        if role == "outline":
            continue
        for _ in range(MAX_NUDGE):
            clash = next((other for other in RESOLVE_ORDER
                          if other != role and other != "outline"
                          and palette[other] == palette[role]), None)
            if clash is None:
                break
            direction = NUDGE[role]
            if direction == 0:
                raise SystemExit(
                    f"'{role}' and '{clash}' are both {palette[role]} on "
                    f"{path.name}, and '{role}' is a base tone that must not "
                    "move. Move or widen the sample box for one of them.")
            palette[role] = _step(palette[role], direction)
            notes.append(f"{role} {direction:+d} away from {clash}")
        else:
            raise SystemExit(f"could not separate '{role}' from its neighbours")

    palette["outline"] = (0, 0, 0)
    return palette, notes


def draw_samples(sheet: dict, out_path: Path) -> None:
    """The sheet with the sample boxes drawn on it, so the boxes can be checked."""
    from PIL import ImageDraw

    image = Image.open(REPO_ROOT / sheet["reference"]["sheet"]).convert("RGB")
    draw = ImageDraw.Draw(image)
    for name, spec in sorted(sheet["reference"]["samples"].items()):
        box = spec["box"] if isinstance(spec, dict) else spec
        draw.rectangle([int(v) for v in box], outline=(255, 0, 255), width=2)
        label = name if not isinstance(spec, dict) else f"{name}:{spec.get('material', '-')}"
        draw.text((int(box[0]) + 4, int(box[1]) + 3), label, fill=(255, 0, 255))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path)


def _frame_for(state: str, index: int):
    """One rendered frame of `state`, using the same pose the build uses."""
    import build_fighter

    spec = next(entry for entry in build_fighter.STATE_SPEC if entry[0] == state)
    _state, _count, _delay, box, _continual, pose_name = spec
    canvas = tuple(int(dim * figure.PX_PER_UNIT) for dim in build_fighter.BOXES[box])
    builder = build_fighter.POSES.get(pose_name, build_fighter.POSES["idle"])
    return figure.pose(**builder(index, spec[1], {})), canvas


def draw_palette(sheet: dict, palette: dict, out_path: Path) -> None:
    """A swatch grid, and the puppet drawn with it, at the size the game draws it."""
    from PIL import ImageDraw

    cell = 54
    grid = Image.new("RGB", (cell * 6, cell * 3 + 8), (24, 24, 28))
    draw = ImageDraw.Draw(grid)
    for index, role in enumerate(figure.PALETTE_ROLES):
        x, y = (index % 6) * cell, (index // 6) * cell
        draw.rectangle([x, y, x + cell - 2, y + cell - 2], fill=palette[role])
        draw.text((x + 4, y + cell - 16), role, fill=(255, 0, 255))

    poses = (("idle", 0), ("start", 0), ("walk_forward", 3), ("2punch", 2),
             ("3kick", 1), ("special", 2), ("hurt_mid", 1), ("knocked_down", 1),
             ("block_high", 0))
    strip = Image.new("RGB", (cell * len(poses), 3 * cell), (196, 208, 214))
    rendered = figure.Palette(palette)
    for column, (state, index) in enumerate(poses):
        skeleton, canvas = _frame_for(state, index)
        frame = figure.render(skeleton, canvas, rendered)
        scale = (3 * cell) / frame.height
        frame = frame.resize((max(1, int(frame.width * scale)), 3 * cell), Image.NEAREST)
        backdrop = Image.new("RGB", frame.size, (196, 208, 214))
        backdrop.paste(frame, (0, 0), frame)
        strip.paste(backdrop, (column * cell + (cell - frame.width) // 2, 0))

    out = Image.new("RGB", (max(grid.width, strip.width),
                            grid.height + strip.height), (24, 24, 28))
    out.paste(grid, (0, 0))
    out.paste(strip, (0, grid.height))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.save(out_path)


def as_sheet_block(palette: dict) -> dict:
    return {role: list(palette[role]) for role in figure.PALETTE_ROLES}


def sheet_image(sheet: dict) -> tuple[np.ndarray, Path]:
    """The reference sheet as an array, and where it was found.

    Paper and grid lines are the same near-neutral light grey, and the annotation
    text is the same near-black as the ink, so neither can be told from the
    drawing by colour alone. That is why the regions are sampled by hand: a
    region is chosen where the material fills the box, and everything that is
    not that material (a strap crossing the chest, an eyebrow) is kept out of the
    box by where the box is placed rather than by a filter that guesses.
    """
    block = sheet.get("reference")
    if not block:
        raise SystemExit(
            f"design sheet '{sheet['id']}' has no 'reference' block.\n"
            "Add one: {\"sheet\": \"design_sheets/refs/<id>_sheet.jpeg\",\n"
            "          \"samples\": {\"face\": [x0, y0, x1, y1], ...}}")
    path = REPO_ROOT / block["sheet"]
    if not path.is_file():
        raise SystemExit(f"reference sheet for '{sheet['id']}' is missing: {path}")
    return np.asarray(Image.open(path).convert("RGB")), path


def report(fighter_id: str, palette: dict, notes, args) -> None:
    print(f"{fighter_id}  ({args.source})")
    for role in figure.PALETTE_ROLES:
        red, green, blue = palette[role]
        print(f"    {role:14s} #{red:02x}{green:02x}{blue:02x}  "
              f"rgb({red:3d},{green:3d},{blue:3d})")
    for note in notes:
        print(f"    note  {note}")


def probe(sheet: dict, palette: dict) -> None:
    """Every sample's tone bands, next to the roles that were taken from them."""
    sheet_px, _ = sheet_image(sheet)
    for name, spec in sorted(sheet["reference"]["samples"].items()):
        pixels = sample_pixels(sheet_px, spec)
        bands = "  ".join(
            "%s=#%02x%02x%02x" % ((which,) + tone(pixels, which))
            for which in ("light", "mid", "shadow"))
        users = [role for role, (sample, _t) in ROLE_SOURCE.items() if sample == name]
        print(f"    sample {name:16s} n={len(pixels):5d}  {bands}")
        print(f"           -> {', '.join(users) or 'unused'}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("fighter", nargs="?",
                        help="design sheet id; omit to cover every sheet with --check")
    parser.add_argument("--write", action="store_true",
                        help="write the derived palette16 into the design sheet")
    parser.add_argument("--check", action="store_true",
                        help="compare the stored palette against a fresh derivation")
    parser.add_argument("--qc", metavar="DIR",
                        help="write the sample overlay and the swatch sheet here")
    parser.add_argument("--probe", action="store_true",
                        help="print every sample's tone bands")
    args = parser.parse_args(argv)

    if not args.fighter and not args.check:
        parser.print_help()
        return 2

    if args.fighter:
        fighters = [args.fighter]
    else:
        fighters = sorted(path.stem for path in SHEET_DIR.glob("*.json"))

    failures = 0
    for fighter_id in fighters:
        path, sheet = load_sheet(fighter_id)
        if not sheet.get("reference"):
            print(f"  skip  {fighter_id}: no 'reference' block, nothing to measure")
            continue

        palette, notes = derive(sheet)
        args.source = sheet["reference"]["sheet"]
        report(fighter_id, palette, notes, args)
        if args.probe:
            probe(sheet, palette)

        if args.check:
            stored = sheet.get("palette16", {})
            drift = [role for role in figure.PALETTE_ROLES
                     if list(stored.get(role, ())) != list(palette[role])]
            if drift:
                failures += 1
                print(f"  FAIL  {fighter_id} palette16 no longer matches "
                      f"{args.source}: {', '.join(drift)}")
                print("        re-run with --write to accept the new measurement")
            else:
                print(f"  OK    {fighter_id} palette16 matches its reference sheet")

        if args.write:
            sheet["palette16"] = as_sheet_block(palette)
            path.write_text(json.dumps(sheet, indent=2) + "\n", encoding="utf-8")
            print(f"  wrote {path.relative_to(REPO_ROOT)}")

        if args.qc:
            out = Path(args.qc)
            if not out.is_absolute():
                out = REPO_ROOT / out
            draw_samples(sheet, out / f"{fighter_id}_samples.png")
            draw_palette(sheet, palette, out / f"{fighter_id}_palette.png")
            print(f"  qc    {out.relative_to(REPO_ROOT)}/{fighter_id}_samples.png")
            print(f"  qc    {out.relative_to(REPO_ROOT)}/{fighter_id}_palette.png")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
