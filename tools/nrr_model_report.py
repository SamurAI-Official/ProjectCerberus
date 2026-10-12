#!/usr/bin/env python3
"""Which published NRR model, if any, belongs in this game?

    python3 tools/nrr_model_report.py [--out build/nrr]

The render path's NRR option is on record as declining every frame, and the reason
recorded used to be that the published model takes exactly 512x512 while our canvas
is 768x432. That was wrong about the model. This measures the three things that are
true instead, and each one changes what should be done about it:

1. **What the graph declares.** `tools/verify/nrr_probe.tscn` asks the *runtime*
   which sizes it accepts; this asks the *graph*, through ONNX Runtime, which is the
   only way to tell "the artifact refuses" from "our binding cannot drive it". Both
   published models are spatially dynamic -- `color [1,3,H,W]` in, 2x H/W out, at any
   size -- and their two conditioning inputs are full-resolution *planes*, not the
   scalars the model card's wording suggests: `scale` is `[1,1,H,W]` and `jitter` is
   `[1,2,H,W]`, and a rank-1 token is a hard error.

2. **Which tier each model serves.** The game draws at a fixed canvas and enlarges to
   whatever the window is, so the ratio is a property of the *window*, not a constant:
   2.5x at 1920x1080, 2x at 1536x864, 5x at 3840x2160. `ratio25/
   upscale_25x_procedural_depth.onnx` is the published model whose head matches 1080p
   from this canvas, and it declares a `depth` plane that the Godot path has no source
   for -- the addon calls `render_frame(color)`, and Godot exposes no portable depth
   buffer.

3. **Whether either model beats the filters the game already has, on this art.** The
   published models are trained on frames captured from 3D Godot scenes
   (`models/training-data/godot-v6-warp`), which have gradients, texture and geometry
   to reconstruct. This game's frames are flat 16-colour pixel art at native
   resolution, where there is nothing to reconstruct and a model that invents detail
   is penalised for it. The test below is our own art: the stage with both fighters on
   it at the game's own 6 px/unit, a downscaled copy of it as the model's input, and
   the frame itself as ground truth. Nearest, bilinear and bicubic are scored on the
   same input, so the arms differ only in how they enlarge.

Two framings are measured because the composition is a stand-in for a screenshot: the
sprites at their texture's own scale (a 30x64-unit crop at 6 px/unit), and at half
that, with the fighters higher in the frame. The conclusion has to hold in both
before it is worth acting on.

Measured on macOS arm64, CPU provider, ONNX Runtime 1.30.0, 2026-10-11: the 2x model
loses to the best classical filter by 3.8-4.6 dB at both framings (24.7-26.2 dB
against 28.4-30.8), including the 128->256 tier it was trained at, and its error map
is dense inside *flat* regions rather than at edges -- it invents texture where the
art has none. The 2.5x model lands level with bicubic at the canvas tier (26.86
against 26.84 dB, which is not a win by any reading) and loses to it at 640x360, and
its depth plane is worth about 0.3 dB either way: zeros, a flat plane and the sprite
mask all land within a hair of each other, because a flat scene has no depth to
condition on. So the answer to the question in the title is: neither model, and the
render path's honest fallback is the right default. Re-measure with this script before
arguing with any of it -- the numbers above are what it printed, and a card is not.
"""


from __future__ import annotations

import argparse
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]

RELEASED = REPO_ROOT / "addons" / "nrr" / "models" / "upscale_msreal_scale.onnx"
RATIO25_URL = ("https://huggingface.co/SamurAI-Official/NRR/resolve/main/"
               "ratio25/upscale_25x_procedural_depth.onnx")
RATIO25_NAME = "upscale_25x_procedural_depth.onnx"

# Resolved in main() from --models: the 2.5x model is downloaded, not vendored, so it
# lives under the output directory rather than beside the released one.
RATIO25_PATH = Path(RATIO25_NAME)

