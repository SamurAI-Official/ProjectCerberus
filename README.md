# Project Cerberus

A 2D fighting game in **Godot 4.7**, built on the
[openfight](https://github.com/nonameentername/openfight) fighting-game engine
(GDExtension, LGPL-3.0), with
[NRR](https://github.com/SamurAI-Official/NRR) vendored as the default upscaler —
installed, loading, running, and declining every frame for a reason it states out
loud. See [The render path](#the-render-path) below.

The roster and stages come from the *ZERO's Universe* lore bible — five
properties that share one anthology: **Conquest of Verelin / Diaporia** (high
fantasy), **New Aurora 3187** (cyberpunk), **FEaster in Franklin** (slasher
horror), **Us vs. The Clowns** (1992 biker), and **Yokai Hon'nō Academy**
(shonen). The first vertical slice is **Tsu Ibano vs. Fei Young** in the
**Gijutsu Gym**.

## Status: M0–M1 complete

| | |
|---|---|
| ✅ M0 | openfight GDExtension builds natively on macOS arm64 and loads in Godot 4.7.2; class registers; 600-frame headless smoke test; Metal render test |
| ✅ M1 | health, damage, best-of-three rounds and 4 Godot signals patched into the engine — a full match runs headless and passes its assertions |
| ✅ M2 | full menu flow — title, fighter select, stage select, match, results, options and an in-match pause menu; gamepad bindings; settings persisted to disk. Walked end to end headless. |
| ✅ M3 | art + YAML pipeline; the two vertical-slice fighters are playable end to end — every state reachable, every hitbox connecting |
| ⏳ M3.5 | art fidelity: alpha, 1:1 pixels, 16-colour palettes, AI-generated frames |
| ⏳ M4 | vertical slice lock |

### M2, verified

`tools/verify/m2_flow.tscn` drives the whole flow the way the UI does and
asserts on where it lands:

```
  roster: 1 entr(ies), first is 'RYU'
  stages: 1 entr(ies), first is 'TRAINING ALLEY'
  gamepad bindings present on all 12 sampled actions
  InputBindings is idempotent (second run added 0 events)
  settings round-trip through user://settings.cfg
  flow reached the match: title -> char select x2 -> stage select -> match
  match reported winner 0
  last_result agrees with the signal: winner 0
  round wins total 2: [2, 0]
  results screen heading: 'PLAYER 1 WINS'
  rematch re-entered the match
PASS: full menu flow with no dead ends
```

The match shell itself is covered by `m2_hud.tscn`:

```
  round labels  : ["ROUND 1", "ROUND 2"]
  announcements : ["ROUND 1", "FIGHT!", "K.O.", "ROUND 2", "PLAYER 1 WINS"]
  bar target min: p1=100 p2=0
  result label  : 'PLAYER 1 WINS'
```

### M3, verified

`tools/verify/m3_roster.tscn` loads the real match with Tsu Ibano against Fei
Young and forces a fight to a decision — the pipeline emitting plausible PNGs is
not the claim, the claim is that a fighter built from a design sheet is
*playable*.

```
  matchup: TSU IBANO vs FEI YOUNG in GIJUTSU GYM
=== M3 roster test summary ===
  elapsed        : 19.7s (1174 frames)
  hits           : 30 (210 damage)
  hit strengths  : { "HIT_M": 30 }
  defender states: ["hurt_mid"]
  min health     : p1=100 p2=0
  winner         : 0
PASS: the generated fighters are playable end to end
```

The hit strength is the interesting line. A light punch reaches `1punch`, which
carries `HIT_M`, and the defender's own state machine turns that into `hurt_mid` —
so the assertion pins the whole chain `LP -> 1punch -> HIT_M -> hurt_mid` rather
than merely noticing that something landed.

`tools/verify/m3_boxes.tscn` is the check that fails when it stops being true. It
walks player one in and screenshots the engine's own box overlay, which the
generated YAML switches on with `show_hitbox`. A hitbox that is in the wrong place
leaves everything else looking healthy — every frame loads, every state is
reachable, the round timer runs — so the only symptom is an absence, and a
screenshot of where the engine *tested* is worth more than any amount of reading
where it should have:

```
=== M3 box overlay check ===
  hits     : 15 (105 damage)
PASS: hitboxes and hurtboxes connect in the engine
```

All ten scenes pass:

```
  m0_smoke      PASS      m0_render     PASS
  m1_match      PASS      m2_render     PASS
  m2_hud        PASS      m3_boxes      PASS
  m2_flow       PASS      video_options PASS
  m3_roster     PASS
  walls         PASS
```

### Movesets

Six normals — light, medium and heavy for each limb — two specials, and a chain
per limb.

| | LP | MP | HP | LK | MK | HK |
|---|---|---|---|---|---|---|
| state | `1punch` | `2punch` | `3punch` | `1kick` | `2kick` | `3kick` |
| lands on | hand | hand | hand | **foot** | **foot** | **foot** |
| world y | 20–26 | 21–27 | 21–28 | **−1–5** | **10–17** | **14–22** |
| strength | HIT_M | HIT_M | HIT_H | **HIT_L** | HIT_M | KNOCK_DOWN |

Damage follows the strength, out of the engine's own table (`actions.cpp`): 4 / 7 /
11 / 10. The kicks come off `foot_far` and the punches off `hand_far`, so a move
named for a leg reaches with a leg. Every strike used to be `_strike`, which
animates the arm and leaves `lift` — the only parameter that moves a leg — at 0
for the state called `kick`: the move named for a leg reached out with an arm, and
the hitbox was a fist the game called a foot. The three kicks are a shin kick, a
hip-height kick and a chest-height kick, which is what those hip and knee angles
actually produce rather than what they were named.

**Combos** are the engine's own `combo: true`: while the current animation is a
combo, a command only takes effect if the opponent is hurt. The chain is therefore
confirmed by the hit rather than by a timer — `LP → MP → HP` and `LK → MK → HK`,
with the heavies as enders that cannot themselves be cancelled out of, because a
chain with no ender is not a chain. A whiffed jab plays out and returns to idle
like any other move.

**Specials** are two off one motion, which is the shape the fixture already uses —
its own `QCF_LP` and `QCF_HP` are the same `F,~D` prefix with the punch button
choosing: `QCF+HP` is the field (`KNOCK_DOWN`), `QCF+LP` a lighter, faster version
of it (`HIT_M`).

`tools/strike_strip.py` composes every strike on the frame its hitbox is live, so
what can be checked by eye is what the game will actually test.

### The pushbox has no answer for a wall

The engine's pushbox is two velocities — the mover is shoved back half its speed,
the opponent twice it. That is fine while the opponent has somewhere to be shoved
to. A fighter clamped against a wall does not, so the mover walks into the space it
is standing in: measured with walls and nothing else changed, p1 reached 107.83
against p2's 108.00, fully overlapped, after which its own punch began 8.7 units
*past* the opponent and the fight never connected again.

Patch `0004` resolves the remainder of the separation in steps — and only when the
opponent is at a wall, which is the case the shove cannot handle. Running it
always also separates a free opponent, and that is not an improvement: the
fixture's own match test went from 20 hits to 6 and stopped reaching a decision,
because two fighters that never touch cannot shove each other across the stage
either. The shove is the engine's design; the patch repairs the one situation it
has no answer for rather than replacing it.

### Stage walls

A fighting game has edges; openfight had none. Nothing anywhere in it bounded a
fighter's x, so both of them walked off the stage and kept going until the round
ended — visible as a fighter strolling past the opponent and out of the picture.

Patch `0003` clamps x inside `Player::moveXpos`, which is the single function
every position change goes through — walking, the pushbox, and the pushbox's shove
of the opponent — so there is one edge rather than three. The bounds are stage
data (`bounds` in the stage manifest) rather than constants, because the right
answer depends on how much of the world is on screen, and this engine's camera has
never moved: `Camera` is constructed, read by the renderer, and never written. The
backgrounds are 200 units wide against a view of about 130, so they already
overflow it — a follow camera is what turns these bounds from "the screen's edges"
back into "the stage's".

The patch also exposes `get_player_x`, without which none of this is checkable:
the node published no position at all, which is exactly why "walked off the stage"
went unnoticed. `walls` drives a fighter into each edge and asserts the pair
stops there:

```
  left wall  : furthest   -10.00 (edge   -10.0)   p1  -10.00  p2   70.00
  right wall : furthest   108.00 (edge   108.0)   p1  100.84  p2  108.00
PASS: the stage has edges and the fighters stop at them
```

p1 stops at the left wall exactly. On the right it stops at 100.8 rather than 108
because walking right drives p1 into p2, and the pushbox carries p2 to the wall
and pins it there — which is the correct interaction, and why the check asserts
the *pair* reaches the edge rather than one fighter.

### The render path

The game draws at 768x432 and enlarges that to whatever the window is, and *how*
it enlarges is a setting: **NRR** (neural, the default), **Nearest**
(pixel-perfect) or **Smooth** (interpolated). The options screen offers all three
and shows which one is actually in force.

NRR is vendored at `addons/nrr`; its native binding is built for macOS arm64 from NRR
`198dba7` plus the four patches in `patches/nrr/`, and it loads, runs and upscales.
Measured headless on this machine, CPU execution provider, release build:

```
  nrr_probe:
    384x216  ->  768x432     200 ms    half-resolution canvas -> canvas
    768x432  -> 1536x864     834 ms    canvas -> the 2x model's grid
    1024x576 -> 2048x1152   1440 ms
```

1920x1080 needs a 2.5x head, because 2.5 x 768 = 1920 exactly and the ratio belongs to
the model: nothing outside the graph resamples the frame, so a tier is chosen by
installing a model rather than by setting one.

**The reason this section used to give for NRR declining every frame was wrong, and the
correction is worth more than the original entry.** It said 512x512 was the runtime's
limit and blamed a pinned revision older than the released model. The real cause was that
the macOS build contained no ONNX Runtime at all: NRR's CMake looked for the Android and
Windows layouts and neither of the Unix ones, so `NRR_HAVE_ONNXRUNTIME` stayed off, the
configure log said `ONNX Runtime: not found (placeholder inference path)`, and the
runtime's *placeholder* path -- which reports a fixed 1x3x512x512 input shape and has no
session to execute -- was the only thing answering. 512x512 was the one size it agreed
to run, in 1.9 ms, without a model. Linking ORT exposed a second defect behind it: the
Godot binding read its result back from the texture it had allocated itself rather than
the one `nrr_render` returns, which is sized to the model's output grid, so every frame
came back correctly sized, correctly formatted, entirely zero, with an empty error
string. Both are now `patches/nrr/0003` and `patches/nrr/0004`, and
`tools/verify/nrr_output_check.gd` is the tool that made the empty frame visible: a
checkerboard in, both frames out, so a crop, a resample, a same-size refinement and an
empty frame are four different pictures.

**Nor would installing one help, which is the finding worth having.** Scored against
our own art -- a frame composed at the game's own 6 px/unit, downscaled, then brought
back up against the frame itself as ground truth -- the released 2x model loses to
bicubic by 3.8-4.6 dB at every tier, *including* the 128-to-256 tier it was trained at,
and its error map is dense inside flat regions rather than at edges: it invents texture
on flat 16-colour art. The 2.5x model is the one that matches 1080p from this canvas
(2.5x of 768x432 is exactly 1920x1080, which is why the Hub publishes it at all), and
it lands level with bicubic while needing a depth plane this renderer has no source
for. Both are trained on 3D-rendered Godot captures, and a flat 2D canvas has nothing
for them to reconstruct.

That is why the options screen prints the runtime's own words rather than a summary of the
file listing. An upscaler that is selected, installed and silently not running is
indistinguishable from a working one unless somebody asks it, so `video_options` asks it
and asserts that the screen agrees with the answer -- and a pass that returns a frame of
the wrong size, or an empty one, is exactly what that assertion is for.

**So NRR runs now, and the shipped default still does not use it, for a measured reason:
834 ms against a 16.6 ms frame budget.** A 768x432 -> 1536x864 pass costs 0.83 s on this
machine's CPU provider and roughly 1.4-2 s for a 1080p output. That is a quality pass
rather than a frame-time one, and the GPU route is a build away rather than a setting:
NRR's provider preference offers CUDA and CPU (`NRR_EXECUTION_PROVIDER`), and ONNX
Runtime's CoreML provider is present on this machine but nothing in the binding selects
it. What would change the verdict, given the model finding above, is a model trained on
this art -- the trainer, the pairing generator (`gen_training_pairs.py --ratio 2.5`) and
the gates are all in the NRR tree and now reachable from here, and the 2.5x model that
came out of them is 91 k parameters. Until then the shipped default stays NRR selected,
with the honest pixel-perfect picture behind it.


### Open bug: a round restart can stop the fight connecting

Reproduce with `m3_boxes.tscn` at `PUNCH_PERIOD_FRAMES = 24`: round one ends by KO
as normal, and round two then runs its full 99-second timer with the fighters
adjacent, animating, and no hitbox ever drawn in front of them. It is not a
geometry problem — the same match completes when the punch cadence is 14 frames,
and enlarging the hitbox and hurtbox both make it land again. It is recorded in
`tools/verify/m2_flow.gd` next to the cadence it constrains, because the symptom
imitates a box bug closely enough to be worth a warning.


### M1, verified

```
round 1 started (p1=100 p2=100 hp)
first hit: attacker=0 defender=1 damage=11 blocked=false strength=HIT_H state=hurt_high -> p2 health=89
round ended: winner=0 time_over=false wins=(1,0) health=(100,0)
round 2 started (p1=100 p2=100 hp)
round ended: winner=0 time_over=false wins=(2,0) health=(100,0)
match ended: winner=0 after 20 hits
PASS: hits, damage, round rotation and match end all behaved
```

20 hits × 11 damage = 220 total: 200 to KO two rounds plus 20 overkill, and the
attacker finishes untouched because it was the only one acting. Reproduce with:

```sh
/Applications/Godot.app/Contents/MacOS/Godot --headless --path . res://tools/verify/m1_match.tscn
```


## Why this project has to patch its engine

`OpenFightNode` exposes exactly four string paths, two methods, and **zero
signals**. The C++ `Player` class has no health field. Health tracking, rounds,
a title screen, character select, and audio are all listed as *unchecked* in
openfight's own `ROADMAP.md`. So the plan of record is:

* vendor openfight as a pinned submodule and never edit it in place,
* carry our changes as a **patch series** in `patches/openfight/` (the same
  convention NRR uses for its Godot fork), and
* keep all game logic in GDScript.

Patch `0001` is 11 files and 658 lines; it adds health, damage resolution,
best-of-three rounds and four signals, and it is verified to apply cleanly onto
a pristine submodule checkout and to reproduce the tree byte-for-byte. Full
notes, including why damage lives in `CollisionAction::doAction()` and why
blocking is a state-name prefix rather than a flag, are in
[`patches/openfight/README.md`](patches/openfight/README.md).

Keeping the engine in patches rather than a fork keeps us rebasable on upstream
and keeps our LGPL-3.0 obligations simple: dynamic linking through the
GDExtension, with the modified engine source published right here.


### A false lead, recorded on purpose

My first read of `GodotRenderBackend::loadTexture()` suggested the `masking`
parameter was stubbed out (`(void)masking;`) while `Animation::addFrame()` takes
the mask branch for every frame — which would have meant every fighter rendering
inside an opaque black rectangle. A render test disproved it: the `if (masking)`
block is fully implemented and keys black to alpha 0, so compositing is correct.

The correction is kept in [`docs/pipeline/sprite-spec.md`](docs/pipeline/sprite-spec.md)
because it also surfaced three things that *do* differ from the SDL build —
the blend mode (SDL is additive, Godot is a flat alpha blend), hard-keyed alpha
that destroys partial transparency, and the sprite texture being uploaded but
never drawn. Those shape the art pipeline, so they are worth having on record.


## Layout

```
project.godot            Godot 4.7 host; input map names are load-bearing
addons/openfight/        built GDExtension (bin/ is gitignored)
addons/nrr/              the NRR upscaler addon, vendored; bin/ is built, not
                         committed -- tools/build_nrr_macos.sh builds it
vendor/openfight/        pinned submodule + godot-cpp
patches/openfight/       our patch series + apply.sh
game/
  main.gd/.tscn          entry point: checks the world is playable, hands off to GameState
  autoload/              GameState (flow + match config + result), UserSettings, InputBindings
  ui/menu_screen.gd      shared menu chrome; screens are scripts so they are testable
  ui/upscaler.gd         NRR / nearest / smooth, and what this machine can do
  ui/fps_counter.gd      the corner frame rate, off by default
  screens/               title, char_select, stage_select, match, results, options, boot
  match/                 MatchController, HealthBar, Announcer, PauseMenu
data/
  fighters/manifest.json roster (name, detail, yaml, moves)
  stages/manifest.json   stages (name, detail, background)
  ryu/, background.png   the vendored engine fixture
tools/build/             build_openfight.sh, build_nrr_macos.sh
tools/pipeline/          build_fighter.py + figure.py -- draws every frame of every
                         state from its design sheet, then writes the character YAML
                         and moves.yml beside them. build_stage.py draws a stage
                         background, contact_sheet.py lays a whole fighter out in
                         one image, inspect_character.py reads a YAML's geometry back
tools/ai/                the art pipeline. ref_palette.py measures a fighter's sixteen
                         colours off the reference sheet they were drawn from;
                         gen_frames.py renders frames through ComfyUI; to_sprite.py
                         quantises and registers a render into a game frame and
                         reports what it had to do; frame_fidelity.py says whether a
                         generated frame still occupies the drawing its hitboxes were
                         measured from; identity_check.py says whether it is still the
                         same character, band by band, and names which cut it banded
                         them with; openpose_render.py, comfy_client.py;
                         sheet_views.py crops the named views out of a reference
                         sheet: --detect proposes boxes from the drawing, --qc draws
                         them so the proposal can be checked, --write records them in
                         the design sheet beside reference.samples, and --extract
                         writes them masked, because the conditioning stages want one
                         view at a time rather than a page of grid paper
tools/strike_strip.py    every strike, on the frame its hitbox is live, in L/M/H order
tools/measure_world.py   reads the world->screen mapping back off a debug capture
tools/nrr_model_report.py
                         runs the released NRR models through ONNX Runtime: what the
                         two graphs declare, which tier each serves from this canvas,
                         and how each scores against our own art -- the measurement
                         "The render path" is written from. Downloads the 2.5x model
                         into build/nrr/models and writes its evidence sheets to
                         build/nrr
tools/validate/          validate_manifest.py -- roster + YAML + frame files resolve
tools/verify/            run_all.sh + the verification scenes. m3_boxes (the box
                         overlay) and video_options (the render path) need a
                         window; nrr_probe and nrr_output_check are tools, not
                         checks -- the first reports which sizes the vendored binding
                         accepts and what it returns for each, which is not the
                         model's own limit (tools/nrr_model_report.py measures the
                         artifact); the second pushes a checkerboard through the pass
                         and writes both frames, which is what told a crop, a resample
                         and an empty frame apart when the binding returned one
docs/pipeline/           sprite spec, findings
docs/lore/               canon reference
```

`data/` sits at the project root on purpose: every frame path inside the YAML
is written as `data/<fighter>/<anim>NN.png` and resolved through
`ResourceLoader` with a `res://` fallback, so the directory name is part of the
data contract.

The roster and stage manifests are hand-authored rather than generated from the
directory tree, because a generator cannot know a fighter's display name, its
detail line, or which universe it belongs to. `tools/validate/validate_manifest.py`
is what keeps them honest — it resolves every `res://` path, rejects duplicate
ids, and checks that each character YAML declares a `start` state and references
no missing frame files.

### Handing generated art to the build

`data/` is filled by `build_fighter.py` (the puppet, drawn from the skeleton) or by
generated frames, which are installed rather than drawn. Three steps, and each is a
check on the one before:

```sh
python3 tools/ai/gen_frames.py tsu_ibano --mode img2img --out build/ai/tsu_ibano
python3 tools/ai/to_sprite.py tsu_ibano --raw build/ai/tsu_ibano/raw \
        --bound build/ai/tsu_ibano/init --out data/tsu_ibano
./tools/verify/run_all.sh
```

`--bound` is the run's own `init/` directory, and it is the step that decides whether
the art fits the game's frame: a repaint may repaint the pose, it may not extend it.
Without it the model's hair reaches the top of the sprite canvas on about a third of
the attack frames and the texture cuts it flat — `python3 build/sprite_check.py
data/tsu_ibano` counts those frames, and reads zero with `--bound` (the run prints how
many pixels it cleared, so a bound doing real work is visible rather than frictionless).

The AI-side gates are the same three, run against the run directory instead of the
game's, and they are what to look at before installing: `identity_check.py` (is it the
same character), `frame_fidelity.py` (is it the same pose) and
`tools/validate/validate_reach.py` (does the art still reach the box the skeleton
derived). Installing needs no staging step of its own because `validate_manifest.py`
and `run_all.sh` cover the swap; what it does need is all of a fighter's states or none
of them, since a partial install is two different hands in one animation.

## Building

```sh
git submodule update --init --recursive
brew install yaml-cpp        # the extension links exactly one library
pip3 install --user scons

./patches/openfight/apply.sh       # patch the engine (idempotent)
./tools/build/build_openfight.sh   # build + install addons/openfight/
```

Then verify everything:

```sh
./tools/verify/run_all.sh              # validator + all six scenes
GODOT_HEADLESS_ONLY=1 ./tools/verify/run_all.sh   # skip the two that need a GPU
```

and play:

```sh
/Applications/Godot.app/Contents/MacOS/Godot --path .        # title screen
```

Controls are the upstream layout. P1: `S`/`Z`/`X`/`C` to move, `J`/`K`/`L` and
`M`/`,`/`.` for light/medium/heavy punch and kick. P2: arrows and the numeric
keypad. Gamepads: P1 uses pad 1, P2 uses pad 2; face buttons are light and
medium, shoulders are heavy. `ESC` pauses a match.

### Known build caveat

Homebrew ships `yaml-cpp` as a dylib with an absolute install name, so the
framework built by `tools/build/build_openfight.sh` only loads on a machine
with that keg. A distributable needs a static `yaml-cpp`
(`-DBUILD_SHARED_LIBS=OFF`). This is recorded in the script, not hidden in it.

## Licence notes

openfight is **LGPL-3.0** (dynamic-linked here; our patches are published in
`patches/`). NRR is MIT. Godot is MIT.
