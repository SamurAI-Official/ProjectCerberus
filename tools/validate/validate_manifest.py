#!/usr/bin/env python3
"""Validate the roster and stage manifests, and the character YAML they point at.

    python3 tools/validate/validate_manifest.py

Three failures this catches that the running game does not:

  * **A res:// path that does not resolve.** GameState falls back to the stock
    fixture whenever a manifest path is empty, so a typo silently plays Ryu
    instead of the fighter that was picked. Nothing errors; you just lose.
  * **A duplicate id.** GameState addresses entries by index, so duplicates are
    invisible at runtime and still make the roster ambiguous to anything else
    that reads it.
  * **A character YAML referencing a sprite that is not there.** The engine
    loads frames lazily through ResourceLoader, so a missing PNG is a sprite
    that quietly does not appear rather than a load failure.

Exit code 0 when everything resolves, 1 otherwise, so this can gate a build.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

FIGHTER_MANIFEST = "data/fighters/manifest.json"
STAGE_MANIFEST = "data/stages/manifest.json"

# Every character needs a `start` state: Player::resetForRound() returns to it
# between rounds, and without it a round reset leaves the fighter mid-animation.
REQUIRED_ANIMATION = "start"

FRAME_PATH_RE = re.compile(r"^\s*path:\s*(\S+)\s*$", re.MULTILINE)


def fail(message: str) -> None:
    print(f"  FAIL  {message}")


def resolve(res_path: str) -> Path | None:
    """Turn a res:// path into a path on disk, or None if it is not res://."""
    if not res_path.startswith("res://"):
        return None
    return REPO_ROOT / res_path[len("res://") :]


def load_manifest(relative: str) -> list | None:
    path = REPO_ROOT / relative
    if not path.exists():
        fail(f"{relative} is missing")
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        fail(f"{relative} is not valid JSON: {error}")
        return None

    if not isinstance(data, list):
        fail(f"{relative} must be a JSON array, got {type(data).__name__}")
        return None

    if not data:
        fail(f"{relative} is an empty array -- the menu that reads it is a dead end")
        return None

    return data


def check_entries(relative: str, entries: list, required: list) -> int:
    """Returns the number of failures."""
    failures = 0
    seen_ids: dict = {}

    for index, entry in enumerate(entries):
        where = f"{relative}[{index}]"

        if not isinstance(entry, dict):
            fail(f"{where} is {type(entry).__name__}, expected an object")
            failures += 1
            continue

        for key in required:
            value = entry.get(key)
            if not isinstance(value, str) or not value:
                fail(f"{where} is missing a non-empty '{key}'")
                failures += 1

        entry_id = entry.get("id")
        if isinstance(entry_id, str) and entry_id:
            if entry_id in seen_ids:
                fail(f"{where} id '{entry_id}' duplicates entry {seen_ids[entry_id]}")
                failures += 1
            seen_ids[entry_id] = index

    return failures


def check_res_paths(relative: str, entries: list, keys: list) -> int:
    failures = 0

    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        for key in keys:
            value = entry.get(key)
            if not isinstance(value, str) or not value:
                continue

            resolved = resolve(value)
            if resolved is None:
                fail(f"{relative}[{index}].{key} is not a res:// path: {value}")
                failures += 1
            elif not resolved.is_file():
                fail(f"{relative}[{index}].{key} does not exist: {value}")
                failures += 1

    return failures


def check_character_yaml(relative: str, entries: list) -> int:
    """Checks that a fighter's YAML declares a start state and that every frame
    file it references is actually on disk."""
    failures = 0

    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue

        value = entry.get("yaml")
        resolved = resolve(value) if isinstance(value, str) else None
        if resolved is None or not resolved.is_file():
            continue  # already reported by check_res_paths

        text = resolved.read_text(encoding="utf-8", errors="replace")
        label = f"{relative}[{index}] ({value})"

        if not re.search(rf"^\s*-?\s*name:\s*{REQUIRED_ANIMATION}\s*$", text, re.MULTILINE):
            fail(f"{label} has no '{REQUIRED_ANIMATION}' animation")
            failures += 1

        # Frame paths are written relative to the project root, e.g.
        # "data/ryu/idle00.png" -- which is how ResourceLoader resolves them
        # (with a res:// fallback), so they are checked the same way.
        missing: list = []
        for frame in dict.fromkeys(FRAME_PATH_RE.findall(text)):
            if not (REPO_ROOT / frame).is_file():
                missing.append(frame)

        if missing:
            shown = ", ".join(missing[:5])
            more = f" (+{len(missing) - 5} more)" if len(missing) > 5 else ""
            fail(f"{label} references {len(missing)} missing frame file(s): {shown}{more}")
            failures += 1

    return failures


def main() -> int:
    print(f"validating manifests under {REPO_ROOT}")
    failures = 0

    fighters = load_manifest(FIGHTER_MANIFEST)
    if fighters is not None:
        failures += check_entries(FIGHTER_MANIFEST, fighters, ["id", "name", "yaml", "moves"])
        failures += check_res_paths(FIGHTER_MANIFEST, fighters, ["yaml", "moves"])
        failures += check_character_yaml(FIGHTER_MANIFEST, fighters)

    stages = load_manifest(STAGE_MANIFEST)
    if stages is not None:
        failures += check_entries(STAGE_MANIFEST, stages, ["id", "name", "background"])
        failures += check_res_paths(STAGE_MANIFEST, stages, ["background"])

    if failures == 0:
        print(f"  OK    {FIGHTER_MANIFEST} and {STAGE_MANIFEST} resolve")
        return 0

    print(f"  {failures} problem(s) found")
    return 1


if __name__ == "__main__":
    sys.exit(main())

