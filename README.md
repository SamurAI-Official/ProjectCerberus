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

All nine scenes pass:

```
  m0_smoke      PASS      m0_render     PASS
  m1_match      PASS      m2_render     PASS
  m2_hud        PASS      m3_boxes      PASS
  m2_flow       PASS      video_options PASS
  m3_roster     PASS
```

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

NRR is vendored at `addons/nrr` with its native binding built for macOS arm64, and
it genuinely loads: `video_options` reports

```
  nrr vendored=true binding=true model=true
  nrr backend    : CPU
  nrr model      : res://addons/nrr/models/upscale_msreal_scale.onnx
  nrr last error : 'nrr_render: model input 'color' resolution 768x432 conflicts
                    with the model's static input shape'
  nrr frames out : 0
```

**It is not upscaling, and the game says so rather than pretending.** The
published model takes exactly 512x512 — `tools/verify/nrr_probe.tscn` asks it
size by size, and of twelve candidate sizes only that one is accepted, returning
the same size it was given. Our canvas is 768x432, so every frame is declined.
The model card describes something different ("dynamic H/W", "2x the input"), and
where a card and an artifact disagree the artifact is what ran.

That is why the options screen prints the runtime's own words and not a summary of
the file listing: *"NRR is running but declining every frame: nrr_render: model
input 'color' resolution 768x432 conflicts with the model's static input shape."*
An upscaler that is selected, installed and silently not running is
indistinguishable from a working one unless somebody asks it, so `video_options`
asks it and asserts that the screen agrees with the answer.

To make it actually upscale, either the game renders at 512x512 — which throws
away the 1:1 pixel mapping the art was built for — or NRR publishes a model whose
input is not square. Neither is a configuration change, so the shipped default
stays NRR and the shipped behaviour is an honest pixel-perfect picture.


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
tools/validate/          validate_manifest.py -- roster + YAML + frame files resolve
tools/verify/            run_all.sh + the verification scenes. m3_boxes (the box
                         overlay) and video_options (the render path) need a
                         window; nrr_probe is a tool, not a check -- it reports
                         which frame sizes the released NRR model accepts
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
