"""Measure the world -> screen mapping from the engine's own debug overlay.

The hurtboxes are drawn by the engine at a known size in engine units, so their
width in pixels is the scale, and their position is the mapping. Both fighters
stand on their spawn points at t=0.1s, which are known: 30 and 70.

  python3 tools/measure_world.py <capture.png>
"""
import sys

from PIL import Image

path = sys.argv[1] if len(sys.argv) > 1 else "box_0010.png"
image = Image.open(path).convert("RGB")
width, height = image.size
pixels = image.load()


def is_blue(r, g, b):
    """The hurtbox outline: blue dominant, nothing else in the frame is."""
    return b > 120 and b > r + 60 and b > g + 60


columns = [x for x in range(width) if any(is_blue(*pixels[x, y]) for y in range(height))]
rows = [y for y in range(height) if any(is_blue(*pixels[x, y]) for x in range(width))]

if not columns:
    print("no hurtbox pixels found in %s" % path)
    raise SystemExit(1)

# The two hurtboxes are separated by the gap between the fighters, so split the
# columns into contiguous runs.
runs = []
for x in columns:
    if runs and x == runs[-1][1] + 1:
        runs[-1][1] = x
    else:
        runs.append([x, x])

print("image          : %dx%d" % (width, height))
print("hurtbox columns: %d run(s)" % len(runs))
spans = []
for start, end in runs:
    span = end - start + 1
    spans.append((start, end, span))
    print("  run x %4d..%-4d  width %3d px" % (start, end, span))

print("rows           : y %d..%d" % (min(rows), max(rows)))

# A hurtbox is 12 engine units wide. Take the widest run as the cleanest sample.
widest = max(spans, key=lambda s: s[2])[2]
print()
print("scale          : %.3f px per engine unit (12-unit hurtbox measured %d px)"
      % (widest / 12.0, widest))
