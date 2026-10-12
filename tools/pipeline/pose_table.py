#!/usr/bin/env python3
"""Freeze the skeleton every frame is drawn from, and the boxes derived from it.

    python3 tools/pipeline/pose_table.py --write
    python3 tools/pipeline/pose_table.py --check

`POSES` in build_fighter.py is a table of functions: `idle` breathes, a strike
sweeps, and `strike_box` finds the striking joint's furthest reach *by rendering
the pose*. That is the right way round -- the hitbox follows the drawing rather
than the drawing having to fit a number somebody typed -- but it does mean the
boxes are written down nowhere. They are whatever the current code computes, so a
one-line change to a pose moves a hitbox and changes no file at all.

That was survivable while the frames were drawn by the same function that
measured them. It stopped being survivable with the AI art path: the sampler is
conditioned on the same skeleton, so the same one-line change silently
invalidates every frame already baked from the old one, and nothing in the build
notices -- the boxes move to where the new skeleton's joints are while the
textures still show the figure standing where the old ones were.

So the geometry is measured and written down, once, per fighter:

  * every joint the skeleton has, for every frame of every state, in origin units:
    the two the strikes name (`hand_far` for the punches, `foot_far` for the
    kicks), and the knees and shoulders as well, because the sampler is
    conditioned on a drawing of all of them;
  * the derivation itself: the pose name, the declared box and canvas, the
    hurtbox, and for the eight strikes the active frame, the trigger and the
    offensive box.

`--check` measures the same thing again and diffs it, naming the state, frame and
joint that moved. It is the same contract as `sheet_views.py`'s frozen view boxes,
applied to the skeleton instead of the sheet: the art is only as current as the
table it was drawn from.

The table is per fighter, because `profile` proportions move the joints, and it
lives in `design_sheets/poses/pose_table.json` with a fingerprint of each
fighter's own contents, so a batch of frames can cite the skeleton it came from.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import build_fighter  # noqa: E402
import figure  # noqa: E402

SHEET_DIR = REPO_ROOT / "design_sheets"
# In a subdirectory, not beside the sheets. Three tools enumerate the sheets with
# `design_sheets/*.json` -- build_fighter, validate_boxes and ref_palette -- and each of them would
# otherwise read this file as a fighter with no palette; the first version of it in that directory
# broke `validate_boxes.py` with a KeyError on 'palette16'. `design_sheets/out/` holds the extracted
# sheet views for the same reason: subdirectories are not sheets.
TABLE_PATH = SHEET_DIR / "poses" / "pose_table.json"

# Every joint `figure.pose` returns, frozen. The art path is conditioned on a drawing of the whole
# skeleton, so a table that recorded only the limbs the hitboxes read would miss a pose change the
# sampler can see -- a knee, a shoulder -- and would keep reporting itself current while every frame
# it describes had gone stale. The four limb ends and the head come first because they are the ones
# the game itself reads: `hand_far` and `foot_far` are what STRIKES derives a box from, and the head
# is what gen_frames.py measures the reference composition against.
JOINTS = ("hand_far", "hand_near", "foot_far", "foot_near", "head",
          "pelvis", "chest", "neck",
          "shoulder_far", "shoulder_near", "elbow_far", "elbow_near",
          "hip_far", "hip_near", "knee_far", "knee_near")

# Joints are stored and compared to this many decimals. 0.01 units is a sixteenth
# of a pixel at 6 px per unit -- below anything the art or the engine can express --
# and rounding is what keeps the file's diff readable when a pose is re-tuned.
PLACES = 2


def canvas_for(box: str) -> list:
    """The declared box, in pixels, at the canvas resolution the build renders."""
    return [int(value * figure.PX_PER_UNIT) for value in build_fighter.BOXES[box]]


def _rounded(mapping: dict) -> dict:
    return {key: round(float(value), PLACES) for key, value in mapping.items()}


def table_for(sheet: dict) -> dict:
    """Every state's skeleton and every box derived from it, measured now."""
    profile = sheet.get("profile", {})
    states = {}
    for state, count, _delay, box, _continual, pose_name in build_fighter.STATE_SPEC:
        units = build_fighter.BOXES[box]
        builder = build_fighter.POSES.get(pose_name, build_fighter.POSES["idle"])

        joints = []
        for index in range(count):
            skeleton = figure.pose(**builder(index, count, profile))
            # A joint this table does not record is a pose change the check cannot see, so the
            # skeleton growing one is an error here rather than a silent gap.
            unknown = set(skeleton) - set(JOINTS)
            if unknown:
                raise SystemExit(
                    f"figure.pose returns joint(s) this table does not freeze: {sorted(unknown)}. "
                    f"Add them to JOINTS in {Path(__file__).name}, then re-run --write.")
            joints.append({joint: [round(float(v), PLACES) for v in skeleton[joint]]
                           for joint in JOINTS})

        entry = {
            "pose": pose_name,
            "box": box,
            "canvas": canvas_for(box),
            "hurtbox": _rounded(build_fighter.hurtbox_for(units)),
            "joints": joints,
        }
        # A strike's active frame and its offensive box both come off the pose, so
        # they belong in the table: they are the two numbers the game is tuned by and
        # the two that a moved joint silently changes.
        if state in build_fighter.STRIKES:
            index, trigger, sbox = build_fighter.strike_box(state, count, profile, units)
            entry["strike"] = {"trigger": trigger, "frame": index, "box": _rounded(sbox)}
        states[state] = entry
    return states


