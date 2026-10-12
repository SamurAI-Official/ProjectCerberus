#!/usr/bin/env python3
"""Generate raw fighter frames with ComfyUI, from our own drawings of the poses.

    python3 tools/ai/gen_frames.py tsu_ibano --state idle --out build/ai/tsu_ibano
    python3 tools/ai/gen_frames.py tsu_ibano --state idle --mode controlnet

Which mode, and the measurements that decided it
-----------------------------------------------
Each mode was run over the same eight frames of Tsu Ibano (six idle, two
2punch) and scored by `frame_fidelity.py`, which asks the only question a sprite
sheet actually cares about: does the generated frame still occupy the pixels of
the drawing its hitboxes were measured from? `n/a` below means the frame could not
be measured at all, because the generator painted over the whole canvas and there
was no background left to separate the figure from.

  `--mode controlnet`
      SDXL plus an OpenPose ControlNet conditioned on the skeleton. Holds the
      figure *where* we said and nothing else: six idle frames from one prompt came
      back with six backgrounds (white through near-black, from a prompt asking for
      pure white), six outfits, and two frames with nothing usable in them. Kept
      because it is the measurement that ruled it out, and because a pose with no
      drawing behind it could only ever be generated this way.

  `--mode canny`, empty latent (the first version of it)
      n/a on all eight frames. SDXL with a Canny ControlNet over our drawing, run
      from an empty latent, produced a manga panel with speech boxes, a rooftop
      city, blue window grids and a hologram. To a checkpoint asked to invent an
      image, a line drawing is a sketch to finish. That mode now feeds the drawing
      in as the latent as well; see `build_workflow_canny`.

  `--mode img2img`, denoise 0.40
      median IoU 0.933, min 0.898, and the same character in the same pose in every
      frame. A soft repaint of the drawing -- the blazer's crisp edges and the tie
      lose some definition -- which is this checkpoint's doing rather than the
      mode's. The default.

  `--mode img2img`, denoise 0.55
      median 0.807, min 0.731. More of a painting and no longer one person: the
      hair changes style frame to frame, one frame had no head, one had the tie
      flying off as a detached swoosh.

  `--mode img2img`, denoise 0.70
      median 0.699, min 0.495: one frame holding a satchel, one in a hooded coat,
      one mid-stride. The note that used to live in this file claimed 0.7 held the
      identity and relaxed only an extended arm; the artifacts it was written from
      are kept in `build/ai/refs/old_i2i.png` and show no such thing.

The lesson the sweep teaches is that the framing was never the problem. Every mode
put the crown at the top of the square and the feet on the 90% line, because the
skeleton is in the conditioning and `to_sprite.py` registers off the same camera.
What changes between these runs is the pose and the person, and those are the two
things a fighter's hitboxes are calibrated against -- so the mode that keeps them
is chosen over the mode that looks better.

The pictures these numbers come from are kept in `build/ai/refs/`:
`denoise_compare.png` (init, 0.40 and 0.55 as three rows of the same eight),
`mode_compare.png` (0.40 against the canny hybrid, at game scale), 
`probe_canny_pair.png` (the empty-latent canny, control above output), and
`sprites_lo.png` (the 0.40 batch as finished sprites). `frame_fidelity.py` prints
the numbers for any directory `gen_frames.py` has written, and `to_sprite.py` is
the second opinion: it reports the silhouette it found in units, which catches a
frame that registers but quantised badly.

Every mode writes the same `manifest.json`, recording everything needed to
reproduce a frame: mode, checkpoint, control net or denoise, prompt, seed,
sampler settings, the hash of the conditioning image and the fingerprint of the
frozen pose table (`tools/pipeline/pose_table.py`) the skeleton came from, so a
batch can be compared against the skeleton it cites rather than only against a
fresh one. At ~142 frames per fighter you will regenerate often, and a frame you
cannot regenerate is a frame you cannot fix.

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

The two reference arms
----------------------
Same eight frames, same protocol as the sweep above, and the question they add is where
the fighter's *identity* comes from -- because every mode above carries it in one sentence
of prose, and that is exactly what drifts between frames.

**Read the pose numbers on this page with the caveat below before trusting them: the
reference arm keeps the identity and does *not* adopt the pose.**

  `--mode reference`
      Identity: kept 0.88 with every band 0.56 and up (`identity_check.py`), which is what
      the arm was for. Composed init: `sheet_views.py`'s frozen body view scaled onto the
      skeleton's own height and crown, the state's face view on its own head, one denoise of
      0.40 -- and 0.40 over an init that already contains a complete standing figure leaves
      the sampler no reason to move a limb.

      **Pose: not adopted.** Every frame reproduces the *sheet's* standing silhouette. Along
      the front axis, in engine units, `build/reach_check.py` measures the arm's idle at +6.0
      and its punch at +5.5, against the skeleton's own +11.7 (idle guard) and +12.4
      (`2punch`'s far hand) -- and against the *puppet's* art at +11.3 and +12.2, which is
      what a pose looks like when the drawing is made from the skeleton. The strike hitboxes
      come from the skeleton (`strike_box`), so for this arm they describe limbs the art does
      not show: a punch whose box starts at +6 and reaches +16, fired by a figure whose hand
      is at +5.5. `tools/validate/validate_reach.py` is the check that says so.

      Raising the denoise does not recover the pose either: at 0.70 on the same four frames of
      `2punch` the punch still stops at +6.0, and the character pays for it -- its legs band
      falls from 0.59 to 0.24, below `identity_check.py`'s floor. The table in `INIT_CLIP` has
      that run next to the two compositions and the img2img one.

      Why the IoU above did not catch it: `frame_fidelity.py` scores a render against what
      `init/` holds. For img2img, canny and controlnet that is the *posed drawing*, so the
      number means "kept the pose". For this arm it is the composed *sheet art* -- a standing
      figure -- so the same number means "kept the drawing", and a frame that ignores the pose
      scores *better*, not worse. 0.911 here is a statement about the sheet, not the skeleton.

  `--mode ipadapter`
      Measured, and it lost before the pose question even applies. Same state, same seed, same
      size and same steps as the `reference` frame above: kept 0.53 with the bands at head 0.43
      / torso 0.39 / legs 0.14 -- the figure comes back light cyan (`#6fcefc` in the torso,
      `#bdecfd` in the legs) where the sheet is a cerulean blazer and tan trousers. The torso
      band also *moved* between its two frames of the same state (`#6fcefc` -> `#98ceeb`, a
      drift of 44.4 of 255), which is a different wrong colour frame to frame. And it does not
      survive the game's own pipeline: with an empty latent the sampler paints a full-bleed
      scene, so the pose score cannot be taken at all, and `to_sprite.py` turns one of the two
      frames into 294 pixels of art clipped by its texture and the other into an empty sprite.

What that leaves is the trade the arms were run to find, and all three ways out of it have now been
measured on one state -- `2punch`'s four frames, one seed each, 512px, 20 steps, the numbers in
`INIT_CLIP` and reproducible with `--state 2punch --limit 4`:

  * Composing identity where it cannot pin a limb, the head and torso from the sheet with the limbs
    left to the skeleton and the ControlNet, is the first candidate and it fails. Clipping the
    sheet's ink to the pose's own silhouette does empty the arm the pose throws out, and the sampler
    fills the gap by closing the silhouette rather than drawing into it: the figure comes back
    armless and hollow, its reach *shorter* than the whole view's (4.9 against 6.0 on the active
    frame), its identity lower (torso 0.65 -> 0.60) and its frames less consistent (drift 48.5 ->
    86.4). `--clip pose` is kept for the record, not for use.
  * A higher denoise on that init -- a denoise on the limbs and not the body was the second --
    does not buy the pose at 0.70 either, and repaints the character while it fails to.
  * The third is the one the measurements point at, because it stops confusing the pose's problem
    with the identity's. The puppet path, whose init is *drawn from* the skeleton, already has the
    pose: on those same four frames it reaches `hand_far` everywhere (10.5/12.3/12.4/12.0 against
    10.2/12.2/12.4/12.0, `validate_reach.py` green) and holds the drawing at IoU 0.94. What it loses
    is the face. Its kept share is the highest of any run (0.96) while its *head* band is the lowest
    (0.67 against 0.83 for the torso) and the head is the band that moves between frames of one
    state (drift 129 of 255). So the sheet belongs on the head -- the face panel this arm already
    composes well, worth 0.79 there -- and the body should stay the puppet's.
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
import sheet_views  # noqa: E402
from comfy_client import ComfyClient, ComfyError  # noqa: E402
from PIL import Image, ImageChops  # noqa: E402

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

# The canny mode's ControlNet: SDXL, and the only family of control nets this
# machine has. Used with `figure.render()`'s own drawing as the control image
# rather than with a detected pose, because a canny edge map of our drawing
# constrains the silhouette, the limb positions AND the internal boundaries --
# the blazer's front edge, the tie, the hairline -- and every one of those is
# something a hitbox is calibrated against.
CONTROL_NET_CANNY = "xinsir-canny-sdxl-1.0.safetensors"

# Canny's two thresholds, on a drawing that is flat colours under black ink.
# Wide, because the point is to keep the long boundaries and drop the paper
# grain of a JPEG-compressed reference.
CANNY_THRESHOLDS = (0.30, 0.85)

# How much of the drawing canny mode may repaint, with the ControlNet holding the
# edges through the whole of it. Higher than the img2img default is defensible here
# precisely because the boundaries are no longer the sampler's to move, so there is
# less for a high denoise to lose. `probe_canny` at denoise 1.0 from an empty latent
# is the measurement that showed the latent is not optional.
CANNY_DENOISE = 0.6

# What the puppet init is composited on, and therefore the backdrop every img2img
# frame inherits. A known flat colour is worth more than a pleasant one: to_sprite
# finds the backdrop by flood filling from the border, and txt2img could not be
# talked into a consistent background at all -- six idle frames came back as six
# different colours, white to near-black, from one prompt asking for pure white.
BACKDROP = (196, 208, 214)

# How much of the init the sampler may repaint. The whole trade-off is in this one
# number, so it is the one number here that was swept rather than guessed: eight
# frames (six idle, two 2punch) of Tsu Ibano at each value, scored by
# `frame_fidelity.py` against the drawing the hitboxes were measured from.
#
#   0.40  median IoU 0.933, min 0.898. The same character, pose and palette in all
#         eight. What it costs is crispness -- arms merge into the torso and the tie
#         fades in some frames -- because this is what this checkpoint does to flat
#         cel shapes. The default.
#   0.55  median 0.807, min 0.731. More of a painting: rendered hair, folds in the
#         cloth. No longer one character. The hair style changes frame to frame, one
#         frame came back with no head at all, and one had the tie flying off as a
#         detached blue swoosh.
#   0.70  median 0.699, min 0.495, and the failures are worse than the average: one
#         frame holding a satchel, one in a hooded coat, one mid-stride. The note
#         that used to be here claimed 0.7 held the identity and relaxed only an
#         extended arm. The artifacts it was written from are kept in
#         build/ai/refs/old_i2i.png and they do not show that either.
#
# 0.4 wins because a sprite sheet is a *set*. The softness costs a look; the drift
# costs the sheet, since a pose is the one thing a hitbox cannot share with a
# character who has changed between frames.
DENOISE = 0.4

# ---------------------------------------------------------------------------
# The two reference arms: where the sheet's identity goes.
# ---------------------------------------------------------------------------
#
# Every mode above puts the *puppet* in the latent and asks the sampler to redraw it. That is why
# they hold the pose, and it is why the character drifts: the puppet is a shape, not a person, and
# the only thing saying who it is has been one sentence of prose. These two arms are the same idea
# with the fighter's own reference sheet in the loop -- the skeleton still owns the pose, the sheet
# now owns the identity -- and they differ in *how* the sheet is injected:
#
#   `reference`  the sheet is pixels. The body view is scaled onto the skeleton's own height, the
#                state's face view onto its own head, and the result is the latent at a low denoise
#                with the same OpenPose ControlNet pinning the pose around it. No new weights.
#   `ipadapter`  the sheet is a conditioning vector. An IP-Adapter reads the same two views through
#                ViT-H CLIP and biases the sampler towards them from an empty latent at full
#                denoise, with the same ControlNet. One new dependency -- see IPADAPTER_MODEL.
#
# Neither is used without measuring it; both arms are scored by `frame_fidelity.py` on the same
# eight frames the denoise sweep above used (six idle, two 2punch of Tsu Ibano).

# Which frozen view is the body reference, by the name the design sheet gives it. The three-quarter
# view rather than the front: the skeleton is a side view facing right, and the front view is the
# one view whose silhouette disagrees with the pose everywhere on the canvas.
VIEW_BODY = "three_quarter"

# How much of the composed init the sampler may repaint. Higher than the img2img default because a
# standing reference pasted under a crouching skeleton is *meant* to be repainted below the
# shoulders -- what has to survive is the head, where the face paste and the pose control agree.
#
# That intent was measured and it does not hold either. This number decides how much of the init is
# repainted, and repainting more does not put a pose into it: at 0.70 the arm's punch still stops at
# +6.0, the same place it stops at 0.40, while the character's legs band falls from 0.59 to 0.24.
# The table in `INIT_CLIP` is that pair of runs against the two compositions.
DENOISE_REFERENCE = 0.40

# The face crop is drawn this many engine units tall, and the skeleton's head centre lands this far
# down it. Both are measurements of the reference sheets rather than preferences: on both sheets
# hair-top-to-chin is about 62% of a face panel and the collar takes the rest, so a panel 8.6 units
# tall (against a 5.4 unit head, 2 x HEAD_R) puts the face on the head with the collar below it.
FACE_HEAD_SPAN = 8.6
FACE_HEAD_LINE = 0.36
# Hair-top-to-chin as a share of a face panel: the same measurement `FACE_HEAD_SPAN` is built on
# ("hair-top-to-chin is about 62% of a face panel and the collar takes the rest"), kept separately
# because it is also where the crop goes. A panel is a *head with a collar*, and the collar is drawn
# for an upright chest: paste it onto `knocked_down`'s lying torso and it draws a tie across the
# sleeve, which is a composition error the game's own art does not make -- `data/tsu_ibano/
# knocked_down00.png` is an upright head on a lying body, with no collar in sight. Measured, the
# collar also costs the torso band (0.83 without any paste, 0.79 with the whole panel, 0.80 with the
# crop on the four `2punch` frames). So `head` is the default crop and `sheet` keeps the whole panel.
FACE_HEAD_ONLY = 0.62
# Whether the pasted panel is trimmed to the head `figure.render` drew, or may stick out above it.
#
# A panel is measured, not fitted: `FACE_HEAD_SPAN` at `FACE_HEAD_LINE` puts its top 3.1 engine units
# above the head's centre, and `figure.HEAD_R` is 2.7 -- so the sheet's hair is 0.4 units taller than
# the head it is pasted onto, which is 2 pixels at the game's 6 per unit. On a pose whose crown is
# near the top of the sprite canvas that is the whole of the clearance: `sprite_check.py` on one run
# found `start00`, `turn00` and `1punch00` with 2 pixels of art on their top border -- a hair tip cut
# flat by the texture. The crop takes those 0.4 units off the panel instead. It cannot stop the
# *sampler* from drawing above the silhouette it was given (the run before this option had five
# frames on their border, by 4 to 11 pixels), only the paste from raising the crown itself.
FACE_CLIP_TO_HEAD = True

# Where a frame's *face* comes from, on the mode whose init is our own drawing of the pose.
#
# The measurement that put it here is in `INIT_CLIP`'s table: with the pose in the init every band of
# the character survives except the head -- 0.67, against 0.83 for the torso and 0.65 for the legs --
# and the head is the only band that moves between frames of one state (drift 129 of 255, against
# 48.5 for the reference arm's composed init). A face is the one part of a fighter that a prompt
# cannot describe and a 512px repaint cannot preserve, so the sheet supplies it as pixels.
#
# All three settings, same four `2punch` frames, same seeds, 512px, 20 steps, `denoise` 0.40 unless
# said otherwise (`identity_check.py`'s bands and drift; `reach` from `build/front_scan.py`, against
# `hand_far` at +10.2/+12.2/+12.4/+12.0):
#
#   --face-panel  denoise  reach (front, units)     kept  head  torso  legs  drift
#   none          0.40     10.5 12.3 12.4 12.0     0.96  0.67  0.83   0.65  129.2
#   sheet         0.40     10.7 12.3 12.3 12.1     0.97  0.72  0.79   0.64   55.9
#   head          0.40     10.6 12.3 12.4 12.7     0.97  0.71  0.82   0.64   43.3
#   head          0.30     10.6 12.3 12.4 12.0     0.97  0.68  0.81   0.64   42.9
#
# `head` is the default because it takes the pose and the identity both: the head band is up where
# the whole panel has it (0.71 against 0.72), the torso band stays where no paste at all leaves it
# (0.82 against 0.83, and against the whole panel's 0.79 -- the collar *was* costing that band), the
# frames of one state agree more than either alternative (43.3), and `reach` is green on all four.
# The lower denoise is not: at 0.30 the same crop keeps the same frames but loses the band it was
# pasted for (0.68 against 0.71), so `DENOISE` stays 0.40. "none" is the drawing's own face, which is
# what every frame in `build/ai/` was made with, and "sheet" keeps the whole panel; both are kept so
# the difference stays measurable.
FACE_PANEL = "head"

# What the composed init does where the pose and the sheet disagree -- and what four runs say about
# it. The intent was that the sampler repaint the parts the standing view gets wrong: a reference
# pasted under a crouching skeleton, a downward arm under a thrown punch. It does not.
#
# Measured on `2punch`'s four frames, one fighter, one seed per frame (0..3), 512px, 20 steps, with
# only this setting and the denoise varying. `reach` is the render's front extent in engine units
# against the skeleton's own `hand_far`, which is +10.2, +12.2, +12.4, +12.0 on those four frames;
# bands and drift are `identity_check.py`'s on the same frames.
#
#   init                    denoise  reach (front, units)    kept  head  torso  legs  drift
#   sheet, whole view       0.40     5.3 6.2 6.0 6.6        0.89  0.79  0.65   0.59  48.5
#   sheet, clipped to pose  0.40     4.4 5.3 4.9 4.8        0.81  0.76  0.60   0.54  86.4
#   sheet, whole view       0.70     6.5 6.4 6.0 6.0        0.76  0.66  0.34   0.24  76.9
#   sheet, clipped to pose  0.70     4.6 6.6 5.1 4.8        0.74  0.76  0.46   0.36  92.0
#   the posed drawing, img2img      10.5 12.3 12.4 12.0     0.96  0.67  0.83   0.65 129.2
#
# Two things follow. A pose arrives only if it is in the init's pixels: the drawing made *from* the
# skeleton reaches its joint on all four frames and the sheet's standing figure on none of them, at
# either denoise -- 0.70 does not buy the arm back, it only repaints the character (legs 0.59 ->
# 0.24, below the floor). And clipping the sheet to the pose's silhouette, which empties the limb
# that has to move, is *worse* than leaving it: the sampler keeps the hard edge the clip leaves
# against the backdrop instead of drawing an arm into the gap, so the figure comes back armless and
# hollow, reach shortens again (6.0 -> 4.9 on the active frame) and identity falls with it.
#
# So the default is the whole view. What the sheet has to supply is the part img2img loses rather
# than the part it keeps: with the pose in the init, the head is the weak band (0.67 against 0.83
# for the torso) and the only band that moves between frames of one state (drift 129) -- the face.
INIT_CLIP = "none"

# IP-Adapter's own weights, pinned by name for the same reason the checkpoints are: a run that came
# back as a different fighter because a different adapter was listed first is a run that cannot be
# rebuilt. Both paths are relative to ~/ComfyUI/models.
IPADAPTER_MODEL = "ip-adapter-plus_sdxl_vit-h.safetensors"
CLIP_VISION_MODEL = "CLIP-ViT-H-14-launcher-v2.safetensors"

# How hard each reference pushes, as the adapter's own `weight`. The body view carries the costume
# and the face view carries the face, and an adapter's two weights do not simply add up, so these
# are the A/B's own numbers rather than a preference; see the docstring.
REFERENCE_WEIGHT = 0.8
FACE_WEIGHT = 0.6

# Shared across every fighter so the roster reads as one game rather than a pile
# of commissions. "side view facing right" is the load-bearing phrase: the
# skeleton is a side view and a 3/4 or front render cannot be posed onto it.
STYLE = ("2D fighting game character sprite, full body, side view facing right, "
         "flat cel shading, bold clean black outlines, limited flat colour palette, "
         "crisp silhouette, clean pure white background, no text, no watermark")

# The 90s anime/cel fighting-game read, on top of STYLE. STYLE names the
# constraints (flat, cel, side view, white bg); this names the *look* the
# reference sheets ask for -- the crisp linework and saturated flat colour of a
# 90s anime fighter. It is a bias, not a load-bearing phrase like STYLE's "side
# view facing right": the checkpoint already pulls anime, this steers the era and
# the finish. Kept separate so the hard constraints can be re-measured without
# touching the aesthetic direction. First measured at build/ai/i2i_anime -- see
# the commit message that carries it.
STYLE_ANIME = ("90s anime style, retro anime, crisp lineart, sharp black ink lines, "
               "saturated flat colours, cel-shaded, clean vector-like shapes, "
               "vivid, high contrast, no gradient shading, no airbrush, no blur")

NEGATIVE = ("3/4 view, front view, multiple characters, cropped, cut off, "
            "extra limbs, extra arms, extra legs, deformed hands, mutated hands, "
            "blurry, soft gradient, photorealistic, 3d render, text, watermark, "
            "signature, background scenery, ground shadow, border, frame, "
            # The anti-90s-cel half of the negative: the things a painterly model
            # reaches for that undo the flat look. A 90s cel sprite is hard-edged
            # and few-tone; these ban the smooth, shaded, over-worked result that
            # would otherwise be the failure mode of any modern checkpoint.
            "gradient shading, airbrush, soft shading, smooth shading, painterly, "
            "sketch, crosshatching, grainy, noisy, chromatic aberration, "
            "photorealistic skin, subsurface scattering, lens flare, bokeh, "
            # Props. A character sheet shows the fighter walking to school with a
            # satchel; a fighter sprite with a satchel in its hand is a sprite
            # whose punch has a bag in it. The design sheet's props are costume
            # reference, not match equipment, and the prompt says so explicitly
            # because img2img will happily invent one.
            "bag, satchel, briefcase, backpack, purse, held object, "
            "weapon, sword, staff, jacket tied around waist")

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

# What the IP-Adapter arm costs *on top of* an ordinary SDXL run.
#
# It holds SDXL, the OpenPose ControlNet, ViT-H CLIP and the SDXL IP-Adapter open at once: 14.8 GB
# of weights on disk against the 8.9 GB the other SDXL modes load, and on a 16 GB machine the
# overflow becomes swapfiles, which are disk. Measured twice at --size 512 -- one run grew swap by
# 4.2 GB (volume 6.2 -> 2.0 GB free) and a second by 9.1 GB (16.0 -> 6.9 GB), and both were ended
# by a reboot to get the volume back. The floor below is the SDXL floor plus the larger of those,
# because a guard that lets a run start and then has the disk fill underneath it is worse than no
# guard at all: it is the same afternoon, with a reboot in it.
IPADAPTER_FREE_BYTES = 24 * 1024 ** 3


def preflight(size=DEFAULT_SIZE, mode="controlnet"):
    """Refuse to start a run this machine cannot finish."""
    # The weights are the same either way, and they are the bulk of it; the
    # activations are what the render size controls, and they go as the square.
    needed = MIN_FREE_BYTES if size > 512 else MIN_FREE_BYTES // 2
    if mode == "img2img":
        # 2.0 GB of SD1.5 rather than 8.9 GB of SDXL plus ControlNet. The floor is
        # those weights and enough room for the swap they still provoke.
        needed //= 4
    elif mode == "ipadapter":
        # All four of the heavy models in one graph -- see IPADAPTER_FREE_BYTES.
        needed = IPADAPTER_FREE_BYTES if size > 512 else IPADAPTER_FREE_BYTES // 2
    free = shutil.disk_usage(REPO_ROOT).free
    if free >= needed:
        return

    weights = "14.8 GB (SDXL, ControlNet, ViT-H CLIP and the IP-Adapter)" \
        if mode == "ipadapter" else "8.9 GB"
    raise SystemExit(
        f"only {free / 1024 ** 3:.1f} GB free; a {size}px SDXL run wants "
        f"{needed / 1024 ** 3:.0f} GB of headroom.\n"
        f"The checkpoints alone are ~{weights}. Where they do not fit in RAM the "
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


def build_workflow_canny(control_image, positive, seed, size=DEFAULT_SIZE, steps=24,
                         cfg=7.0, strength=0.9, denoise=CANNY_DENOISE, prefix="cerberus",
                         thresholds=CANNY_THRESHOLDS):
    """The API-format graph: SDXL painting our drawing, edges pinned by Canny.

    Two things are holding the figure here, and the first version of this graph
    had only one of them. It sampled *from an empty latent* at full denoise with
    the drawing attached as a canny control, and eight frames came back as eight
    full-bleed illustrations -- a manga panel with speech boxes, a rooftop city,
    blue window grids, a hologram -- each one a different character in a different
    pose, none of them separable from a background because the model had painted
    over the whole canvas. That is what a line drawing *is* to a checkpoint asked
    to invent an image: a sketch to finish. The control map was followed, at the
    level of "there are lines here", and everything between the lines was invented.

    So the latent is our drawing too (`VAEEncode` of the same control image, at
    `CANNY_DENOISE`), which is what puts the palette, the backdrop and the framing
    back under our control, and leaves the ControlNet the job it does well: holding
    the silhouette, the limb positions and the internal boundaries -- the blazer's
    front edge, the tie, the hairline -- through a repaint that would otherwise be
    free to move them. Every one of those is something a hitbox is calibrated
    against.
    """
    return {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": CHECKPOINT}},
        "2": {"class_type": "ControlNetLoader",
              "inputs": {"control_net_name": CONTROL_NET_CANNY}},
        "3": {"class_type": "CLIPTextEncode",
              "inputs": {"clip": ["1", 1], "text": positive}},
        "4": {"class_type": "CLIPTextEncode",
              "inputs": {"clip": ["1", 1], "text": NEGATIVE}},
        "5": {"class_type": "LoadImage", "inputs": {"image": control_image}},
        "6": {"class_type": "Canny",
              "inputs": {"image": ["5", 0], "low_threshold": thresholds[0],
                         "high_threshold": thresholds[1]}},
        "7": {"class_type": "ControlNetApplyAdvanced",
              "inputs": {"positive": ["3", 0], "negative": ["4", 0],
                         "control_net": ["2", 0], "image": ["6", 0],
                         "strength": strength, "start_percent": 0.0,
                         "end_percent": 1.0}},
        "8": {"class_type": "VAEEncode",
              "inputs": {"pixels": ["5", 0], "vae": ["1", 2]}},
        "9": {"class_type": "KSampler",
              "inputs": {"model": ["1", 0], "positive": ["7", 0], "negative": ["7", 1],
                         "latent_image": ["8", 0], "seed": seed, "steps": steps,
                         "cfg": cfg, "sampler_name": "euler",
                         "scheduler": "normal", "denoise": denoise}},
        "10": {"class_type": "VAEDecode",
               "inputs": {"vae": ["1", 2], "samples": ["9", 0]}},
        "11": {"class_type": "SaveImage",
               "inputs": {"images": ["10", 0], "filename_prefix": prefix}},
    }


def build_workflow_reference(init_image, pose_image, positive, seed, size=DEFAULT_SIZE, steps=20,
                             cfg=7.0, strength=0.9, denoise=DENOISE_REFERENCE,
                             prefix="cerberus"):
    """The API-format graph: the sheet composited into the pose, redrawn under the pose control.

    The latent is the composed init (`compose_reference_init`), so what the sampler starts from is
    the fighter's own sheet at the fighter's own scale -- costume, palette and face as pixels rather
    than as a sentence. The OpenPose ControlNet supplies the half of the pose the composite cannot:
    the reference is a *standing* view and most of these states are not, so the network is what
    keeps the crouch a crouch while the latent keeps the person a person.

    It is canny mode's arrangement with a different picture in it -- drawing in the latent, network
    over it -- and the question the arm answers is whether 40% of a latent can carry a sheet's worth
    of identity. Canny is the control it is measured against: both are SDXL, both hold the pose, and
    only one of them has ever seen this fighter.
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
        "6": {"class_type": "LoadImage", "inputs": {"image": init_image}},
        "7": {"class_type": "ControlNetApplyAdvanced",
              "inputs": {"positive": ["3", 0], "negative": ["4", 0],
                         "control_net": ["2", 0], "image": ["5", 0],
                         "strength": strength, "start_percent": 0.0, "end_percent": 1.0}},
        "8": {"class_type": "VAEEncode",
              "inputs": {"pixels": ["6", 0], "vae": ["1", 2]}},
        "9": {"class_type": "KSampler",
              "inputs": {"model": ["1", 0], "positive": ["7", 0], "negative": ["7", 1],
                         "latent_image": ["8", 0], "seed": seed, "steps": steps,
                         "cfg": cfg, "sampler_name": "euler",
                         "scheduler": "normal", "denoise": denoise}},
        "10": {"class_type": "VAEDecode",
               "inputs": {"vae": ["1", 2], "samples": ["9", 0]}},
        "11": {"class_type": "SaveImage",
               "inputs": {"images": ["10", 0], "filename_prefix": prefix}},
    }


