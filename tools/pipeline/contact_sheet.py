#!/usr/bin/env python3
"""Compose every frame of a fighter into one image, for looking at.

    python3 tools/pipeline/contact_sheet.py tsu_ibano [--scale 3]

Writes `build/contact_<id>.png`. Frames are laid out in animation order with one
blank column between states, because the fastest way to find a broken pose is to
see all of them at once -- and a generated frame set can be broken in ways no
single frame reveals (a limb that mirrors wrongly, a state whose poses do not
progress).

This is the handoff artefact too: it is what you show an artist when the
placeholder art is being replaced.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_fighter import STATE_SPEC  # noqa: E402

GUTTER = 6
MARGIN = 8


def main(argv) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2

    identifier = argv[1]
    scale = 3
    if "--scale" in argv:
        scale = int(argv[argv.index("--scale") + 1])

    frames_dir = REPO_ROOT / "data" / identifier
    if not frames_dir.is_dir():
        print(f"no frames at {frames_dir}", file=sys.stderr)
        return 2

    columns = []
    for state, count, _delay, _box, _continual, _pose in STATE_SPEC:
        columns.append([frames_dir / f"{state}{index:02d}.png" for index in range(count)])

    # Wrapped into rows rather than one long strip: 117 frames in a single row is
    # a 45000-pixel-wide image, which is the same as not having one.
    cells = []
    for column in columns:
        cells.extend(column)
        cells.append(None)  # blank gap between states

    per_row = 14
    rows = [cells[i:i + per_row] for i in range(0, len(cells), per_row)]

    present = [path for path in cells if path is not None and path.is_file()]
    cell_w = max(Image.open(path).size[0] for path in present) * scale
    cell_h = max(Image.open(path).size[1] for path in present) * scale

    total_w = MARGIN * 2 + per_row * (cell_w + GUTTER)
    total_h = MARGIN * 2 + len(rows) * (cell_h + GUTTER)

    sheet = Image.new("RGB", (total_w, total_h), (22, 22, 30))

    for row_index, row in enumerate(rows):
        x = MARGIN
        y = MARGIN + row_index * (cell_h + GUTTER)
        for path in row:
            if path is not None and path.is_file():
                frame = Image.open(path).convert("RGB").resize((cell_w, cell_h), Image.NEAREST)
                sheet.paste(frame, (x, y))
            x += cell_w + GUTTER

    out_dir = REPO_ROOT / "build"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"contact_{identifier}.png"
    sheet.save(out_path)

    print(f"{sum(len(c) for c in columns)} frames -> {out_path.relative_to(REPO_ROOT)} "
          f"({total_w}x{total_h}, {scale}x)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
