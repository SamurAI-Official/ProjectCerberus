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

## Status: M0 complete

The engine builds on macOS arm64 and runs. What is and is not done:

| | |
|---|---|
| ✅ M0 | openfight GDExtension builds natively and loads in Godot 4.7.2; class registers; 600-frame headless smoke test passes |
| ⏳ M1 | fork in health / damage / rounds / signals (the engine has none — see below) |
| ⏳ M2 | title / character select / match / results shell, gamepad input |
| ⏳ M3 | art + YAML pipeline, the two vertical-slice fighters |
| ⏳ M4 | vertical slice lock |

## Why this project has to patch its engine

`OpenFightNode` exposes exactly four string paths, two methods, and **zero
signals**. The C++ `Player` class has no health field. Health tracking, rounds,
a title screen, character select, and audio are all listed as *unchecked* in
openfight's own `ROADMAP.md`. So the plan of record is:

* vendor openfight as a pinned submodule and never edit it in place,
* carry our changes as a **patch series** in `patches/openfight/` (the same
  convention NRR uses for its Godot fork), and
* keep all game logic in GDScript.

Working in patches keeps us rebasable on upstream and keeps our LGPL-3.0
obligations simple: dynamic linking through the GDExtension, with the modified
engine source published right here.

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
game/                    GDScript: screens, match, autoloads
data/                    openfight YAML + sprite frames (res://data)
tools/build/             build_openfight.sh
tools/verify/            headless smoke tests
docs/pipeline/           sprite spec, findings
docs/lore/               canon reference
```

`data/` sits at the project root on purpose: every frame path inside the YAML
is written as `data/<fighter>/<anim>NN.png` and resolved through
`ResourceLoader` with a `res://` fallback, so the directory name is part of the
data contract.

## Building

```sh
git submodule update --init --recursive
brew install yaml-cpp        # the extension links exactly one library
pip3 install --user scons
./tools/build/build_openfight.sh
```

Then verify:

```sh
/Applications/Godot.app/Contents/MacOS/Godot --headless --path . --import
/Applications/Godot.app/Contents/MacOS/Godot --headless --path . res://tools/verify/m0_smoke.tscn
```

and play:

```sh
/Applications/Godot.app/Contents/MacOS/Godot --path . res://game/screens/match/match.tscn
```

Controls are the upstream layout. P1: `S`/`Z`/`X`/`C` to move, `J`/`K`/`L` and
`M`/`,`/`.` for attacks. P2: arrows and the numeric keypad. Gamepad bindings
arrive in M2.

### Known build caveat

Homebrew ships `yaml-cpp` as a dylib with an absolute install name, so the
framework built by `tools/build/build_openfight.sh` only loads on a machine
with that keg. A distributable needs a static `yaml-cpp`
(`-DBUILD_SHARED_LIBS=OFF`). This is recorded in the script, not hidden in it.

## Licence notes

openfight is **LGPL-3.0** (dynamic-linked here; our patches are published in
`patches/`). NRR is MIT. Godot is MIT.
