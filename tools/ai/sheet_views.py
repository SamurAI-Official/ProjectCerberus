#!/usr/bin/env python3
"""Extract the named views out of a fighter's reference sheet.

    python3 tools/ai/sheet_views.py tsu_ibano --detect           # propose boxes, print them
    python3 tools/ai/sheet_views.py tsu_ibano --qc build/ai/refs # draw them, numbered
    python3 tools/ai/sheet_views.py tsu_ibano --write            # freeze the boxes into the sheet
    python3 tools/ai/sheet_views.py tsu_ibano --extract          # write the masked views

Why this exists
---------------
A character sheet is not one picture, it is a page of them: several standing views, a row of
expression heads, pose vignettes, sometimes a VFX panel, all drawn over grid paper with an
annotation beside each one and a crest watermark in the middle of the page. Everything downstream
that wants the sheet as a *reference* -- pose conditioning, an identity adapter, per-state faces --
needs one view at a time, cropped, with the paper and the annotations gone.

The view boxes live in the design sheet, beside `reference.samples`, for the same reason the
palette's sample boxes do: "where is Tsu's front view" is then a measurement you can re-run rather
than a number somebody typed into a tool. `--detect` proposes boxes from the drawing itself,
`--write` records whichever boxes are in force, `--qc` draws them so a human can check the proposal
is the one they meant, and `--extract` is what the rest of the pipeline consumes.

What counts as content
----------------------
The paper is near-white and the grid drawn on it is light and grey, so both go away under one
predicate rather than a threshold on one channel: a pixel is background when it is *light* (its
darkest channel is above `PAPER_MIN`) **and** *unsaturated* (its channel spread is below
`GRID_SPREAD`). That keeps a pale skin tone and a white shirt, which a plain "bright means paper"
test would eat, and it drops the grid lines, which a "not white" test would keep.

Detected boxes are merged afterwards: in cel-style line art a figure is one connected region, but
an annotation under it ("slumping into a seat") is another, and a head can be separated from its
own body by the white collar between them. Two boxes whose horizontal overlap is wide and whose
vertical gap is small are therefore the same view.

Trimming a view
---------------
Detection groups what belongs together; a *box* is still a rectangle, and on these sheets a
generous one around a pose also catches the caption beside it ("avoiding trouble", "g sigh") and
the tail of somebody's label arrow. A view with `"trim": true` keeps only the content components at
least `TRIM_FLOOR` of the largest one -- a figure against its own caption -- so the boxes can hug
the drawing without handing a generator the words next to it. It is per view rather than global,
because whether an annotation lands inside the box is a fact about one box.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parents[2]
SHEET_DIR = REPO_ROOT / "design_sheets"

# Paper and grid, as one predicate. Both numbers are generous on purpose: the sheets are JPEGs, so
# the paper is a band rather than a value, and the grid's lines are darker than the paper they are
# drawn on. Measured on both sheets: every pixel this calls background reads as paper or grid by
# eye, and no pixel of either fighter does.
PAPER_MIN = 205
GRID_SPREAD = 26

# A region has to be bigger than this to be a view rather than JPEG noise or one letter of an
# annotation.
MIN_VIEW_PIXELS = 400

# Merging: two content boxes are one view when they overlap horizontally by at least this fraction
# of the narrower one and the vertical gap between them is at most this many rows. The gap is what
# joins a head to its shoulders across a white collar, and a label to the figure it names.
MERGE_OVERLAP = 0.35
MERGE_GAP = 26


def load_sheet(fighter_id: str) -> tuple[Path, dict]:
    path = SHEET_DIR / f"{fighter_id}.json"
    if not path.is_file():
        raise SystemExit(f"no design sheet for '{fighter_id}' at {path}")
    return path, json.loads(path.read_text(encoding="utf-8"))


def sheet_image(sheet: dict) -> tuple[np.ndarray, Path]:
    block = sheet.get("reference")
    if not block:
        raise SystemExit(
            f"design sheet '{sheet['id']}' has no 'reference' block, so there is no sheet to "
            "measure views on")
    path = REPO_ROOT / block["sheet"]
    if not path.is_file():
        raise SystemExit(f"reference sheet for '{sheet['id']}' is missing: {path}")
    return np.asarray(Image.open(path).convert("RGB")), path


def content_mask(sheet_px: np.ndarray) -> np.ndarray:
    """True where the sheet holds drawing rather than paper, grid or JPEG noise."""
    hi = sheet_px.max(axis=2).astype(int)
    lo = sheet_px.min(axis=2).astype(int)
    background = (lo > PAPER_MIN) & ((hi - lo) < GRID_SPREAD)
    return ~background


def _horizontal_overlap(a, b) -> float:
    """Overlap of two boxes along x, as a fraction of the narrower one."""
    inter = min(a[2], b[2]) - max(a[0], b[0])
    if inter <= 0:
        return 0.0
    return inter / float(min(a[2] - a[0], b[2] - b[0]))


def merge_boxes(boxes: list) -> list:
    """Fold together the boxes that are parts of one view, until nothing changes.

    This is where the judgement in this tool lives, so it is one pass of a simple rule rather than
    a parameter search: overlap horizontally enough, sit close enough vertically, belong together.
    """
    boxes = [list(box) for box in boxes]
    merged = True
    while merged:
        merged = False
        out: list = []
        for box in boxes:
            for other in out:
                gap = max(other[1], box[1]) - min(other[3], box[3])
                if _horizontal_overlap(other, box) >= MERGE_OVERLAP and gap <= MERGE_GAP:
                    other[0] = min(other[0], box[0])
                    other[1] = min(other[1], box[1])
                    other[2] = max(other[2], box[2])
                    other[3] = max(other[3], box[3])
                    merged = True
                    break
            else:
                out.append(box)
        boxes = out
    return boxes


def reading_order(boxes: list) -> list:
    """Rows top to bottom, each row left to right -- the order a person reads the sheet in."""
    rows: list = []
    for box in sorted(boxes, key=lambda b: (b[1], b[0])):
        for row in rows:
            band_top = min(item[1] for item in row)
            band_bottom = max(item[3] for item in row)
            if min(band_bottom, box[3]) - max(band_top, box[1]) > 0:
                row.append(box)
                break
        else:
            rows.append([box])
    ordered: list = []
    for row in rows:
        ordered.extend(sorted(row, key=lambda b: b[0]))
    return ordered


def detect_boxes(sheet_px: np.ndarray) -> list:
    """Candidate views, in reading order.

    Connected components would be the obvious way to write this by hand; scipy's labelling is used
    instead because it is the same measurement with none of the topology to get wrong -- the merge
    above is where the judgement is, and it should be the only place.
    """
    from scipy import ndimage

    mask = content_mask(sheet_px)
    labels, _count = ndimage.label(mask)
    found = []
    for index, window in enumerate(ndimage.find_objects(labels), start=1):
        if window is None:
            continue
        area = int((labels[window] == index).sum())
        if area < MIN_VIEW_PIXELS:
            continue
        found.append([window[1].start, window[0].start, window[1].stop, window[0].stop])
    return reading_order(merge_boxes(found))


# A view is the figure it shows plus whatever was drawn touching it -- the arrow head that points at
# the briefcase, the crest the bag overlaps, the paper grain. A generous box around a figure
# therefore also catches any *disconnected* drawing that happens to sit beside it, and on these two
# sheets that is the caption under a pose ("avoiding trouble") and the tail of the one beside it.
#
# `"trim": true` on a view keeps only the content components at least this fraction of the largest
# one, which is a figure against its own caption: a head or a hand the collar separates from the
# body is a large component and survives, a word of annotation is a small one and goes. It is opt-in
# per view because it is a judgement about one box, not a property of sheets in general.
TRIM_FLOOR = 0.20


def trim_mask(mask: np.ndarray) -> np.ndarray:
    """The content in a box, minus the small disconnected pieces of someone's annotation."""
    from scipy import ndimage

    labels, count = ndimage.label(mask, structure=np.ones((3, 3), dtype=int))
    if count <= 1:
        return mask
    sizes = np.asarray(ndimage.sum(mask, labels, index=np.arange(1, count + 1)))
    keep = np.flatnonzero(sizes >= sizes.max() * TRIM_FLOOR) + 1
    return np.isin(labels, keep)