# The canvas the game draws at, and the world-to-screen scale the art pipeline
# registers frames at (figure.PX_PER_UNIT): a 40-unit frame is 240 px tall on this
# canvas, and each fighter's texture is a 30x64-unit crop of it -- 180x384 px.
CANVAS = (768, 432)
PX_PER_UNIT = 6.0

# The sprite frames the game ships, and where the ground line sits on the canvas.
# 90% is the drawing camera's GROUND_FRACTION; frames are registered onto that line,
# so a composed frame puts the feet there.
SPRITES = (("tsu_ibano", 300), ("fei_young", 470))
GROUND_FRACTION = 0.90

# The enlargements the game can be presented at, as window size / canvas. The window
# is whatever the desktop gives, so a model has to match a tier, not a size.
TIERS = ((2.0, "1536x864"), (2.5, "1920x1080"), (3.333, "2560x1440"), (5.0, "3840x2160"))

# What a caller with no depth buffer can hand the 2.5x model: zeros, which is what
# the addon's render_frame(color) does; a flat plane; and the sprite mask, which is
# the only source of depth a 2D scene has.
DEPTH_ARMS = ("zeros", "flat", "mask")

# What counts as beating a filter rather than matching it, in dB. A tenth of a dB is
# a fraction of one 8-bit level on one pixel in ten; calling that a win is the kind of
# claim this project exists to avoid, so an arm inside the margin is reported as level
# with the filter it matched.
MARGIN_DB = 0.25

# The tier token the graph's `scale` plane carries: log2(input width / 128), 0.0 for
# the 128->256 grid and 1.0 for the 256->512 grid. An input wider than the 256 the
# model was trained at is extrapolation, which is worth printing next to a score
# rather than assuming away.
TOKEN_UNIT = 128.0


def session(path: Path):
    """An ONNX Runtime session on the CPU, which is where a machine with no CUDA
    provider lands anyway and where NRR's own recorded Godot run landed."""
    import onnxruntime as ort
    return ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])


def fetch_ratio25(models_dir: Path) -> Path:
    """The 2.5x model, downloaded once. It is 369 KB, the size the Hub lists.

    Through curl rather than urllib, the same way `tools/build_nrr_macos.sh` fetches
    the released model: macOS's bundled Python has no CA bundle of its own, so urllib
    fails the handshake on a machine where every other tool in the repo succeeds.
    """
    path = models_dir / RATIO25_NAME
    if path.is_file():
        return path
    models_dir.mkdir(parents=True, exist_ok=True)
    print(f"  fetching {RATIO25_NAME} from huggingface.co/SamurAI-Official/NRR")
    done = subprocess.run(["curl", "-sSL", "-o", str(path), RATIO25_URL])
    if done.returncode != 0 or not path.is_file() or path.stat().st_size == 0:
        path.unlink(missing_ok=True)
        raise SystemExit(f"could not fetch {RATIO25_URL} (curl exit {done.returncode})")
    return path


def evidence(panels, path: Path, zoom: int = 2) -> None:
    """Lay arms side by side, with each model arm's error next to it magnified."""
    width, height = panels[0][1].size
    sheet = Image.new("RGB", (width * len(panels) + 6 * (len(panels) + 1),
                              height * zoom + 6), (18, 18, 22))
    for index, (_label, image) in enumerate(panels):
        sheet.paste(image.resize((width * zoom, height * zoom), Image.NEAREST),
                    (6 + index * (width * zoom + 6), 3))
    sheet.save(path)


def error_map(got: Image.Image, want: Image.Image, boost: int = 6) -> Image.Image:
    left = np.asarray(got.convert("RGB"), dtype=np.int16)
    right = np.asarray(want.convert("RGB"), dtype=np.int16)
    return Image.fromarray(np.clip(np.abs(left - right) * boost, 0, 255).astype(np.uint8),
                           "RGB")


