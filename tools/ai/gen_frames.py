#!/usr/bin/env python3
"""Generate raw fighter frames with SDXL + OpenPose ControlNet, via ComfyUI.

    python3 tools/ai/gen_frames.py tsu_ibano --state idle --out build/ai/tsu_ibano
    python3 tools/ai/gen_frames.py tsu_ibano --state idle --limit 1 --seed 1234

Writes the raw renders and a `manifest.json` recording everything needed to
reproduce them: checkpoint, control net, prompt, seed, sampler settings and the
hash of the control image. At ~117 frames per fighter you will regenerate often,
and a frame you cannot regenerate is a frame you cannot fix.

The one thing this does differently from the reference ControlNet workflow
-----------------------------------------------------------------------
`taldor_sdxl_controlnet.json` runs `Openpose_Detector_Preprocessor` over a
rendered picture and conditions on what the detector found. Here the control
image is written by `openpose_render.py` straight from `figure.pose()`, so:

  * the pose is the pose the engine will resolve hitboxes against, not a
    detector's opinion about a drawing;
  * it is reproducible from a state name and a frame index;
  * there is no detector pass, and no chance of it failing on a pose that is
    unusual (a grounded fighter, an arm crossing the body) and silently
    conditioning on nothing.

Everything downstream still has to earn its place: a raw render is 1024x1024 and
tens of thousands of colours, and the game wants 64x121 in sixteen. That is
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

import openpose_render  # noqa: E402
from comfy_client import ComfyClient, ComfyError  # noqa: E402

SHEET_DIR = REPO_ROOT / "design_sheets"

# Both models are already on this machine (see ~/ComfyUI/models). Pinned by name
# rather than discovered: a roster that changes style because a *different*
# checkpoint happened to be listed first is a roster that cannot be rebuilt.
CHECKPOINT = "sd_xl_base_1.0.safetensors"
CONTROL_NET = "xinsir-openpose-sdxl-1.0.safetensors"

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


def preflight(size=1024):
    """Refuse to start a run this machine cannot finish."""
    free = shutil.disk_usage(REPO_ROOT).free
    if free >= MIN_FREE_BYTES:
        return

    raise SystemExit(
        f"only {free / 1024 ** 3:.1f} GB free; a {size}px SDXL run wants "
        f"{MIN_FREE_BYTES / 1024 ** 3:.0f} GB of headroom.\n"
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


def load_sheet(fighter_id):
    path = SHEET_DIR / f"{fighter_id}.json"
    if not path.is_file():
        raise SystemExit(f"no design sheet for '{fighter_id}' at {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def generate(fighter_id, states, out_dir, size=1024, steps=20, cfg=7.0,
             strength=0.9, seed=0, limit=None, host="127.0.0.1", port=8188):
    """Write control images, generate a raw render for each, write the manifest."""
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
        uploaded = client.upload_image(pose_path, subfolder="cerberus_poses")
        prompt_id = client.queue(build_workflow(uploaded, positive, frame_seed,
                                                size, steps, cfg, strength,
                                                prefix=f"cerberus_{fighter_id}"))
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
            "checkpoint": CHECKPOINT, "control_net": CONTROL_NET,
            "size": size, "steps": steps, "cfg": cfg,
            "control_strength": strength, "sampler": "euler",
            "scheduler": "normal", "seed_base": seed,
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
    parser.add_argument("--size", type=int, default=1024)
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--cfg", type=float, default=7.0)
    parser.add_argument("--strength", type=float, default=0.9,
                        help="ControlNet strength; 1.0 pins hardest to the skeleton")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8188)
    args = parser.parse_args(argv)

    states = None if not args.state else [
        name.strip() for name in args.state.split(",") if name.strip()]

    try:
        preflight(args.size)
        generate(args.fighter, states, Path(args.out), args.size, args.steps,
                 args.cfg, args.strength, args.seed, args.limit, args.host, args.port)
    except ComfyError as error:
        print(f"\n{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