def fingerprint(states: dict) -> str:
    """A digest of one fighter's geometry, so a batch of frames can cite it."""
    blob = json.dumps(states, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def measure_all() -> dict:
    """The table, as the code computes it right now."""
    table = {}
    for path in sorted(SHEET_DIR.glob("*.json")):
        if path.name == TABLE_PATH.name:
            continue
        sheet = json.loads(path.read_text(encoding="utf-8"))
        sheet.setdefault("id", path.stem)
        states = table_for(sheet)
        table[sheet["id"]] = {"fingerprint": fingerprint(states), "states": states}
    return table


def diff(recorded: dict, measured: dict, label: str) -> list:
    """Everything that moved between a frozen fighter's states and the code's, named.

    Both arguments are the `states` dicts, not the per-fighter wrappers around them.
    """
    was_states = recorded
    problems = []
    for state in sorted(set(was_states) | set(measured)):
        if state not in was_states:
            problems.append(f"{label}/{state}: a state the table has never seen")
            continue
        if state not in measured:
            problems.append(f"{label}/{state}: in the table but no longer in STATE_SPEC")
            continue
        was, now = was_states[state], measured[state]
        for key in ("pose", "box", "canvas", "hurtbox", "strike"):
            if was.get(key) != now.get(key):
                problems.append(f"{label}/{state}.{key}: table {was.get(key)} -> now "
                                f"{now.get(key)}")
        was_joints = was.get("joints", [])
        if len(was_joints) != len(now["joints"]):
            problems.append(f"{label}/{state}: {len(was_joints)} frame(s) in the table, "
                            f"{len(now['joints'])} now")
        for index, (before, after) in enumerate(zip(was_joints, now["joints"])):
            for joint in JOINTS:
                if before.get(joint) != after.get(joint):
                    problems.append(f"{label}/{state}{index:02d} {joint}: table "
                                    f"{before.get(joint)} -> now {after.get(joint)}")
    return problems


def summarise(label: str, entry: dict, verbose: bool) -> None:
    """One fighter's table, as a line and (with --verbose) its strike derivations."""
    states = entry["states"]
    frames = sum(len(state["joints"]) for state in states.values())
    strikes = [state for state in sorted(states) if "strike" in states[state]]
    print(f"  OK    {label:16s} {len(states):2d} states, {frames:3d} frames, "
          f"{len(strikes)} strike(s), fingerprint {entry['fingerprint'][:16]}")
    if not verbose:
        return
    for state in strikes:
        strike = states[state]["strike"]
        box = strike["box"]
        print(f"          {state:14s} {strike['trigger']:12s} frame {strike['frame']:2d}  "
              f"x_pos {box['x_pos']:6.1f} y_pos {box['y_pos']:5.1f}  "
              f"{box['width']:.1f}x{box['height']:.1f}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--write", action="store_true",
                        help=f"measure every pose and write {TABLE_PATH.name}")
    parser.add_argument("--check", action="store_true",
                        help="measure again and diff against the written table")
    parser.add_argument("--quiet", action="store_true", help="one line per fighter")
    parser.add_argument("--verbose", action="store_true",
                        help="also print where each strike's box comes from")
    args = parser.parse_args(argv)

    table = measure_all()
    if not table:
        raise SystemExit(f"no design sheets in {SHEET_DIR}")

    if args.write:
        TABLE_PATH.parent.mkdir(parents=True, exist_ok=True)
        TABLE_PATH.write_text(json.dumps(table, indent=1, sort_keys=True) + "\n",
                              encoding="utf-8")
        print(f"wrote {TABLE_PATH.relative_to(REPO_ROOT)} "
              f"({len(table)} fighter(s))")
        for label in sorted(table):
            summarise(label, table[label], args.verbose)
        return 0

    if args.check:
        if not TABLE_PATH.is_file():
            raise SystemExit(f"no pose table at {TABLE_PATH.relative_to(REPO_ROOT)}: "
                             "run --write once, look at the diff, and commit it")
        frozen = json.loads(TABLE_PATH.read_text(encoding="utf-8"))
        problems = []
        for label in sorted(set(frozen) | set(table)):
            if label not in frozen:
                problems.append(f"{label}: a fighter the table has never seen")
            elif label not in table:
                problems.append(f"{label}: in the table but has no design sheet")
            else:
                problems += diff(frozen[label].get("states", {}),
                                 table[label]["states"], label)
        if problems:
            print(f"the pose table no longer describes the code "
                  f"({len(problems)} difference(s)):")
            for problem in problems[:40]:
                print(f"  {problem}")
            if len(problems) > 40:
                print(f"  ... and {len(problems) - 40} more")
            print("\nEach of those is a frame whose art may have been drawn from a different\n"
                  "skeleton than the table -- and a hitbox that may not be where the drawing\n"
                  "puts the limb any more. Re-run --write, then re-bake the affected frames.")
            return 1
        print(f"pose table is current ({TABLE_PATH.relative_to(REPO_ROOT)})")
        for label in sorted(table):
            summarise(label, table[label], args.verbose)
        return 0

    print("what the code computes now (nothing written):")
    for label in sorted(table):
        summarise(label, table[label], args.verbose)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
