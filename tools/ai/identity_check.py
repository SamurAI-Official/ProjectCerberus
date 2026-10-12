#!/usr/bin/env python3
"""Is this frame still the same character as the sheet it was conditioned on?

    python3 tools/ai/identity_check.py build/ai/refA build/ai/refB
    python3 tools/ai/identity_check.py build/ai/refB --selftest

`frame_fidelity.py` answers "is the figure where the drawing put it", which is the
question the hitboxes care about. This answers the other one, and it is the one the
two reference arms exist to settle: the skeleton owns the pose, but the *character*
-- the jacket, the hair, the trousers -- comes from the design sheet, and a sampler
is free to hand back a figure in the right place wearing the wrong colours.

The sheet has already been measured, by `ref_palette.py`, into sixteen tones that
`figure.render` bakes into the puppet and that img2img inherits from its init. So
"the same character" has a number: the share of the figure painted in those tones.

Per frame, over the figure's mask (the same mask, and the same speck filter, as the
pose score):

  * **kept** -- the share of figure pixels within `TONE_DISTANCE` of any of the
    sixteen measured tones. A frame at 0.6 has four pixels in ten that the sheet's
    palette cannot name.
  * **head / torso / legs** -- the same share, but only against the tones that
    belong in that band of the figure (head: hair, skin and the collar, torso:
    blazer, sleeve, collar and tie, legs: trousers). This catches the failure
    `kept` cannot: a figure painted entirely from the sheet's palette, with the
    trousers in the blazer's blue. The head band is reported but cannot be judged
    -- see `JUDGED_BANDS` -- and the torso and legs are. For a pose that is not
    upright the bands are cut along the body's own bones rather than across its
    bounding box (`skeleton_bands`), because a horizontal slice through a figure
    lying on the ground is not a body part; the report names how many frames were
    cut each way.
  * each band's median colour, printed as hex, because "the jacket moved 18/255
    sideways across a state" is a thing you want to see rather than infer.

And per directory, the number that a per-frame score cannot see at all: **drift**,
the largest colour distance between two frames' version of the same band *within one
state*. Frames of one state differ only in the breathing cycle, so they should be the
same character; eight frames that are each 60% right and each wrong *differently* are
several people wearing one name, and `ref_palette.py`'s docstring is explicit that
this is what stops a generated sheet reading as one character. Drift is reported
rather than passed or failed: low drift with low `kept` is a character who is
consistently somebody else.

`--selftest` runs the whole thing again over a hue-rotated copy of the frames, so
the floor below is shown failing something. A metric that has never failed anything
is not a measurement.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "ai"))

import frame_fidelity  # noqa: E402
import openpose_render  # noqa: E402
import ref_palette  # noqa: E402

# How far a pixel may be from one of the sheet's tones and still be that tone. Wider than the
# pixel-to-pixel tolerance in the other two tools, because this is not comparing two drawings: a
# generated frame has gradients where the sheet has flat cel fill, so the tone the sheet measured
# comes back as a small cloud around itself.
TONE_DISTANCE = 56.0

# Bands, as fractions of the figure's own height, and the sample regions that are allowed to
# appear in them. The bands assume an upright figure -- the same assumption the hitboxes make --
# so a knocked-down frame is measured as if it were standing and its bands are not meaningful;
# the pose score is the one that matters there.
BANDS = (
    ("head", 0.00, 0.22, ("hair", "face", "collar")),
    ("torso", 0.22, 0.60, ("jacket", "sleeve", "collar", "tie")),
    ("legs", 0.60, 1.00, ("trousers",)),
)

# The bones the bands are cut along when the figure is not upright, as (band, from, to) over the
# joint names `figure.pose` returns. See `skeleton_bands`.
BONES = (
    ("head", "head", "neck"),
    ("torso", "neck", "pelvis"),
    ("torso", "shoulder_far", "elbow_far"),
    ("torso", "elbow_far", "hand_far"),
    ("torso", "shoulder_near", "elbow_near"),
    ("torso", "elbow_near", "hand_near"),
    ("legs", "hip_far", "knee_far"),
    ("legs", "knee_far", "foot_far"),
    ("legs", "hip_near", "knee_near"),
    ("legs", "knee_near", "foot_near"),
)

# The head band cannot be judged, only reported: on a 512px frame it also holds the shoulders, and
# a blazer is not a head material, so a perfect frame tops out near 0.7 there. Measured -- 0.65 on
# arm A, 0.52 on the img2img run, 0.55 on the hue-rotated control -- which is no separation at all.
# The torso and the legs do separate (0.65/0.56 against 0.41/0.02), and they are also where a wrong
# material is a wrong character rather than a band boundary. So the verdict rests on them, and the
# head band is printed for the reader.
#
# What a band *is* is a share of the figure mask's own bounding box, and the three above assume a
# figure standing up. `knocked_down` is not one: its box is wide and short, so "torso" is the middle
# of whatever is lying there -- a leg, a sleeve, a bit of backdrop. Measured on the game's own art
# for that state, which cannot be off-palette at all, the box bands came back head 0.54 / torso 0.50
# / legs 0.57, with the torso's median colour *#a18757*: a trouser leg, scored as a torso. That made
# the torso band the floor for a pose and read an honest img2img frame (torso 0.35) as FAIL.
#
# So a pose that is not upright is cut along the body's own bones instead -- see `skeleton_bands` --
# and the same measurements read head 1.00 / torso 0.65 / legs 0.65 for the game's art (torso median
# *#417a90*, the blazer) and torso 0.56 for the img2img frame, which is OK. `build/puppet_control.py`
# writes that control for any state and `build/upright_probe.py` prints the geometry the decision is
# made from. The cut is scoped to the poses that break the box rather than applied everywhere,
# because every number the floors were set from was measured standing.
JUDGED_BANDS = ("torso", "legs")

# The floors. Set from the measurements `main`'s docstring records, not from caution: the arms and
# the hue-rotated control are all measured against them in this file's own output.
GOOD_KEPT = 0.80
GOOD_BAND = 0.50

# Drift is reported rather than passed or failed -- low drift with low `kept` is a character who is
# consistently somebody else -- so this is the line above which the report says the batch disagrees
# with itself rather than calling it a failure.
DRIFT_NOTICE = 30.0


def sheet_tones(sheet: dict) -> dict:
    """Every sample region's three tones, measured off the sheet."""
    sheet_px, _path = ref_palette.sheet_image(sheet)
    tones = {}
    for name, spec in sheet["reference"]["samples"].items():
        pixels = ref_palette.sample_pixels(sheet_px, spec)
        tones[name] = {which: np.asarray(ref_palette.tone(pixels, which), float)
                       for which in ("light", "mid", "shadow")}
    return tones