def arms_for(frame, mask, ratio, out_w, model):
    """Every arm's enlargement of the same low-resolution frame, on one grid.

    The model decides the output size -- 2.5x of 307 px is 767, not 768 -- and every
    other arm is resized to that same size, so the comparison is over identical
    pixels and the target is cropped to match.
    """
    out_h = int(round(out_w * CANVAS[1] / CANVAS[0]))
    target = frame.resize((out_w, out_h), Image.BOX)
    in_w, in_h = int(round(out_w / ratio)), int(round(out_h / ratio))
    low = target.resize((in_w, in_h), Image.BOX)

    arms = {}
    if model == "released":
        got = run_released(model_session("released"), nchw(low),
                           math.log2(in_w / TOKEN_UNIT))
    else:
        depth_plane = np.asarray(mask.resize((in_w, in_h), Image.BOX),
                                 dtype=np.float32)[None, None] / 255.0
        got = run_ratio25(model_session("ratio25"), nchw(low), depth_plane)
        for arm in DEPTH_ARMS:
            if arm == "zeros":
                plane = np.zeros_like(depth_plane)
            elif arm == "flat":
                plane = np.full_like(depth_plane, 0.5)
            else:
                plane = depth_plane
            arms[f"nrr {ratio}x depth={arm}"] = run_ratio25(
                model_session("ratio25"), nchw(low), plane)

    scored = (got.width, got.height)
    if model == "released":
        arms["nrr 2x"] = got
    for label, resample in (("nearest", Image.NEAREST), ("bilinear", Image.BILINEAR),
                            ("bicubic", Image.BICUBIC)):
        arms[label] = low.resize(scored, resample)
    return arms, target.crop((0, 0, scored[0], scored[1])), (in_w, in_h)


_SESSIONS: dict = {}


def model_session(which: str):
    """One ONNX Runtime session per model, kept for the run: loading is the only slow
    part, and every arm below runs the same graph on the same frame."""
    if which not in _SESSIONS:
        _SESSIONS[which] = session(RELEASED if which == "released" else RATIO25_PATH)
    return _SESSIONS[which]


def declared(sess) -> None:
    """The graph's own contract, read off the artifact rather than a card."""
    for item in sess.get_inputs():
        print(f"    in   {item.name:6s} {item.type:14s} {item.shape}")
    for item in sess.get_outputs():
        print(f"    out  {item.name:6s} {item.type:14s} {item.shape}")


def game_frame(framing: float):
    """A stand-in for a screenshot: the stage with both fighters on the ground line.

    `framing` 1.0 draws each texture at its own scale -- a 30x64-unit crop at 6
    px/unit, so the figure fills the canvas -- and anything smaller draws it further
    from the camera, with the fighters higher in the frame. The lowest opaque row of
    a texture is its feet; that row goes on the ground line.
    """
    background = REPO_ROOT / "data" / "stages" / "gijutsu_gym" / "background.png"
    stage = Image.open(background).convert("RGB")
    stage = stage.resize(CANVAS, Image.NEAREST) if stage.size != CANVAS else stage
    frame = stage.copy()
    mask = Image.new("L", CANVAS, 0)
    ground = CANVAS[1] * GROUND_FRACTION
    for fighter, x in SPRITES:
        sprite = Image.open(REPO_ROOT / "data" / fighter / "idle00.png").convert("RGBA")
        if framing != 1.0:
            size = (max(1, int(sprite.width * framing)),
                    max(1, int(sprite.height * framing)))
            sprite = sprite.resize(size, Image.BOX)
        rows = np.nonzero(np.asarray(sprite.getchannel("A")).max(axis=1))[0]
        top = int(round(ground - (rows.max() + 1))) if len(rows) else 0
        frame.paste(sprite, (x, top), sprite)
        mask.paste(sprite.getchannel("A"), (x, top), sprite)
    return frame, mask


