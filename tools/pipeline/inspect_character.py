#!/usr/bin/env python3
"""Report the frame geometry an openfight character YAML actually uses.

    python3 tools/pipeline/inspect_character.py data/ryu/ryu.yml

Written because the sprite spec was wrong. It said "64x128" and `data/notes`
padded everything to that; the shipped fixture does not do that. Attack frames
are much wider than locomotion frames, and the drawn box in the YAML differs per
animation. Since the engine scales the WHOLE texture into the declared box, an
art file whose canvas aspect does not match its declared box comes out squashed,
and nothing errors -- it just looks wrong.

So this reports, per animation: the real PNG size, the declared draw box, and the
non-black silhouette extent. The silhouette is what has to line up with the
hand-authored hitboxes.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]

FRAME_RE = re.compile(r"^\s*-?\s*path:\s*(\S+)\s*$")
NAME_RE = re.compile(r"^\s*-?\s*name:\s*(\S+)\s*$")


def parse(yaml_path: Path) -> list:
    """Returns [{anim, path, w, h}] for the first frame of each animation."""
    animations: list = []
    current_anim = None
    frame = None

    for line in yaml_path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()

        if stripped.startswith("- name:") and line.startswith(("  - ", "    - ")):
            current_anim = NAME_RE.match(stripped).group(1)
            continue

        if FRAME_RE.match(line):
            if frame and "w" in frame and "h" in frame:
                animations.append(frame)
            frame = {"anim": current_anim, "path": FRAME_RE.match(line).group(1)}
            continue

        if frame is not None and stripped.startswith("width:"):
            frame["w"] = stripped.split(":", 1)[1].strip()
        elif frame is not None and stripped.startswith("height:"):
            frame["h"] = stripped.split(":", 1)[1].strip()

    if frame and "w" in frame and "h" in frame:
        animations.append(frame)

    return animations


def silhouette(path: Path) -> tuple:
    image = Image.open(path).convert("RGB")
    width, height = image.size
    pixels = image.load()

    min_x, max_x, min_y, max_y = width, -1, height, -1
    for y in range(height):
        for x in range(width):
            r, g, b = pixels[x, y]
            if r > 8 or g > 8 or b > 8:
                min_x = min(min_x, x)
                max_x = max(max_x, x)
                min_y = min(min_y, y)
                max_y = max(max_y, y)

    if max_x < 0:
        return (0, 0, 0, 0, 0, 0)
    return (min_x, min_y, max_x - min_x + 1, max_y - min_y + 1, width, height)


def main(argv: list) -> int:
    target = Path(argv[1]) if len(argv) > 1 else REPO_ROOT / "data/ryu/ryu.yml"
    if not target.is_absolute():
        target = REPO_ROOT / target
    if not target.is_file():
        print(f"no such file: {target}", file=sys.stderr)
        return 2

    print(f"{target.relative_to(REPO_ROOT)}")
    print(f"{'animation':18s} {'source PNG':12s} {'draw box':10s} {'silhouette':22s} aspect")
    print("-" * 82)

    seen = set()
    for frame in parse(target):
        anim = frame["anim"]
        if anim in seen:
            continue
        seen.add(anim)

        path = REPO_ROOT / frame["path"]
        if not path.is_file():
            print(f"{anim:18s} MISSING {frame['path']}")
            continue

        sx, sy, sw, sh, iw, ih = silhouette(path)
        declared = float(frame["w"]) / float(frame["h"])
        actual = float(sw) / float(sh) if sh else 0.0
        flag = "" if abs(declared - actual) < 0.18 else "  <-- aspect mismatch"

        print(f"{anim:18s} {iw}x{ih:<8} {frame['w']+'x'+frame['h']:10s} "
              f"x[{sx},{sx+sw}] y[{sy},{sy+sh}] {sw}x{sh:<6} "
              f"declared {declared:.2f} vs drawn {actual:.2f}{flag}")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