def stored_views(sheet: dict) -> dict:
    return (sheet.get("reference") or {}).get("views") or {}


def view_names(sheet: dict) -> list:
    return sorted(stored_views(sheet).keys())


def qc_overlay(sheet_px: np.ndarray, boxes: list, labels: list, out_path: Path) -> None:
    """Draw the boxes, numbered and named, onto a copy of the sheet."""
    image = Image.fromarray(sheet_px).convert("RGB")
    draw = ImageDraw.Draw(image)
    for index, (box, label) in enumerate(zip(boxes, labels), start=1):
        draw.rectangle(box, outline=(255, 0, 0), width=2)
        draw.text((box[0] + 4, box[1] + 2), label or "#%d" % index, fill=(255, 0, 0))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path)


def extract_view(sheet_px: np.ndarray, box: list, trim: bool = False) -> Image.Image:
    """One view, cropped to its box, with the paper and the grid made transparent.

    The mask is the point of the extraction rather than a nicety: a reference image handed to a
    generator with a page of grid paper still in it is a reference for grid paper. `trim` goes one
    step further and drops the disconnected bits of annotation a generous box let in (see TRIM_FLOOR).
    """
    x0, y0, x1, y1 = (int(v) for v in box)
    cropped = sheet_px[y0:y1, x0:x1]
    mask = content_mask(cropped)
    if trim:
        mask = trim_mask(mask)
    rgba = np.dstack([cropped, (mask * 255).astype(np.uint8)])
    return Image.fromarray(rgba, mode="RGBA")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("fighter", help="design sheet id, e.g. tsu_ibano")
    parser.add_argument("--detect", action="store_true",
                        help="propose view boxes from the drawing and print them")
    parser.add_argument("--qc", metavar="DIR",
                        help="write <fighter>_views.png, with the boxes drawn on the sheet")
    parser.add_argument("--write", action="store_true",
                        help="record the detected boxes in the design sheet as reference.views")
    parser.add_argument("--extract", action="store_true",
                        help="write each stored view to design_sheets/out/<fighter>/<name>.png")
    parser.add_argument("--out", metavar="DIR",
                        help="where --extract writes (default design_sheets/out/<fighter>)")
    parser.add_argument("--check", action="store_true",
                        help="verify the stored views are inside the sheet and hold content")
    args = parser.parse_args(argv)

    if not any((args.detect, args.qc, args.write, args.extract, args.check)):
        parser.print_help()
        return 2

    path, sheet = load_sheet(args.fighter)
    sheet_px, sheet_path = sheet_image(sheet)
    height, width = sheet_px.shape[0], sheet_px.shape[1]
    mask = content_mask(sheet_px)
    stored = stored_views(sheet)

    if args.detect or args.qc or args.write:
        boxes = detect_boxes(sheet_px)
        if not boxes:
            raise SystemExit(
                f"no view detected on {sheet_path.name}: the background predicate may not fit this "
                "sheet (see PAPER_MIN/GRID_SPREAD)")
        if args.detect:
            print(f"{args.fighter}: {len(boxes)} candidate view(s) on {sheet_path.name} "
                  f"({width}x{height})")
            for index, box in enumerate(boxes, start=1):
                area = (box[2] - box[0]) * (box[3] - box[1])
                ink = int(mask[box[1]:box[3], box[0]:box[2]].sum())
                print(f"  #{index:<3d} [{box[0]:4d},{box[1]:4d},{box[2]:4d},{box[3]:4d}]  "
                      f"{box[2] - box[0]:4d}x{box[3] - box[1]:<4d}  ink {ink / area:5.1%}")
        if args.qc:
            labels = list(stored.keys()) if len(stored) == len(boxes) else [""] * len(boxes)
            out_path = Path(args.qc) / f"{args.fighter}_views.png"
            qc_overlay(sheet_px, boxes, labels, out_path)
            print(f"  qc: {out_path}")
        if args.write:
            sheet.setdefault("reference", {})["views"] = {
                "view_%02d" % index: {"box": list(box)}
                for index, box in enumerate(boxes, start=1)
            }
            path.write_text(json.dumps(sheet, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")
            print(f"  wrote {len(boxes)} box(es) into {path} -- rename them in the sheet so each "
                  "one says which view it is")

    if args.extract:
        if not stored:
            raise SystemExit(
                f"{path.name} has no reference.views. Run --detect, check the boxes with --qc, then "
                "--write: extracting unnamed boxes would write files nobody can address.")
        out_dir = Path(args.out) if args.out else (REPO_ROOT / "design_sheets" / "out" / args.fighter)
        out_dir.mkdir(parents=True, exist_ok=True)
        for name in view_names(sheet):
            image = extract_view(sheet_px, stored[name]["box"])
            target = out_dir / f"{name}.png"
            image.save(target)
            print(f"  {name:12s} {image.width:4d}x{image.height:<4d} -> {target}")

    if args.check:
        failures = 0
        if not stored:
            print(f"  note  {args.fighter}: no reference.views recorded yet")
        for name in view_names(sheet):
            box = [int(v) for v in stored[name]["box"]]
            if not (0 <= box[0] < box[2] <= width and 0 <= box[1] < box[3] <= height):
                print(f"  FAIL  {name}: box {box} is not inside the sheet ({width}x{height})")
                failures += 1
                continue
            ink = int(mask[box[1]:box[3], box[0]:box[2]].sum())
            if ink < MIN_VIEW_PIXELS:
                print(f"  FAIL  {name}: box {box} holds {ink} content pixel(s), under the "
                      f"{MIN_VIEW_PIXELS} floor")
                failures += 1
            else:
                print(f"  OK    {name}: {box[2] - box[0]}x{box[3] - box[1]}, "
                      f"{ink} content pixel(s)")
        if failures:
            print(f"  {failures} view(s) no longer measure what they claim")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())