def _segment_distance(points: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Distance from every (x, y) in `points` to the segment a-b, in pixels."""
    ab = b - a
    length_sq = float((ab ** 2).sum())
    if length_sq <= 1e-9:
        return np.sqrt(((points - a) ** 2).sum(axis=1))
    t = np.clip(((points - a) @ ab) / length_sq, 0.0, 1.0)
    closest = a + t[:, None] * ab
    return np.sqrt(((points - closest) ** 2).sum(axis=1))


# How much more vertical than horizontal the head-to-pelvis line has to be for a pose to count as
# upright. Measured off the build's own skeletons (see `build/upright_probe.py`): standing states put
# the head directly above the pelvis, `knocked_down`/`hit_ground`/`ground` put it 140 pixels to the
# side of it (ratios 0.18, 0.07, 0.03) and `hurt_air` -- a figure thrown backwards with the head
# still well above the hips (ratio 0.62) -- sits in between. The floor is what makes those three
# banded along the body, which is the point; `hurt_air` is a judgement call that the puppet control
# settles, because a cut that makes the game's own art read *worse* is the wrong cut.
UPRIGHT_RATIO = 1.0


def upright(joints: dict) -> bool:
    """Is the figure standing? Head above the pelvis, and not out to the side of it."""
    across = abs(joints["head"][0] - joints["pelvis"][0])
    above = joints["pelvis"][1] - joints["head"][1]
    return above > 0 and above >= UPRIGHT_RATIO * across


def skeleton_bands(mask: np.ndarray, joints: dict) -> dict:
    """Bands decided by the nearest *bone*, for a figure the box bands cannot cut.

    Every figure pixel joins the band of the bone it is closest to. On an upright figure this lands
    within a few pixels of the box bands; on one lying on the ground -- where the box is wide and
    short, and a horizontal slice through it is not a body part -- it is the only cut that means
    anything. The arm bones carry the torso band, because a sleeve is a torso material and a hand at
    the hip is not a trouser.
    """
    ys, xs = np.nonzero(mask)
    points = np.stack([xs, ys], axis=1).astype(float)
    distances = np.stack([
        _segment_distance(points, np.asarray(joints[start], float), np.asarray(joints[end], float))
        for _band, start, end in BONES])
    nearest = np.argmin(distances, axis=0)
    out = {name: np.zeros_like(mask) for name, _start, _end, _samples in BANDS}
    for index, (band, _start, _end) in enumerate(BONES):
        chosen = nearest == index
        out[band][ys[chosen], xs[chosen]] = True
    return out


def band_masks(mask: np.ndarray, joints: dict | None = None) -> dict:
    """The figure's mask, split into bands across its own height.

    `joints`, when the figure is not upright, switches the cut to `skeleton_bands`: the box bands
    assume a standing figure, which is the same assumption the hitboxes make and is the reason this
    is scoped to the poses that break it rather than applied to every frame -- the numbers the
    floors were set from were all measured standing.

    The head band is the exception among the box-cut bands, and the torso and legs join it on the
    poses that move. A box slice is a body part only while the figure holds one shape; a kick
    extends a leg through the torso's rows, a stand sways, a hurt recoils, and the slice then reads
    a limb or a shadow where it meant the blazer. Measured over Tsu Ibano's img2img batch, cutting
    the torso along the bone instead of the box takes 3kick 77->29, stand 52->23, 2kick 54->35,
    block_low 37->16, hurt_mid 39->23 -- the poses whose silhouette changes within the state -- and
    is a wash (within a few points either way) on the rest. So all three bands are bone-cut here,
    which is the same cut `skeleton_bands` already applies to a figure that is not upright; the box
    is kept only as the fallback for a frame with no skeleton to cut along.

    The non-upright states (knocked_down, hit_ground, hurt_air, ground) already took the bone path
    before this and are unchanged by it -- the numbers that argued for scoping the cut to the box
    were measured on standing figures, and the only upright state the bone reads worse is 2punch
    (torso 22->28), which stays under the notice line and so is not a failure either way.
    """
    if joints is not None:
        return skeleton_bands(mask, joints)
    rows = np.nonzero(mask.any(axis=1))[0]
    if not len(rows):
        return {}
    top, bottom = int(rows[0]), int(rows[-1]) + 1
    height = max(bottom - top, 1)
    out = {}
    for name, start, end, _samples in BANDS:
        first = top + int(start * height)
        last = max(top + int(end * height), first + 1)
        band = np.zeros_like(mask)
        band[first:last] = mask[first:last]
        out[name] = band
    return out


def nearest(colours: np.ndarray, tones: list) -> np.ndarray:
    """How far each colour is from the closest of `tones`."""
    stack = np.stack(tones)
    return np.sqrt(((colours[:, None, :] - stack[None, :, :]) ** 2).sum(axis=2)).min(axis=1)


def measure(image: Image.Image, tones: dict, palette: dict, joints: dict | None = None) -> dict:
    """One frame, scored against the sheet.

    `joints` is the skeleton the frame was rendered from, in this image's own pixels, when the caller
    has it: it is what lets a lying frame be banded along the body instead of along the box around
    it. See `band_masks`.
    """
    rgb = np.asarray(image.convert("RGB")).astype(float)
    mask = frame_fidelity.mask_of(image)
    if not mask.any():
        return {}
    every = [np.asarray(tone, float) for tone in palette.values()]
    along_body = joints is not None and not upright(joints)
    result = {"kept": float((nearest(rgb[mask], every) <= TONE_DISTANCE).mean()),
              "bands": {},
              "bands_from": "skeleton" if along_body else "box"}
    for name, band in band_masks(mask, joints).items():
        samples = next(entry[3] for entry in BANDS if entry[0] == name)
        allowed = [np.asarray(tone, float)
                   for sample in samples for tone in tones[sample].values()]
        pixels = rgb[band]
        result["bands"][name] = {
            "share": float((nearest(pixels, allowed) <= TONE_DISTANCE).mean()),
            "med": np.median(pixels, axis=0)}
    return result


def joints_of(stem: str, size: int) -> dict | None:
    """The build's skeleton for one frame, in that frame's own pixels.

    Taken from `ref_palette._frame_for`, which uses the same pose the build and the renderer use, so
    a frame lying on the ground can be banded along its own body (see `skeleton_bands`). None when
    the name is not a state the build knows: a stray file is measured with the box bands rather than
    skipped, because a frame it cannot band is still a frame the reader should see scored.
    """
    state = state_of(stem)
    digits = stem[len(state):]
    if not digits.isdigit():
        return None
    try:
        skeleton, _canvas = ref_palette._frame_for(state, int(digits))
    except (KeyError, StopIteration):
        return None
    return {name: openpose_render.project(point, size) for name, point in skeleton.items()}


def measure_dir(out_dir: Path, tones: dict, palette: dict) -> list:
    """Every raw render under one output directory, scored."""
    raws = sorted((out_dir / "raw").glob("*.png"))
    if not raws:
        raise SystemExit(f"no raw renders under {out_dir / 'raw'}")
    rows = []
    for raw in raws:
        image = Image.open(raw)
        rows.append((raw.stem, measure(image, tones, palette, joints_of(raw.stem, image.size[0]))))
    return rows


def state_of(stem: str) -> str:
    """`idle03` -> `idle`: the frames that hold one pose, and so should hold one character."""
    return stem.rstrip("0123456789").rstrip("_") or stem


def drift_of(rows: list) -> tuple:
    """The largest colour distance between two frames' version of one band, within one state.

    Within a state, not across the batch. A batch deliberately mixes poses, and a different pose
    moves the band boundaries over different materials, which moves a band's median colour for
    entirely honest reasons -- measured across a mixed batch, even the img2img run that inherits
    the palette from its init reads 250 of 255 and says nothing. Within one state the frames differ
    only in the breathing cycle, so whatever distance is left is the sampler's, which is what this
    number is for.
    """
    states = {}
    for stem, row in rows:
        if row:
            states.setdefault(state_of(stem), []).append(row)
    worst = ("", "", 0.0)
    for state, group in sorted(states.items()):
        for name, _start, _end, _samples in BANDS:
            medians = [row["bands"][name]["med"] for row in group if name in row["bands"]]
            if len(medians) < 2:
                continue
            stack = np.stack(medians)
            spread = float(np.sqrt(((stack[:, None, :] - stack[None, :, :]) ** 2)
                                   .sum(axis=2)).max())
            if spread > worst[2]:
                worst = (state, name, spread)
    return worst


def report(title: str, rows: list, quiet: bool) -> int:
    """Print one directory's frames and totals; return 0 when it is a character."""
    usable = [(stem, row) for stem, row in rows if row]
    print(f"{title} ({len(usable)} frame(s))")
    if not usable:
        print("  no frame has a figure in it: the backdrop rule found nothing to measure")
        return 2
    for stem, row in usable:
        if quiet:
            break
        bands = "  ".join(f"{name}={row['bands'][name]['share']:.2f}"
                          for name, *_ in BANDS)
        colours = "  ".join(
            f"{name}#{''.join(f'{int(v):02x}' for v in row['bands'][name]['med'])}"
            for name, *_ in BANDS)
        print(f"  {stem:16s} kept={row['kept']:.2f}  {bands}")
        print(f"  {'':16s} {colours}")

    kept = sorted(row["kept"] for _stem, row in usable)
    median = kept[len(kept) // 2]
    shares = {name: sorted(row["bands"][name]["share"] for _stem, row in usable)
              for name, *_ in BANDS}
    band_median = {name: values[len(values) // 2] for name, values in shares.items()}
    drift_state, drift_band, drift = drift_of(usable)

    print(f"  kept   median {median:.2f}  min {kept[0]:.2f}")
    print("  bands  " + "  ".join(f"{name} {value:.2f}"
                                  for name, value in band_median.items())
          + "   (share painted in the tones the sheet gives that band)")
    along_body = sum(1 for _stem, row in usable if row.get("bands_from") == "skeleton")
    if along_body:
        # Named, not silent: the same frame reads differently under the two cuts, so which cut
        # produced a number is part of the number.
        print(f"  cut    {along_body} frame(s) banded along the body, not by the box around it "
              f"(the figure is not upright)")
    if drift_state:
        print(f"  drift  {drift:.1f} of 255 between frames of one state (worst: {drift_band} "
              f"in {drift_state})"
              + ("  -- past the notice line, so those frames disagree about it"
                 if drift > DRIFT_NOTICE else ""))
    else:
        print("  drift  n/a: this batch has one frame per state, and drift is a distance "
              "between two")
    judged = min((band_median[name] for name in JUDGED_BANDS), default=0.0)
    good = median >= GOOD_KEPT and judged >= GOOD_BAND
    print(f"  verdict {'OK' if good else 'FAIL'} (kept {GOOD_KEPT:.2f} and "
          f"{'/'.join(JUDGED_BANDS)} {GOOD_BAND:.2f} are the floors; weakest judged band "
          f"{min(JUDGED_BANDS, key=lambda name: band_median[name])} "
          f"{min(band_median[name] for name in JUDGED_BANDS):.2f})")
    return 0 if good else 1


def hue_control(out_dir: Path, shift: int = 85) -> Path:
    """A copy of the frames with every hue rotated, so the floors can be seen failing."""
    tmp = Path(tempfile.mkdtemp(prefix="identity_control_"))
    (tmp / "raw").mkdir()
    for raw in sorted((out_dir / "raw").glob("*.png")):
        hsv = np.asarray(Image.open(raw).convert("HSV")).copy()
        hsv[:, :, 0] = (hsv[:, :, 0].astype(int) + shift) % 256
        Image.fromarray(hsv, "HSV").convert("RGB").save(tmp / "raw" / raw.name)
    return tmp


def fighter_of(out_dir: Path, override) -> str:
    """Which sheet to measure against: the run's own manifest, or an explicit override."""
    if override:
        return override
    manifest = out_dir / "manifest.json"
    if manifest.is_file():
        try:
            return json.loads(manifest.read_text(encoding="utf-8"))["fighter"]
        except (KeyError, ValueError):
            pass
    raise SystemExit(f"cannot tell which fighter {out_dir} was built from: it has no readable "
                     "manifest.json, so pass --fighter")


def main(argv=None) -> int:
    """Score each directory, and optionally score a hue-rotated copy of the last one.

    The floors are set from what has been measured rather than chosen: Tsu Ibano's reference arm
    returns kept 0.9x with every band 0.8x and up, a hue-rotated copy of those same frames drops
    to kept 0.2x with bands at 0.0x, and the empty-latent canny probe -- the mode that ignores
    the init and paints what it likes, whose pose score is already 0.46 -- lands between them.
    """
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("out_dirs", nargs="+",
                        help="gen_frames.py output directories (each needs raw/)")
    parser.add_argument("--fighter", help="takes the sheet from here instead of the manifest")
    parser.add_argument("--quiet", action="store_true", help="totals only")
    parser.add_argument("--selftest", action="store_true",
                        help="also score a hue-rotated copy, to show the floors failing")
    args = parser.parse_args(argv)

    dirs = [Path(d) if Path(d).is_absolute() else REPO_ROOT / d for d in args.out_dirs]
    _path, sheet = ref_palette.load_sheet(fighter_of(dirs[0], args.fighter))
    tones = sheet_tones(sheet)
    palette, notes = ref_palette.derive(sheet)
    if notes:
        print(f"the palette for {sheet['id']} was nudged to keep its tones distinct: "
              f"{'; '.join(notes)}")

    status = 0
    for out_dir in dirs:
        shown = str(out_dir.relative_to(REPO_ROOT)) if REPO_ROOT in out_dir.parents else str(out_dir)
        status |= report(shown, measure_dir(out_dir, tones, palette), args.quiet)
    if args.selftest:
        control = hue_control(dirs[-1])
        try:
            print(f"\ncontrol: the same frames with every hue turned 120 degrees ({control})")
            status |= report("hue-rotated control",
                             measure_dir(control, tones, palette), args.quiet)
        finally:
            shutil.rmtree(control, ignore_errors=True)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