def nchw(image: Image.Image) -> np.ndarray:
    return np.asarray(image.convert("RGB"), dtype=np.float32).transpose(
        2, 0, 1)[None] / 255.0


def image_of(batch: np.ndarray) -> Image.Image:
    planes = np.clip(batch[0].transpose(1, 2, 0), 0.0, 1.0)
    return Image.fromarray((planes * 255.0 + 0.5).astype(np.uint8), "RGB")


def run_released(sess, low: np.ndarray, token: float) -> Image.Image:
    """The 2x model: `color`, plus the two planes it declares."""
    h, w = low.shape[2], low.shape[3]
    batch = sess.run(None, {
        "color": low,
        "jitter": np.zeros((1, 2, h, w), np.float32),
        "scale": np.full((1, 1, h, w), token, np.float32),
    })[0]
    return image_of(batch)


def run_ratio25(sess, low: np.ndarray, depth: np.ndarray) -> Image.Image:
    return image_of(sess.run(None, {"color": low, "depth": depth})[0])


def score(got: Image.Image, want: Image.Image) -> tuple[float, float]:
    a = np.asarray(got.convert("RGB"), dtype=np.float64)
    b = np.asarray(want.convert("RGB"), dtype=np.float64)
    mse = float(((a - b) ** 2).mean())
    psnr = 99.0 if mse == 0.0 else 10.0 * math.log10((255.0 ** 2) / mse)
    return psnr, float(np.abs(a - b).mean())


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default="build/nrr",
                        help="where the downloaded model and the evidence sheets go")
    parser.add_argument("--models", default=None,
                        help="where the 2.5x model is kept (default: <out>/models)")
    parser.add_argument("--quiet", action="store_true",
                        help="the verdict, without the measurements behind it")
    args = parser.parse_args(argv)

    def resolve(value):
        path = Path(value)
        return path if path.is_absolute() else REPO_ROOT / path

    global RATIO25_PATH
    out_dir = resolve(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    RATIO25_PATH = fetch_ratio25(
        resolve(args.models) if args.models else out_dir / "models")

    if not RELEASED.is_file():
        raise SystemExit(f"the released model is not installed at {RELEASED} -- "
                         f"tools/build_nrr_macos.sh fetches it")

    if not args.quiet:
        print("=== what the two published graphs declare ===")
        for label, path in (("released", RELEASED), ("ratio25", RATIO25_PATH)):
            try:
                shown = path.relative_to(REPO_ROOT)
            except ValueError:
                shown = path
            print(f"  {label:9s} {shown}  ({path.stat().st_size} bytes)")
            declared(model_session(label))

    def say(*parts):
        """Everything except the verdict is measurement, and --quiet drops it."""
        if not args.quiet:
            print(*parts)

    say("\n=== the tier each one serves, from this canvas ===")
    say(f"  the game draws at {CANVAS[0]}x{CANVAS[1]} at {PX_PER_UNIT:g} px/unit, so the "
        f"ratio a window needs is that window over {CANVAS[0]}")
    for ratio, window in TIERS:
        serves = {2.0: "the released 2x model",
                  2.5: "ratio25 (needs a depth plane)"}.get(ratio, "no published model")
        say(f"    {window:>9s}  {ratio:>5.2f}x  ->  "
            f"{int(round(CANVAS[0] * ratio))}x{int(round(CANVAS[1] * ratio)):<5d}  {serves}")

    blank = np.zeros((1, 3, CANVAS[1], CANVAS[0]), np.float32)
    token = math.log2(CANVAS[0] / TOKEN_UNIT)
    got = run_released(model_session("released"), blank, token)
    say(f"\n  run at the canvas: released 2x -> {got.width}x{got.height}  (scale token "
        f"{token:.2f}; trained at 0.00 and 1.00, so this one is extrapolated)")
    got = run_ratio25(model_session("ratio25"), blank,
                      np.zeros((1, 1, CANVAS[1], CANVAS[0]), np.float32))
    say(f"  run at the canvas: ratio25 2.5x -> {got.width}x{got.height}  (1080p, which is "
        f"the window this canvas is normally presented in)")
    say("\n=== against our own art: this frame, downscaled, brought back up ===")
    wins, levels, losses = [], [], []
    for framing, label in ((1.0, "sprites at their own scale"),
                           (0.5, "sprites at half scale, fighters higher in the frame")):
        frame, mask = game_frame(framing)
        say(f"\n  {label}")
        for model, ratio, widths in (("released", 2.0, (256, 768)),
                                     ("ratio25", 2.5, (640, 768))):
            for out_w in widths:
                arms, target, low = arms_for(frame, mask, ratio, out_w, model)
                trained = (ratio == 2.0 and out_w == 256)
                say(f"    {ratio}x  {low[0]}x{low[1]} -> {target.width}x{target.height}"
                    f"   token {math.log2(low[0] / TOKEN_UNIT):+.2f} "
                    f"({'the tier it was trained at' if trained else 'extrapolated'})")
                classical = {arm: score(image, target) for arm, image in arms.items()
                             if arm in ("nearest", "bilinear", "bicubic")}
                best_name = max(classical, key=lambda arm: classical[arm][0])
                best = classical[best_name]
                for arm, image in arms.items():
                    psnr, l1 = score(image, target)
                    note = ""
                    if arm not in classical:
                        where = (model, ratio, low[0], framing)
                        if psnr > best[0] + MARGIN_DB:
                            note = "  wins"
                            wins.append(where)
                        elif psnr > best[0] - MARGIN_DB:
                            note = "  level"
                            levels.append(where)
                        else:
                            note = "  loses"
                            losses.append(where)
                    say(f"      {arm:22s} PSNR {psnr:6.2f} dB   L1 {l1:6.2f}{note}")
                say(f"      {'best classical: ' + best_name:22s} PSNR {best[0]:6.2f} dB"
                    f"   L1 {best[1]:6.2f}")
                if framing == 1.0 and out_w == CANVAS[0]:
                    arm = "nrr 2x" if model == "released" else "nrr 2.5x depth=mask"
                    clip = (200, 0, 560, 360)
                    truth = target.crop(clip)
                    panels = [("bicubic", arms["bicubic"].crop(clip)),
                              (arm, arms[arm].crop(clip))]
                    panels.append(("error", error_map(panels[1][1], truth)))
                    sheet = out_dir / f"nrr_canvas_{model}.png"
                    evidence(panels, sheet)
                    say(f"      wrote {sheet.relative_to(REPO_ROOT)}  (bicubic | {arm} | "
                        f"{arm} error x6, both against the true frame)")

    print("\n=== verdict ===")
    total = len(wins) + len(levels) + len(losses)
    if wins:
        print(f"  {len(wins)} of {total} model arms beat the best classical filter by more "
              f"than {MARGIN_DB} dB: "
              f"{sorted({f'{row[0]} at {row[1]}x from {row[2]} px' for row in wins})}")
        return 0
    detail = (f", {len(levels)} within {MARGIN_DB} dB of it" if levels else "")
    print(f"  none of the {total} model arms beats the best classical filter by more than "
          f"{MARGIN_DB} dB on\n  this art, at any tier or framing ({len(losses)} lose"
          f"{detail}). Both published models are\n  trained on 3D-rendered Godot captures; "
          f"this game is flat 16-colour pixel art already at\n  native resolution, so there "
          f"is nothing for a network to reconstruct and inventing detail\n  scores worse than "
          f"not doing it -- the 2x model's error map is dense inside flat regions,\n  which is "
          f"the picture that claim describes. Neither model is worth installing, and the\n  "
          f"render path's honest fallback is the right default.")
    return 1


if __name__ == "__main__":
    sys.exit(main())