def build_workflow_ipadapter(pose_image, body_image, face_image, positive, seed,
                             size=DEFAULT_SIZE, steps=20, cfg=7.0, strength=0.9,
                             body_weight=REFERENCE_WEIGHT, face_weight=FACE_WEIGHT,
                             prefix="cerberus"):
    """The API-format graph: SDXL, the sheet as two conditioning vectors, the pose pinned.

    Where `reference` puts the sheet in the latent, this puts it in the sampler: two IP-Adapter
    patches read the body view and the state's face view through ViT-H CLIP and bias attention
    towards them for the whole of the sample. Two chained nodes rather than one, because the two
    views are not a batch of one reference -- they are different references at different weights,
    and chaining is how the adapter's own documentation combines them.

    The latent is empty at full denoise, so nothing about the composition comes from a reference:
    the pose is the ControlNet's alone and the identity the adapter's alone. That is what makes this
    the arm worth having -- it cannot cheat with alignment, so if it holds up it is the one that
    scales to a state whose silhouette the sheet never showed.
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
        "6": {"class_type": "IPAdapterModelLoader",
              "inputs": {"ipadapter_file": IPADAPTER_MODEL}},
        "7": {"class_type": "CLIPVisionLoader",
              "inputs": {"clip_name": CLIP_VISION_MODEL}},
        "8": {"class_type": "LoadImage", "inputs": {"image": body_image}},
        "9": {"class_type": "IPAdapterAdvanced",
              "inputs": {"model": ["1", 0], "ipadapter": ["6", 0], "clip_vision": ["7", 0],
                         "image": ["8", 0], "weight": body_weight, "weight_type": "linear",
                         "combine_embeds": "concat", "start_at": 0.0, "end_at": 1.0,
                         "embeds_scaling": "V only"}},
        "10": {"class_type": "LoadImage", "inputs": {"image": face_image}},
        "11": {"class_type": "IPAdapterAdvanced",
               "inputs": {"model": ["9", 0], "ipadapter": ["6", 0], "clip_vision": ["7", 0],
                          "image": ["10", 0], "weight": face_weight, "weight_type": "linear",
                          "combine_embeds": "concat", "start_at": 0.0, "end_at": 1.0,
                          "embeds_scaling": "V only"}},
        "12": {"class_type": "ControlNetApplyAdvanced",
               "inputs": {"positive": ["3", 0], "negative": ["4", 0],
                          "control_net": ["2", 0], "image": ["5", 0],
                          "strength": strength, "start_percent": 0.0, "end_percent": 1.0}},
        "13": {"class_type": "EmptyLatentImage",
               "inputs": {"width": size, "height": size, "batch_size": 1}},
        "14": {"class_type": "KSampler",
               "inputs": {"model": ["11", 0], "positive": ["12", 0], "negative": ["12", 1],
                          "latent_image": ["13", 0], "seed": seed, "steps": steps,
                          "cfg": cfg, "sampler_name": "euler",
                          "scheduler": "normal", "denoise": 1.0}},
        "15": {"class_type": "VAEDecode",
               "inputs": {"vae": ["1", 2], "samples": ["14", 0]}},
        "16": {"class_type": "SaveImage",
               "inputs": {"images": ["15", 0], "filename_prefix": prefix}},
    }


def check_ipadapter(client):
    """Refuse an IP-Adapter run whose nodes or weights are missing, and say exactly what to do.

    The way this arm fails without the check is ComfyUI's way: the graph is rejected with a node
    error naming a class this server has never heard of, which reads as "the workflow is wrong"
    rather than "the dependency is not installed". So it is checked up front, against the server's
    own node list and its own file lists, and the message names the file, the folder and the URL.
    """
    wanted_nodes = ("IPAdapterAdvanced", "IPAdapterModelLoader", "CLIPVisionLoader")
    loaded, absent = {}, []
    for class_name in wanted_nodes:
        info = client.object_info(class_name)
        if info:
            loaded[class_name] = info
        else:
            absent.append(class_name)

    if absent:
        raise SystemExit(
            "this ComfyUI has not loaded the IP-Adapter nodes (%s missing).\n"
            "  git clone https://github.com/cubiq/ComfyUI_IPAdapter_plus "
            "$HOME/ComfyUI/custom_nodes/ComfyUI_IPAdapter_plus\n"
            "then restart ComfyUI: custom nodes are imported once at start-up, so one installed "
            "under a running server is not loaded by it." % ", ".join(absent))

    wanted_files = (
        ("IPAdapterModelLoader", "ipadapter_file", IPADAPTER_MODEL, "$HOME/ComfyUI/models/ipadapter",
         "https://huggingface.co/h94/IP-Adapter/resolve/main/sdxl_models/" + IPADAPTER_MODEL),
        ("CLIPVisionLoader", "clip_name", CLIP_VISION_MODEL, "$HOME/ComfyUI/models/clip_vision",
         "https://huggingface.co/h94/IP-Adapter/resolve/main/models/image_encoder/model.safetensors"),
    )
    missing = []
    for class_name, input_name, filename, folder, url in wanted_files:
        choices = loaded[class_name]["input"]["required"].get(input_name, [[]])[0]
        if filename not in choices:
            missing.append(f"  {filename}\n    put it in {folder}/\n    curl -L -o "
                           f"{folder}/{filename} {url}")
    if missing:
        raise SystemExit("ComfyUI cannot see the IP-Adapter weights:\n" + "\n".join(missing))
    return True


def write_init_images(fighter_id, out_dir, states=None, size=DEFAULT_SIZE, limit=None,
                      face_panel=None):
    """The puppet each img2img frame is repainted from. Returns the paths.

    `figure.render` draws at the game's 6 px per unit, so it is drawn at game size
    and scaled up rather than scaled down. That keeps one camera across both modes:
    the ground lands on the same row of the generator's square as it does in the
    control images, and the figure is the same height in both, so a frame generated
    either way registers into the same place on the canvas.

    `face_panel` is `"sheet"`, `"head"` or None. `"head"` pastes the state's expression view with the
    collar cropped off it; `"sheet"` keeps the whole panel; None leaves the drawing's own face alone.
    The caller passes None for the modes that *trace* this drawing rather than repaint it: a pasted
    face is a face's worth of edges, and Canny was measured without them. See `compose_puppet_init`,
    `FACE_PANEL` and `FACE_HEAD_ONLY`.
    """
    sheet = load_sheet(fighter_id)
    palette = figure.Palette(sheet["palette16"])
    profile = sheet.get("profile", {})
    out_dir.mkdir(parents=True, exist_ok=True)
    views = load_views(fighter_id) if face_panel in ("sheet", "head") else {}
    face_refs = {}

    written = []
    for state, count, _delay, _box, _continual, pose_name in openpose_render.select_states(states):
        builder = build_fighter.POSES.get(pose_name, build_fighter.POSES["idle"])
        face = None
        if face_panel in ("sheet", "head"):
            # The same lookup the two reference arms use, so a state wears the same expression
            # whichever mode draws it -- and so an unlisted state is an error here too rather than
            # a frame that quietly wears somebody else's face.
            _role, expression = expression_for_state(sheet, state)
            view = expression["view"]
            if view not in views:
                raise SystemExit("expressions['%s'].view is '%s', which is not one of %s's views: %s"
                                 % (_role, view, sheet["id"], ", ".join(sorted(views))))
            face_refs.setdefault(view, views[view])
            face = face_refs[view]
        for index in range(count):
            if limit is not None and len(written) >= limit:
                return written
            skeleton = figure.pose(**builder(index, count, profile))
            path = out_dir / f"{state}{index:02d}.png"
            compose_puppet_init(skeleton, size, palette, face,
                                head_only=face_panel == "head",
                                clip_to_head=FACE_CLIP_TO_HEAD).save(path)
            written.append(path)

    return written


def load_views(fighter_id):
    """The design sheet's frozen views, as RGBA images, keyed by the name in the sheet.

    The boxes are the sheet's and the extraction is re-run here rather than read out of
    `design_sheets/out/`, so a retuned box cannot leave a stale crop behind: the pixels that
    condition a frame are the ones the sheet describes now.
    """
    _path, sheet = sheet_views.load_sheet(fighter_id)
    sheet_px, _sheet_path = sheet_views.sheet_image(sheet)
    stored = sheet_views.stored_views(sheet)
    if not stored:
        raise SystemExit(
            f"design sheet '{fighter_id}' has no reference.views, so there is no sheet to "
            "condition on.\nRun `python3 tools/ai/sheet_views.py %s --detect --qc DIR`, author the "
            "boxes, then `--write` and `--extract`." % fighter_id)
    return {name: sheet_views.extract_view(sheet_px, view["box"],
                                           trim=bool(view.get("trim")))
            for name, view in stored.items()}


def expression_for_state(sheet, state):
    """(role, {"view": ..., "prompt": ...}) for the face this state wears.

    Two lookups, in this order, because they answer different questions: `build_fighter` knows which
    *states* are angry, and the design sheet knows which *panel* is angry. A fighter with four
    different face panels needs a change in neither file's other half.
    """
    role = build_fighter.STATE_EXPRESSION.get(state)
    if role is None:
        raise SystemExit(f"state '{state}' has no expression role "
                         "(see build_fighter.STATE_EXPRESSION)")
    reference = sheet.get("reference") or {}
    expressions = reference.get("expressions") or {}
    if role not in expressions:
        raise SystemExit(
            "design sheet '%s' has no reference.expressions['%s'], which state '%s' wears.\n"
            "Add it: {\"view\": \"<one of the sheet's face_* views>\", \"prompt\": \"...\"}"
            % (sheet.get("id"), role, state))
    expression = expressions[role]
    views = reference.get("views") or {}
    if expression.get("view") not in views:
        raise SystemExit(
            "expressions['%s'].view is '%s', which is not one of %s's views: %s"
            % (role, expression.get("view"), sheet.get("id"), ", ".join(sorted(views))))
    return role, expression


def flatten(view, background=BACKDROP):
    """A view composited onto the backdrop, for anything that cannot take an alpha channel.

    ComfyUI's `LoadImage` drops the alpha and keeps the pixel under it, and the pixels under these
    crops are the reference sheet's paper and grid -- which is what an adapter would then be reading
    a fighter out of. Flattening on the backdrop is the same background the composed init uses, so
    both arms hand the generator the same figure on the same field.
    """
    flat = Image.new("RGB", view.size, background)
    flat.paste(view, (0, 0), view)
    return flat


def _grown_puppet(skeleton, size, palette):
    """`figure.render` of this pose, grown to the render size.

    `figure.render` draws at the game's own scale and is grown rather than the camera being
    changed, which is what keeps one camera across every image in a run: at 6 px per unit over a
    40-unit frame the drawing is 240 px wide, so growing to `size` is a factor of `size / 240` --
    exactly `size / FRAME_UNITS`, the factor `openpose_render.project` uses. A composed init and a
    control image are therefore comparable pixel for pixel, and so are both against the hitboxes.
    """
    game = int(figure.PX_PER_UNIT * openpose_render.FRAME_UNITS)
    tall = (game, int(round(game * openpose_render.GROUND_FRACTION * 2)))
    return figure.render(skeleton, tall, palette).resize(
        (size, int(round(tall[1] * size / game))), Image.NEAREST)


def _paste_face(init, skeleton, size, face, head_only=False, clip_to_head=True):
    """Paste the sheet's face view onto the skeleton's head; returns the same image.

    Shared by both compositions rather than written twice, because this is the one part of a frame
    where the sheet has beaten the generator on every measurement taken so far, and the two arms
    cannot be allowed to disagree about where it goes. It goes on the *skeleton's* head and not the
    body's, so a crouch or a knockout still gets a face on the top of the figure instead of one where
    a standing body would have carried it -- an upright head, which is what the game's own knocked
    down frames are.

    `head_only` clips the panel to its hair-top-to-chin part before pasting. The scale and the
    placement come from the whole panel either way, so the face lands byte for byte where it would
    have: all this decides is whether the collar comes with it. See `FACE_HEAD_ONLY`.

    `clip_to_head` trims whatever part of the panel lands above the crown of the head `figure.render`
    drew, so the paste cannot make the figure taller than its own pose. See `FACE_CLIP_TO_HEAD`.
    """
    ink = face.getbbox()
    if ink is None:
        raise SystemExit("the face view is empty: there is nothing to paste onto the head")
    face_h = FACE_HEAD_SPAN * size / openpose_render.FRAME_UNITS
    face_scale = face_h / float(ink[3] - ink[1])
    face_scaled = face.resize((max(1, round(face.width * face_scale)),
                               max(1, round(face.height * face_scale))), Image.LANCZOS)
    face_ink = face_scaled.getbbox()
    if head_only:
        face_scaled = face_scaled.crop(
            (face_ink[0], face_ink[1], face_ink[2],
             face_ink[1] + max(1, round(FACE_HEAD_ONLY * (face_ink[3] - face_ink[1])))))
    head_x, head_y = openpose_render.project(skeleton["head"], size)
    paste_y = round(head_y - FACE_HEAD_LINE * (face_ink[3] - face_ink[1]) - face_ink[1])
    if clip_to_head:
        px_per_unit = size / float(openpose_render.FRAME_UNITS)
        cut = round(head_y - figure.HEAD_R * px_per_unit) - paste_y
        if cut > 0:
            face_scaled = face_scaled.crop((0, cut, face_scaled.width, face_scaled.height))
            paste_y += cut
    init.paste(face_scaled,
               (round(head_x - (face_ink[0] + face_ink[2]) / 2.0), paste_y), face_scaled)
    return init


def compose_puppet_init(skeleton, size, palette, face=None, head_only=False, clip_to_head=True):
    """img2img's init: our own drawing of the pose on the backdrop, its head wearing the sheet's face.

    The drawing is the pose -- it is what `figure.render` makes *from* the skeleton, and the reason
    this mode reaches its hitboxes (measured: `hand_far` on all four frames of `2punch`, 10.5/12.3/
    12.4/12.0 against 10.2/12.2/12.4/12.0, at IoU 0.94 against the drawing). Its head is its weak
    point, so `face` -- the state's own expression view from the sheet -- is pasted there before the
    sampler sees it, and the sampler blends it in the same repaint that keeps the pose.

    With `face` left out this is exactly what `write_init_images` drew before there was an option:
    the grown drawing composited on the backdrop at the game's own scale.
    """
    init = Image.new("RGB", (size, size), BACKDROP)
    drawn = _grown_puppet(skeleton, size, palette)
    # The drawing is its own mask: pasting it onto an RGB canvas without one copies the *transparent*
    # pixels too, whose RGB is black -- which is the whole backdrop at (196, 208, 214) replaced by
    # 87% of the canvas in black. The composed init pastes its body onto an RGBA layer instead, so
    # only this one can get it wrong, and `cmp` against a pre-option init is the test for it.
    init.paste(drawn, (0, 0), drawn)
    return init if face is None else _paste_face(init, skeleton, size, face, head_only, clip_to_head)


def compose_reference_init(skeleton, size, palette, body, face, clip=INIT_CLIP):
    """The sheet under the skeleton: body view scaled to the pose's own height, face on its head.

    The alignment *is* the arm. The body view is scaled so its ink is exactly as tall as our own
    drawing of this pose and its crown lands on the same row, which puts its head, shoulders and
    feet where the skeleton already is; the face view is then placed on the skeleton's head rather
    than on the body's, so a crouch still gets a face on the top of the composed figure instead of
    one where a standing body would have carried it.

    `clip` decides what happens where the pose and the sheet disagree, which is every limb that
    moves. See `INIT_CLIP` for the measurement that made this an option rather than a detail.
    """
    puppet = Image.new("RGBA", (size, size))
    puppet.paste(_grown_puppet(skeleton, size, palette), (0, 0))
    posed = puppet.getbbox()
    ink = body.getbbox()
    if posed is None or ink is None:
        raise SystemExit("nothing to compose: either the pose or the reference view is empty")

    drawn_h = posed[3] - posed[1]
    scale = drawn_h / float(ink[3] - ink[1])
    body_scaled = body.resize((max(1, round(body.width * scale)),
                               max(1, round(body.height * scale))), Image.LANCZOS)
    body_ink = body_scaled.getbbox()
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    layer.paste(body_scaled,
                (round((posed[0] + posed[2]) / 2.0 - (body_ink[0] + body_ink[2]) / 2.0),
                 posed[1] - body_ink[1]), body_scaled)

    if clip == "pose":
        # Keep the sheet's pixels only where the pose has a body of its own. One intersection does
        # both halves of the job: an arm the pose throws out is empty backdrop in a view of a
        # standing figure, and an arm a standing figure hangs out is outside the pose's outline --
        # so the limb the sampler has to draw is left empty, and the limbs that already agree (an
        # idle's arms, the head, the torso) keep their sheet pixels and their identity.
        layer.putalpha(ImageChops.multiply(layer.getchannel("A"), puppet.getchannel("A")))

    init = Image.new("RGB", (size, size), BACKDROP)
    init.paste(layer, (0, 0), layer)
    return _paste_face(init, skeleton, size, face)


def write_reference_frames(fighter_id, out_dir, states=None, size=DEFAULT_SIZE, limit=None,
                           body_view=VIEW_BODY, clip=INIT_CLIP):
    """One frame's worth of inputs for either reference arm, per selected frame.

    A dict per frame rather than a path, because the two arms need different members of it --
    `reference` the composed init, `ipadapter` the flattened sheet views -- and because the frame's
    face is now part of how it was made: a manifest that cannot say which expression a frame wore is
    a manifest that cannot reproduce it.
    """
    sheet = load_sheet(fighter_id)
    palette = figure.Palette(sheet["palette16"])
    profile = sheet.get("profile", {})
    views = load_views(fighter_id)
    if body_view not in views:
        raise SystemExit("'%s' is not one of %s's views: %s"
                         % (body_view, sheet["id"], ", ".join(sorted(views))))

    poses_dir, init_dir, refs_dir = out_dir / "poses", out_dir / "init", out_dir / "refs"
    for directory in (poses_dir, init_dir, refs_dir):
        directory.mkdir(parents=True, exist_ok=True)

    body_ref = refs_dir / f"{body_view}.png"
    flatten(views[body_view]).save(body_ref)

    written = []
    face_refs = {}
    for state, count, _delay, _box, _continual, pose_name in openpose_render.select_states(states):
        builder = build_fighter.POSES.get(pose_name, build_fighter.POSES["idle"])
        role, expression = expression_for_state(sheet, state)
        face_view = expression["view"]
        if face_view not in face_refs:
            face_refs[face_view] = refs_dir / f"{face_view}.png"
            flatten(views[face_view]).save(face_refs[face_view])
        for index in range(count):
            if limit is not None and len(written) >= limit:
                return written
            skeleton = figure.pose(**builder(index, count, profile))
            pose_path = poses_dir / f"{state}{index:02d}.png"
            init_path = init_dir / f"{state}{index:02d}.png"
            openpose_render.render_pose(skeleton, size).save(pose_path)
            compose_reference_init(skeleton, size, palette, views[body_view],
                                   views[face_view], clip=clip).save(init_path)
            written.append({
                "state": state, "init": init_path, "pose": pose_path,
                "ref_body": body_ref, "ref_face": face_refs[face_view],
            })

    return written


# `reference_view` and `ipadapter` are here because both change what a frame looks like while
# leaving the seed alone, and `expressions` because editing the words of a face panel has to
# re-sample the frames that wear it -- a kept frame would otherwise carry a prompt that no longer
# exists anywhere. `size` is here because resuming a 512px batch under `--size 1024` would reuse
# every frame at the wrong resolution and report the new size in the manifest. `clip` is here
# because it decides whether a limb in a composed init is drawn or left for the sampler: a batch
# resumed under the other setting would be half one thing and half the other. `face_clip` is here for
# the same reason one step smaller -- it trims the pasted panel's hair, which is 0.4 engine units of
# a frame's top row, and a batch is made of two of those as little as of one pose.
SETTINGS_THAT_DECIDE_A_FRAME = ("mode", "checkpoint", "control_net", "denoise",
                                "steps", "cfg", "size", "reference_view", "ipadapter",
                                "clip", "face_panel", "face_clip", "expressions", "seed_base")


def _resume_key(settings):
    """The settings that change what a frame looks like, for `--resume`.

    Two runs may reuse each other's frames only if every one of these agrees.
    `seed_base` is in the list because the seed is the handle for re-rolling a
    single frame: resuming under a new seed would quietly keep the old frame and
    report the new seed, which is a manifest that lies about an image.

    Compared through JSON, because that is what a previous run's settings have
    already been through: a tuple in the live dict is a list in `manifest.json`,
    and `("a", 0.8)` does not equal `["a", 0.8]`. The IP-Adapter arm's model tuple
    never matched, so `--resume` on that arm re-sampled the whole batch while
    reporting nothing unusual -- which is the one thing the reuse path must not do,
    because a fighter is hours of sampling and the reason to resume is that the
    first attempt was interrupted.
    """
    chosen = {key: settings.get(key) for key in SETTINGS_THAT_DECIDE_A_FRAME}
    return json.dumps(chosen, sort_keys=True, default=str)


def _resume_plan(out_dir, settings):
    """frame name -> record, for frames an earlier run already rendered."""
    manifest_path = out_dir / "manifest.json"
    if not manifest_path.is_file():
        return {}
    try:
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if _resume_key(previous.get("settings", {})) != _resume_key(settings):
        return {}
    return {record["frame"]: record for record in previous.get("frames", [])}


def _reusable(frame, already, out_dir, frame_seed):
    """The record for a frame an earlier run already drew, and its path, or (None, path).

    Asked twice per run: once to work out whether there is anything left to draw at all -- and so
    whether the disk preflight is even a question -- and once per frame in the loop. One predicate,
    so a frame that the preflight counts as pending is a frame the loop draws.
    """
    name = frame["pose"].stem
    raw_path = out_dir / "raw" / f"{name}.png"
    kept = already.get(name)
    if (kept is not None and kept.get("seed") == frame_seed
            and kept.get("raw") == str(raw_path.relative_to(out_dir))
            and raw_path.is_file()):
        return kept, raw_path
    return None, raw_path


def load_sheet(fighter_id):
    path = SHEET_DIR / f"{fighter_id}.json"
    if not path.is_file():
        raise SystemExit(f"no design sheet for '{fighter_id}' at {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# The frozen skeleton. `records[..]["pose_sha256"]` pins each frame to the *drawing* of the pose it
# was conditioned on; this pins the batch to the pose table those drawings came from, boxes and all.
POSE_TABLE = REPO_ROOT / "design_sheets" / "poses" / "pose_table.json"
_SKELETON_CACHE = {}


def _skeleton_note(fighter_id):
    """The frozen pose table's fingerprint for this fighter, or why there is not one.

    A batch is only as current as the skeleton it was drawn from: move a pose and the hitboxes move
    while every frame baked from the old skeleton stays as it was. Recording the fingerprint here
    means a batch can be compared against the table it cites, instead of looking identical to a
    fresh one.
    """
    if fighter_id in _SKELETON_CACHE:
        return _SKELETON_CACHE[fighter_id]
    if not POSE_TABLE.is_file():
        note = {"pose_table": None,
                "note": f"no {POSE_TABLE.relative_to(REPO_ROOT)}: run "
                        "tools/pipeline/pose_table.py --write"}
    else:
        entry = json.loads(POSE_TABLE.read_text(encoding="utf-8")).get(fighter_id)
        note = ({"pose_table": entry["fingerprint"]} if entry else
                {"pose_table": None,
                 "note": f"{POSE_TABLE.name} has no entry for {fighter_id}"})
    _SKELETON_CACHE[fighter_id] = note
    return note


def _write_manifest(out_dir, fighter_id, settings, positive, records, started, reused):
    """Write `manifest.json` from the records so far.

    Called after every frame rather than once at the end. The end is exactly where
    it does not get called: two long runs here were killed after fetching their
    final frame and before reaching the single write that was sitting after the
    loop, which left a directory full of images and no record of how any of them
    were made. A few extra kilobytes per frame buys a run that can be resumed with
    its provenance intact no matter where it stops.
    """
    manifest = {
        "fighter": fighter_id,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "seconds": round(time.time() - started, 1),
        "reused": reused,
        "skeleton": _skeleton_note(fighter_id),
        "settings": settings,
        "prompt": {"positive": positive, "negative": NEGATIVE},
        "frames": records,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n",
                                           encoding="utf-8")
    return manifest


def generate(fighter_id, states, out_dir, size=DEFAULT_SIZE, steps=20, cfg=7.0,
             strength=0.9, seed=0, limit=None, host="127.0.0.1", port=8188,
             mode="img2img", denoise=DENOISE, reference_view=VIEW_BODY,
             ref_weight=REFERENCE_WEIGHT, face_weight=FACE_WEIGHT, resume=False,
             clip=INIT_CLIP, face_panel=FACE_PANEL):
    """Write the conditioning images, render each frame, write the manifest.

    Five modes, separated by what is holding the figure still and by where the fighter's identity
    comes from:

    * ``img2img`` -- SD1.5 repainting our own drawing. Framing, backdrop, palette, character and
      pose all come through, because the sampler starts from the drawing and stops early (see
      `DENOISE` for the two numbers that bound this). The default. It is also the only mode whose
      *head* is not left to the drawing: the state's face view from the sheet is pasted on it first
      (`FACE_PANEL`), because the pose is only in the pixels and the face is the one thing a repaint
      of those pixels loses -- see `INIT_CLIP`'s table for the three settings measured.
    * ``canny`` -- the same drawing as the latent *and* a Canny edge control, on SDXL. Same
      guarantees, less of the drawing survives, four times the weights.
    * ``controlnet`` -- SDXL conditioned on the bare skeleton, so the figure is where we said and
      everything else is invented per frame. Kept because it is the measurement that ruled it out,
      and because it is the only mode a pose with no drawing behind it could ever use.
    * ``reference`` -- the design sheet composited onto the skeleton as the latent, redrawn under
      the OpenPose control. Identity as pixels.
    * ``ipadapter`` -- the same sheet read by an IP-Adapter, from an empty latent. Identity as a
      conditioning vector. These two are the arms; see the module docstring for which one won.

    The face is per state in every mode, not only the two arms: a frame's expression comes from
    `build_fighter.STATE_EXPRESSION` through the design sheet's own `expressions` block, so an
    attack is drawn with the attack face and being hit with the hurt face, rather than with one
    sentence about a blank expression written once and used for all 142 frames of a fighter. In
    `img2img` that view is also pasted onto the drawing's head as pixels; in `canny` and
    `controlnet` only its sentence reaches the sampler, which is half of why neither is the default.

    ``resume`` keeps whatever an earlier run left in the same ``out_dir``, as long as the settings
    that decide what a frame looks like have not changed (see `_resume_key`). A fighter is hours of
    sampling, and both long runs here were killed from outside one frame short of the end: that is
    not a reason to sample 142 frames a second time.
    """
    sheet = load_sheet(fighter_id)
    appearance = sheet.get("appearance")
    if not appearance:
        raise SystemExit(
            f"design sheet '{fighter_id}' has no 'appearance' field.\n"
            "The palette says which colours the fighter is; 'appearance' says what\n"
            "it looks like. Without it the generator invents a different person in\n"
            "every frame, which is the one failure a palette cannot repair.")

    shared = f"{appearance}, {STYLE_ANIME}, {STYLE}"
    out_dir = Path(out_dir)
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    settings = {
        "mode": mode,
        "checkpoint": CHECKPOINT_IMG2IMG if mode == "img2img" else CHECKPOINT,
        "control_net": {"img2img": None, "canny": CONTROL_NET_CANNY}.get(
            mode, CONTROL_NET),
        "size": size, "steps": steps, "cfg": cfg,
        "denoise": denoise if mode in ("img2img", "canny", "reference") else None,
        "control_strength": None if mode == "img2img" else strength,
        "canny_thresholds": list(CANNY_THRESHOLDS) if mode == "canny" else None,
        "reference_view": reference_view if mode in ("reference", "ipadapter") else None,
        "clip": clip if mode == "reference" else None,
        "face_panel": face_panel if mode == "img2img" else None,
        "face_clip": FACE_CLIP_TO_HEAD if mode == "img2img" else None,
        "ipadapter": (IPADAPTER_MODEL, CLIP_VISION_MODEL, ref_weight, face_weight)
                     if mode == "ipadapter" else None,
        "expressions": (sheet.get("reference") or {}).get("expressions"),
        "sampler": "euler", "scheduler": "normal", "seed_base": seed,
    }
    already = _resume_plan(out_dir, settings) if resume else {}

    if mode in ("reference", "ipadapter"):
        frames = write_reference_frames(fighter_id, out_dir, states, size, limit,
                                        reference_view, clip)
    else:
        # The init image and the canny mode's control image are the same drawing:
        # one is repainted, the other is traced. Only the repaint gets the face panel --
        # a traced face is a face's worth of edges to hold, and that mode was measured
        # without them.
        paths = (openpose_render.write_poses(fighter_id, out_dir / "poses", states, size)
                 if mode == "controlnet"
                 else write_init_images(fighter_id, out_dir / "init", states, size, limit,
                                        face_panel=face_panel if mode == "img2img" else None))
        if limit is not None:
            paths = paths[:limit]
        frames = [{"state": path.stem.rstrip("0123456789"), "init": path, "pose": path,
                   "ref_body": None, "ref_face": None} for path in paths]
    if not frames:
        raise SystemExit("no frames selected; nothing to generate")

    # The disk preflight is a question about drawing, not about launching: a `--resume` whose frames
    # are all still on disk loads no weights at all, so it is not asked for the room that loading
    # them needs. Measured, because the first version of the IP-Adapter floor refused exactly that
    # case -- a completed batch re-run to check that resume works, at 6.3 GB free.
    pending = [frame for number, frame in enumerate(frames, start=1)
               if _reusable(frame, already, out_dir, seed + number - 1)[0] is None]
    if pending:
        preflight(size, mode)

    client = ComfyClient(host, port)
    print(f"waiting for ComfyUI at {client.base} ...", flush=True)
    client.wait_until_ready()
    if mode == "ipadapter":
        check_ipadapter(client)

    records = []
    reused = 0
    started = time.time()
    for number, frame in enumerate(frames, start=1):
        frame_seed = seed + number - 1
        name = frame["pose"].stem
        kept, raw_path = _reusable(frame, already, out_dir, frame_seed)
        if kept is not None:
            records.append(kept)
            reused += 1
            print(f"  [{number}/{len(frames)}] {name} kept from an earlier run", flush=True)
            continue

        role, expression = expression_for_state(sheet, frame["state"])
        positive = f"{appearance}, {expression['prompt']}, {STYLE_ANIME}, {STYLE}"
        pose_upload = client.fresh(frame["pose"], subfolder=f"cerberus_{mode}")
        if mode == "img2img":
            graph = build_workflow_img2img(pose_upload, positive, frame_seed, size,
                                           steps, cfg, denoise,
                                           prefix=f"cerberus_{fighter_id}")
        elif mode == "canny":
            graph = build_workflow_canny(pose_upload, positive, frame_seed, size,
                                         steps, cfg, strength,
                                         prefix=f"cerberus_{fighter_id}",
                                         denoise=denoise)
        elif mode == "reference":
            graph = build_workflow_reference(
                client.fresh(frame["init"], subfolder=f"cerberus_{mode}"), pose_upload,
                positive, frame_seed, size, steps, cfg, strength, denoise,
                prefix=f"cerberus_{fighter_id}")
        elif mode == "ipadapter":
            graph = build_workflow_ipadapter(
                pose_upload,
                client.fresh(frame["ref_body"], subfolder=f"cerberus_{mode}"),
                client.fresh(frame["ref_face"], subfolder=f"cerberus_{mode}"),
                positive, frame_seed, size, steps, cfg, strength, ref_weight,
                face_weight, prefix=f"cerberus_{fighter_id}")
        else:
            graph = build_workflow(pose_upload, positive, frame_seed, size, steps, cfg,
                                   strength, prefix=f"cerberus_{fighter_id}")
        prompt_id = client.queue(graph)
        print(f"  [{number}/{len(frames)}] {name} {role} seed={frame_seed} "
              f"-> {prompt_id[:8]}", flush=True)
        images = client.wait(prompt_id)
        raw_path.write_bytes(client.fetch(images[0]))

        records.append({
            "frame": name,
            "state": frame["state"],
            "expression": role,
            "positive": positive,
            "seed": frame_seed,
            "pose": str(frame["pose"].relative_to(out_dir)),
            "pose_sha256": _digest(frame["pose"]),
            "raw": str(raw_path.relative_to(out_dir)),
            "prompt_id": prompt_id,
        })
        _write_manifest(out_dir, fighter_id, settings, shared, records, started, reused)

    manifest = _write_manifest(out_dir, fighter_id, settings, shared, records, started, reused)

    print(f"\n{len(records)} raw render(s) in {manifest['seconds']}s -> {raw_dir}"
          + (f" ({reused} reused)" if reused else ""))
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
    parser.add_argument("--mode",
                        choices=("canny", "img2img", "controlnet", "reference",
                                 "ipadapter"),
                        default="img2img",
                        help="what holds the figure: 'img2img' repaints our own "
                             "drawing with SD1.5 and is the mode that measures as "
                             "keeping both pose and character (default); 'canny' "
                             "repaints the same drawing with SDXL while a ControlNet "
                             "pins its edges, for a more painterly result at 4x the "
                             "weights; 'controlnet' conditions SDXL on the bare "
                             "skeleton and holds the pose at the cost of the "
                             "character, which changes every frame; 'reference' puts "
                             "the design sheet's own views in the latent, scaled onto "
                             "the skeleton, under the same OpenPose control; "
                             "'ipadapter' hands the same views to an IP-Adapter "
                             "instead, from an empty latent")
    parser.add_argument("--denoise", type=float, default=DENOISE,
                        help="img2img, canny and reference: how much of the latent "
                             "the sampler may repaint; low holds the pose, high holds "
                             "identity")
    parser.add_argument("--strength", type=float, default=0.9,
                        help="controlnet, reference and ipadapter: 1.0 pins hardest "
                             "to the skeleton")
    parser.add_argument("--ref-view", default=VIEW_BODY,
                        help="the reference arms' body view, by the name the design "
                             "sheet gives it (default %s)" % VIEW_BODY)
    parser.add_argument("--ref-weight", type=float, default=REFERENCE_WEIGHT,
                        help="ipadapter: how hard the body view pushes")
    parser.add_argument("--face-weight", type=float, default=FACE_WEIGHT,
                        help="ipadapter: how hard the state's face view pushes")
    parser.add_argument("--clip", choices=("pose", "none"), default=INIT_CLIP,
                        help="reference: whether the composed init clips the sheet's ink to the "
                             "pose's own silhouette (pose) or pastes the whole standing view "
                             "under the skeleton (none, the default). Both were measured against "
                             "the strike boxes and neither adopts the pose -- see INIT_CLIP, whose "
                             "table is the reason the default is what it is.")
    parser.add_argument("--face-panel", choices=("sheet", "head", "none"), default=FACE_PANEL,
                        help="img2img: what the state's face view from the design sheet contributes "
                             "to the drawing before it is repainted -- the whole panel (sheet), the "
                             "head with its collar cropped off (head, the default), or nothing, "
                             "leaving the face our own drawing gave it (none). The head is the band "
                             "a repaint loses; the collar is drawn for an upright chest. See "
                             "FACE_PANEL and FACE_HEAD_ONLY.")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8188)
    parser.add_argument("--resume", action="store_true",
                        help="keep frames an earlier run already rendered in --out, "
                             "instead of sampling them again; a frame is only kept "
                             "if its settings and seed are unchanged")
    args = parser.parse_args(argv)

    states = None if not args.state else [
        name.strip() for name in args.state.split(",") if name.strip()]

    try:
        generate(args.fighter, states, Path(args.out), args.size, args.steps,
                 args.cfg, args.strength, args.seed, args.limit, args.host, args.port,
                 mode=args.mode, denoise=args.denoise, reference_view=args.ref_view,
                 ref_weight=args.ref_weight, face_weight=args.face_weight,
                 resume=args.resume, clip=args.clip, face_panel=args.face_panel)
    except ComfyError as error:
        print(f"\n{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
