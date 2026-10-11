#!/usr/bin/env python3
"""Generate a stage background.

    python3 tools/pipeline/build_stage.py gijutsu_gym

Writes `data/stages/<id>/background.png`.

Two constraints come from the engine rather than from taste
---------------------------------------------------------
1. `GameContext::render()` draws the background at a FIXED 200x100 logical units
   centred on world (200, 200) -- the size is not read from any data file. That
   is 800x400 world pixels, so a background is authored at 800x400 and there is
   no point authoring larger: it would only be resampled.
2. That 800x400 region does not reach the bottom of the viewport at our camera
   setting, leaving a band. The band is painted dark on purpose so it reads as
   foreground floor rather than as a missing asset, and the project clear colour
   matches it. Fixing it properly means patching the background draw size, which
   is a separate change.

The Gijutsu Gym, from the lore: a training hall with a glass observation wall
where a class watches through the glass, ice-shard set dressing ("The Clouds of
Frozen Tears"), and a bright training floor.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parents[2]

WIDTH, HEIGHT = 800, 400

# Where the wall meets the floor, in image rows. This is not a free choice.
#
# The engine draws the background into a fixed 200x100 logical box at world
# (200,200) -- 800x400 world pixels -- so image row == world y. The match camera
# at (198,279), zoom 1.5, shows rows 135..423, and the fighters' feet land at
# world 402 (measured off a spawn capture; see SPAWN_Y for why the spawn height
# cannot move them). Putting the boundary at 360 leaves the floor reading as a
# receding surface under their feet, with the wall behind them, which is the
# composition a fighting game wants.
HORIZON = 360


def gijutsu_gym() -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), (16, 20, 26))
    draw = ImageDraw.Draw(image)

    # Back wall: a vertical gradient brightening toward the floor.
    for y in range(HORIZON):
        t = y / float(HORIZON)
        draw.line([(0, y), (WIDTH, y)],
                  fill=(int(20 + 26 * t), int(26 + 30 * t), int(34 + 34 * t)))

    # The glass observation wall: panels with a frame, and a faint highlight
    # running down each one so the glass reads as glass.
    panel_w, panel_h, top = 88, 200, 96
    for index, x in enumerate(range(18, WIDTH - 18, panel_w)):
        shade = 12 if index % 2 else 0
        draw.rectangle([x, top, x + panel_w - 8, top + panel_h],
                       fill=(46 + shade, 74 + shade, 88 + shade))
        draw.rectangle([x, top, x + panel_w - 8, top + panel_h],
                       outline=(96, 140, 156), width=2)
        draw.line([(x + 14, top + 6), (x + 14, top + panel_h - 6)],
                  fill=(74 + shade, 112 + shade, 130 + shade), width=3)

        # Silhouettes of the class watching through the glass -- the scene the
        # arena is named for. Deliberately indistinct.
        for watcher in range(2):
            wx = x + 26 + watcher * 32
            draw.ellipse([wx - 5, top + 74, wx + 5, top + 84], fill=(30, 44, 54))
            draw.rectangle([wx - 7, top + 84, wx + 7, top + 126], fill=(30, 44, 54))

    # Ice shards: "The Clouds of Frozen Tears" set dressing, standing against the
    # wall at both ends of the arena.
    def shard(x, height, width):
        draw.polygon([(x, HORIZON), (x + width // 2, HORIZON - height), (x + width, HORIZON)],
                     fill=(126, 186, 210))

    for x, h, w in [(24, 92, 26), (54, 62, 20), (700, 108, 30), (738, 74, 22), (762, 48, 18)]:
        shard(x, h, w)

    # Training floor: a tile grid receding to the horizon.
    draw.rectangle([0, HORIZON, WIDTH, HEIGHT], fill=(58, 62, 70))
    for row in range(HORIZON, HEIGHT, 18):
        draw.line([(0, row), (WIDTH, row)], fill=(48, 52, 60), width=1)
    for column in range(0, WIDTH, 46):
        draw.line([(column, HORIZON), (column, HEIGHT)], fill=(48, 52, 60), width=1)

    # The lit edge where the floor meets the wall -- the line the fighters stand
    # on. It has to be crisp: it is the only thing telling the eye where the
    # ground is.
    draw.line([(0, HORIZON), (WIDTH, HORIZON)], fill=(170, 226, 246), width=3)

    # Darken toward the bottom of the frame so the floor has depth. There is no
    # clear-colour band to blend into any more -- the camera change removed it --
    # so this is purely a vignette now rather than damage control.
    for y in range(HEIGHT - 44, HEIGHT):
        shade = int(58 - 30 * ((y - (HEIGHT - 44)) / 44.0))
        draw.line([(0, y), (WIDTH, y)], fill=(shade, shade + 4, shade + 10))

    return image


STAGES = {"gijutsu_gym": gijutsu_gym}


def main(argv) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2

    identifier = argv[1]
    if identifier not in STAGES:
        print(f"unknown stage '{identifier}'; known: {', '.join(STAGES)}", file=sys.stderr)
        return 2

    out_dir = REPO_ROOT / "data" / "stages" / identifier
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "background.png"

    STAGES[identifier]().save(out_path)
    print(f"  {identifier:16s} {WIDTH}x{HEIGHT} -> {out_path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
