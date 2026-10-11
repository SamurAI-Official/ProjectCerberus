#!/usr/bin/env python3
"""Generate raw fighter frames with ComfyUI, from our own drawings of the poses.

    python3 tools/ai/gen_frames.py tsu_ibano --state idle --out build/ai/tsu_ibano
    python3 tools/ai/gen_frames.py tsu_ibano --state idle --mode controlnet

Two modes, and the measurement that picked between them
------------------------------------------------------
`--mode controlnet` is SDXL plus an OpenPose ControlNet conditioned on the
skeleton, and it holds the pose best -- but every frame is an independent sample,
so it cannot hold anything else. Six idle frames from one prompt came back with
six different backgrounds (white through near-black, from a prompt asking for
pure white), six different outfits, and two frames with nothing usable in them at
all. A sprite sheet cannot be built from that: the character has to be the same
character.

`--mode img2img` is SD1.5 repainting `figure.render()`'s drawing of the same pose.
The pose is looser -- at denoise 0.7 the sampler relaxes an extended arm -- but the
backdrop, the palette and the framing come from the init image, so they are the
same in every frame by construction. Across six idle frames the crown, the feet
and the horizontal extent agreed to within 0.1 engine units. It also needs 2.0 GB
of weights instead of 8.9, which on this machine is the difference between a run
that finishes and one that does not.

Both modes write the same `manifest.json`, recording everything needed to
reproduce a frame: mode, checkpoint, control net or denoise, prompt, seed,
sampler settings and the hash of the conditioning image. At ~117 frames per
fighter you will regenerate often, and a frame you cannot regenerate is a frame
you cannot fix.

Why we write the control image rather than detect one
----------------------------------------------------
`taldor_sdxl_controlnet.json` runs `Openpose_Detector_Preprocessor` over a
rendered picture and conditions on what the detector found. Here the conditioning
image is written by `openpose_render.py` straight from `figure.pose()`, so:

  * the pose is the pose the engine will resolve hitboxes against, not a
    detector's opinion about a drawing;
  * it is reproducible from a state name and a frame index;
  * there is no detector pass, and no chance of it failing on a pose that is
    unusual (a grounded fighter, an arm crossing the body) and silently
    conditioning on nothing.

Everything downstream still has to earn its place: a raw render is 512x512 and
tens of thousands of colours, and the game wants 180x384 in sixteen. That is
`to_sprite.py`'s job, not this one's.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "ai"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import build_fighter  # noqa: E402
import figure  # noqa: E402
import openpose_render  # noqa: E402
from comfy_client import ComfyClient, ComfyError  # noqa: E402
from PIL import Image  # noqa: E402

SHEET_DIR = REPO_ROOT / "design_sheets"

# Both models are already on this machine (see ~/ComfyUI/models). Pinned by name
# rather than discovered: a roster that changes style because a *different*
# checkpoint happened to be listed first is a roster that cannot be rebuilt.
CHECKPOINT = "sd_xl_base_1.0.safetensors"
CONTROL_NET = "xinsir-openpose-sdxl-1.0.safetensors"

# The img2img mode's checkpoint: SD1.5, 2.0 GB against SDXL's 6.5, and it needs no
# ControlNet at all, so the pair is 2.0 GB instead of 8.9. That is the difference
# between a run this machine finishes and one it does not.
CHECKPOINT_IMG2IMG = "DreamShaper_8_pruned.safetensors"

# What the puppet init is composited on, and therefore the backdrop every img2img
# frame inherits. A known flat colour is worth more than a pleasant one: to_sprite
# finds the backdrop by flood filling from the border, and txt2img could not be
# talked into a consistent background at all -- six idle frames came back as six
# different colours, white to near-black, from one prompt asking for pure white.
BACKDROP = (196, 208, 214)

# How much of the init the sampler may repaint. This is the whole trade-off. Low
# holds the pose and drifts on identity; high holds identity and lets the pose go.
# Measured over six idle frames: 0.7 held identity, framing and palette together
# but relaxed the extended arm; 0.5 kept the arm and flipped hair colour between
# frames. 0.7 is the default because a consistent character is the harder half.
DENOISE = 0.7

# Shared across every fighter so the roster reads as one game rather than a pile
# of commissions. "side view facing right" is the load-bearing phrase: the
# skeleton is a side view and a 3/4 or front render cannot be posed onto it.
STYLE = ("2D fighting game character sprite, full body, side view facing right, "
         "flat cel shading, bold clean black outlines, limited flat colour palette, "
         "crisp silhouette, clean pure white background, no text, no watermark")

NEGATIVE = ("3/4 view, front view, multiple characters, cropped, cut off, "
            "extra limbs, extra arms, extra legs, deformed hands, mutated hands, "
            "blurry, soft gradient, photorealistic, 3d render, text, watermark, "
            "signature, background scenery, ground shadow, border, frame")

# Render size, in pixels per side.
#
# 512 rather than 1024, and not as a compromise. `to_sprite.py` scales whatever
# comes out of here into a 240-pixel square window at game scale, because 240 is
# the size the game's 6 px/unit actually draws (PX_PER_UNIT * FRAME_UNITS, and
# that product is independent of the render size -- see to_sprite). Rendering at
# 1024 therefore throws away three quarters of the pixels, and their time and
# memory, before anything looks at them. 512 still resolves the 240 window with
# headroom to spare, and on a 16 GB machine the difference between the two is the
# difference between a run that finishes and one that swaps the disk full.
DEFAULT_SIZE = 512

# Headroom a run is required to have before it will start, in bytes.
#
# This is not a nicety. The checkpoint is 6.5 GB and the ControlNet 2.4 GB, and
# on a machine where those do not fit in RAM macOS swaps -- and swap is a file on
# the boot volume. The failure is not an exception; it is the disk silently
# filling twenty minutes later while the sampler is still on step four. On the
# 16 GB machine this was written on, with ~3.7 GB free, one 1024x1024 frame grew
# fifteen 1 GB swapfiles and took the volume to 100% before it was killed. A
# preflight check is the difference between a clear error and an afternoon.
MIN_FREE_BYTES = 12 * 1024 ** 3


def preflight(size=DEFAULT_SIZE, mode="controlnet"):
    """Refuse to start a run this machine cannot finish."""
    # The weights are the same either way, and they are the bulk of it; the
    # activations are what the render size controls, and they go as the square.
    needed = MIN_FREE_BYTES if size > 512 else MIN_FREE_BYTES // 2
    if mode == "img2img":
        # 2.0 GB of SD1.5 rather than 8.9 GB of SDXL plus ControlNet. The floor is
        # those weights and enough room for the swap they still provoke.
        needed //= 4
    free = shutil.disk_usage(REPO_ROOT).free
    if free >= needed:
        return

    raise SystemExit(
        f"only {free / 1024 ** 3:.1f} GB free; a {size}px SDXL run wants "
        f"{needed / 1024 ** 3:.0f} GB of headroom.\n"
        "The checkpoints alone are ~8.9 GB. Where they do not fit in RAM the "
        "overflow becomes swapfiles on the boot volume, so a run that is short of\n"
        "disk does not fail fast -- it fills the disk while you are waiting for "
        "step four.\n"
        "Options: free space, generate at a smaller --size, or swap CHECKPOINT for "
        "a smaller model (note CONTROL_NET must then match its architecture).")


def build_workflow(pose_image, positive, seed, size=1024, steps=20, cfg=7.0,
                   strength=0.9, prefix="cerberus"):
    """The API-format graph: SDXL, our control image, one sampler.

    `ControlNetApplyAdvanced` consumes and returns *both* conditionings, so
    KSampler takes its positive from output 0 and its negative from output 1.
    Wiring 0/0 here would apply the negative prompt as the positive one, which
    fails as "the character ignores the prompt" rather than as an error.
    """
    return {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": CHECKPOINT}},
        "2": {"class_type": "ControlNetLoader",
              "inputs": {"control_net_name": CONTROL_NET}},
        "3": {"class_type": "CLIPTextEncode",
              "inputs": {"clip": ["1", 1], "text": positive}},
        "4": {"class_type": "CLIPTextEncode",
              "inputs": {"clip": ["1", 1], "text": NEGATIVE}},
        "5": {"class_type": "LoadImage", "inputs": {"image": pose_image}},
        "6": {"class_type": "ControlNetApplyAdvanced",
              "inputs": {"positive": ["3", 0], "negative": ["4", 0],
                         "control_net": ["2", 0], "image": ["5", 0],
                         "strength": strength, "start_percent": 0.0,
                         "end_percent": 1.0}},
        "7": {"class_type": "EmptyLatentImage",
              "inputs": {"width": size, "height": size, "batch_size": 1}},
        "8": {"class_type": "KSampler",
              "inputs": {"model": ["1", 0], "positive": ["6", 0], "negative": ["6", 1],
                         "latent_image": ["7", 0], "seed": seed, "steps": steps,
                         "cfg": cfg, "sampler_name": "euler",
                         "scheduler": "normal", "denoise": 1.0}},
        "9": {"class_type": "VAEDecode",
              "inputs": {"vae": ["1", 2], "samples": ["8", 0]}},
        "10": {"class_type": "SaveImage",
               "inputs": {"images": ["9", 0], "filename_prefix": prefix}},
    }


def build_workflow_img2img(init_image, positive, seed, size=DEFAULT_SIZE, steps=24,
                           cfg=7.0, denoise=DENOISE, prefix="cerberus"):
    """The API-format graph: SD1.5, our puppet as the init, one sampler.

    No ControlNet, because there is nothing left for it to constrain. The init
    image already carries the pose, the palette and the backdrop, so what the
    sampler can invent is bounded by what we drew rather than by what the prompt
    asked for -- and the prompt is not a reliable place to bound anything. Six
    txt2img frames from one prompt asking for a pure white background came back
    with six different ones, white through near-black.
    """
    return {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": CHECKPOINT_IMG2IMG}},
        "2": {"class_type": "LoadImage", "inputs": {"image": init_image}},
        "3": {"class_type": "CLIPTextEncode",
              "inputs": {"clip": ["1", 1], "text": positive}},
        "4": {"class_type": "CLIPTextEncode",
              "inputs": {"clip": ["1", 1], "text": NEGATIVE}},
        "5": {"class_type": "VAEEncode",
              "inputs": {"pixels": ["2", 0], "vae": ["1", 2]}},
        "6": {"class_type": "KSampler",
              "inputs": {"model": ["1", 0], "positive": ["3", 0], "negative": ["4", 0],
                         "latent_image": ["5", 0], "seed": seed, "steps": steps,
                         "cfg": cfg, "sampler_name": "euler",
                         "scheduler": "normal", "denoise": denoise}},
        "7": {"class_type": "VAEDecode",
              "inputs": {"vae": ["1", 2], "samples": ["6", 0]}},
        "8": {"class_type": "SaveImage",
              "inputs": {"images": ["7", 0], "filename_prefix": prefix}},
    }


def write_init_images(fighter_id, out_dir, states=None, size=DEFAULT_SIZE, limit=None):
    """The puppet each img2img frame is repainted from. Returns the paths.

    `figure.render` draws at the game's 6 px per unit, so it is drawn at game size
    and scaled up rather than scaled down. That keeps one camera across both modes:
    the ground lands on the same row of the generator's square as it does in the
    control images, and the figure is the same height in both, so a frame generated
    either way registers into the same place on the canvas.
    """
    sheet = load_sheet(fighter_id)
    palette = figure.Palette(sheet["palette16"])
    profile = sheet.get("profile", {})
    out_dir.mkdir(parents=True, exist_ok=True)

    game = int(figure.PX_PER_UNIT * openpose_render.FRAME_UNITS)
    tall = (game, int(round(game * openpose_render.GROUND_FRACTION * 2)))
    grow = size / game

    written = []
    for state, count, _delay, _box, _continual, pose_name in openpose_render.select_states(states):
        builder = build_fighter.POSES.get(pose_name, build_fighter.POSES["idle"])
        for index in range(count):
            if limit is not None and len(written) >= limit:
                return written
            skeleton = figure.pose(**builder(index, count, profile))
            grown = figure.render(skeleton, tall, palette).resize(
                (size, int(round(tall[1] * grow))), Image.NEAREST)
            init = Image.new("RGB", (size, size), BACKDROP)
            init.paste(grown, (0, 0), grown)
            path = out_dir / f"{state}{index:02d}.png"
            init.save(path)
            written.append(path)

    return written


def load_sheet(fighter_id):
    path = SHEET_DIR / f"{fighter_id}.json"
    if not path.is_file():
        raise SystemExit(f"no design sheet for '{fighter_id}' at {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def generate(fighter_id, states, out_dir, size=DEFAULT_SIZE, steps=20, cfg=7.0,
             strength=0.9, seed=0, limit=None, host="127.0.0.1", port=8188,
             mode="controlnet", denoise=DENOISE):
    """Write the conditioning images, render each frame, write the manifest.

    Two modes, differing in where the pose comes from:

    * ``controlnet`` -- SDXL plus an OpenPose ControlNet, conditioned on the
      generated skeleton. Best on pose, worst on consistency: every frame is an
      independent sample, so the backdrop and the outfit change from frame to
      frame and some frames come back unusable. Kept for comparison.
    * ``img2img`` -- SD1.5 repainting our own drawing of the pose. The pose is
      looser, but the backdrop, palette and framing are inherited from the init
      image and therefore hold across a state. That is the property a sprite sheet
      is made of, so this is the default for real work.
    """
    sheet = load_sheet(fighter_id)
    appearance = sheet.get("appearance")
    if not appearance:
        raise SystemExit(
            f"design sheet '{fighter_id}' has no 'appearance' field.\n"
            "The palette says which colours the fighter is; 'appearance' says what\n"
            "it looks like. Without it the generator invents a different person in\n"
            "every frame, which is the one failure a palette cannot repair.")

    positive = f"{appearance}, {STYLE}"
    out_dir = Path(out_dir)
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    if mode == "img2img":
        poses = write_init_images(fighter_id, out_dir / "init", states, size, limit)
    else:
        poses = openpose_render.write_poses(fighter_id, out_dir / "poses", states, size)
        if limit is not None:
            poses = poses[:limit]
    if not poses:
        raise SystemExit("no frames selected; nothing to generate")

    client = ComfyClient(host, port)
    print(f"waiting for ComfyUI at {client.base} ...", flush=True)
    client.wait_until_ready()

    records = []
    started = time.time()
    for number, pose_path in enumerate(poses, start=1):
        frame_seed = seed + number - 1
        uploaded = client.upload_image(pose_path, subfolder=f"cerberus_{mode}")
        if mode == "img2img":
            graph = build_workflow_img2img(uploaded, positive, frame_seed, size,
                                           steps, cfg, denoise,
                                           prefix=f"cerberus_{fighter_id}")
        else:
            graph = build_workflow(uploaded, positive, frame_seed, size, steps, cfg,
                                   strength, prefix=f"cerberus_{fighter_id}")
        prompt_id = client.queue(graph)
        print(f"  [{number}/{len(poses)}] {pose_path.stem} seed={frame_seed} "
              f"-> {prompt_id[:8]}", flush=True)
        images = client.wait(prompt_id)
        raw_path = raw_dir / f"{pose_path.stem}.png"
        raw_path.write_bytes(client.fetch(images[0]))

        records.append({
            "frame": pose_path.stem,
            "state": pose_path.stem.rstrip("0123456789"),
            "seed": frame_seed,
            "pose": str(pose_path.relative_to(out_dir)),
            "pose_sha256": _digest(pose_path),
            "raw": str(raw_path.relative_to(out_dir)),
            "prompt_id": prompt_id,
        })

    manifest = {
        "fighter": fighter_id,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "seconds": round(time.time() - started, 1),
        "settings": {
            "mode": mode,
            "checkpoint": CHECKPOINT_IMG2IMG if mode == "img2img" else CHECKPOINT,
            "control_net": None if mode == "img2img" else CONTROL_NET,
            "size": size, "steps": steps, "cfg": cfg,
            "denoise": denoise if mode == "img2img" else None,
            "control_strength": None if mode == "img2img" else strength,
            "sampler": "euler", "scheduler": "normal", "seed_base": seed,
        },
        "prompt": {"positive": positive, "negative": NEGATIVE},
        "frames": records,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n",
                                           encoding="utf-8")

    print(f"\n{len(records)} raw render(s) in {manifest['seconds']}s -> {raw_dir}")
    print(f"manifest: {out_dir / 'manifest.json'}")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("fighter", help="design sheet id, e.g. tsu_ibano")
    parser.add_argument("--state", default=None, help="comma-separated states")
    parser.add_argument("--out", required=True, help="output directory")
    parser.add_argument("--size", type=int, default=DEFAULT_SIZE)
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--cfg", type=float, default=7.0)
    parser.add_argument("--mode", choices=("img2img", "controlnet"),
                        default="img2img",
                        help="where the pose comes from; img2img inherits the "
                             "backdrop, palette and framing from our own drawing "
                             "(default), controlnet pins the skeleton harder")
    parser.add_argument("--denoise", type=float, default=DENOISE,
                        help="img2img only: how much of our drawing the sampler may "
                             "repaint; low holds the pose, high holds identity")
    parser.add_argument("--strength", type=float, default=0.9,
                        help="controlnet only: 1.0 pins hardest to the skeleton")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8188)
    args = parser.parse_args(argv)

    states = None if not args.state else [
        name.strip() for name in args.state.split(",") if name.strip()]

    try:
        preflight(args.size, args.mode)
        generate(args.fighter, states, Path(args.out), args.size, args.steps,
                 args.cfg, args.strength, args.seed, args.limit, args.host, args.port,
                 mode=args.mode, denoise=args.denoise)
    except ComfyError as error:
        print(f"\n{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
