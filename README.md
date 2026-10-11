# Project Cerberus

A 2D fighting game in **Godot 4.7**, built on the
[openfight](https://github.com/nonameentername/openfight) fighting-game engine
(GDExtension, LGPL-3.0), with
[NRR](https://github.com/SamurAI-Official/NRR) planned as an optional upscaling
pass.

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
| ⏳ M3 | art + YAML pipeline, the two vertical-slice fighters |
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
vendor/openfight/        pinned submodule + godot-cpp
patches/openfight/       our patch series + apply.sh
game/
  main.gd/.tscn          entry point: checks the world is playable, hands off to GameState
  autoload/              GameState (flow + match config + result), UserSettings, InputBindings
  ui/menu_screen.gd      shared menu chrome; screens are scripts so they are testable
  screens/               title, char_select, stage_select, match, results, options, boot
  match/                 MatchController, HealthBar, Announcer, PauseMenu
data/
  fighters/manifest.json roster (name, detail, yaml, moves)
  stages/manifest.json   stages (name, detail, background)
  ryu/, background.png   the vendored engine fixture
tools/build/             build_openfight.sh
tools/validate/          validate_manifest.py -- roster + YAML + frame files resolve
tools/verify/            run_all.sh + the verification scenes
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
