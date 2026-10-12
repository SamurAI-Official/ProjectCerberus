#!/usr/bin/env bash
# build_nrr_macos.sh
# Builds the NRR Godot 4.x GDExtension for macOS and installs it into addons/nrr/.
#
# Why this is a script rather than a committed binary: NRR's own README is explicit that the native
# library is per-platform build output and is not committed, and this project follows that - the
# existing .gitignore already ignores bin/. So the addon is vendored and the one thing a machine has
# to do for itself is build the binding. This is that, end to end: clone, fetch ONNX Runtime,
# configure, build, install, and point the descriptor at what it wrote.
#
# ── Upstream revision: 198dba7 plus patches/nrr ─────────────────────────────────────────────────
# The pinned revision is 198dba7 (recorded in patches/nrr/PINNED_COMMIT, and what apply.sh checks the
# checkout against). Every change this project needs in NRR lives in patches/nrr/*.patch and is
# applied at step 3. The previous pin's rationale turned out to be the wrong explanation of a real
# symptom, and the symptom was misleading enough to be worth keeping on the record:
#
#   The addon could only "render" at 512x512. Every other size failed with "nrr_render: model input
#   'color' resolution 768x432 conflicts with the model's static input shape", and 512x512 returned
#   an image in ~1.9 ms without executing anything. That was read as a binding too old to drive the
#   released model. It was two other things:
#
#     1. NRR's CMake looked for ONNX Runtime in exactly two layouts - Android's
#        lib/<abi>/libonnxruntime.so and Windows' lib/onnxruntime.lib - and in neither the macOS nor
#        the Linux one. On a Mac the ORT-enabled path was unreachable and the build silently produced
#        the *placeholder* inference path, whose configure log says so: "ONNX Runtime: not found
#        (placeholder inference path)". That placeholder reports a fixed 1x3x512x512 input shape,
#        which is where 512 came from, and it has no OrtSession, which is why 512x512 "succeeded"
#        without running a model. patches/nrr/0003 adds the missing arm.
#
#     2. The Godot binding read its result back from the texture it had allocated itself rather than
#        from the one nrr_render hands back in `output.color`. Those are different textures, and the
#        runtime's is sized to the model's output grid - the ratio - so even with a real session
#        linked every frame came back zero-filled, correctly sized and formatted, with an empty
#        error string. patches/nrr/0004 reads size, format and pixels back from what was returned.
#
# Both are fixed now, and the binding reports the model's real (fully dynamic) input shapes and
# returns its real output grid: 768x432 -> 1536x864 with the released 2x model, 834 ms on this
# machine's CPU provider. The 2.5x tier the game needs for 1080p is the *model's* own head rather
# than a runtime setting, which is why training a model is a separate piece of work.
#
# patches/nrr/0005 adds the CoreML execution provider, which is the one accelerator NRR itself could
# not reach on Apple silicon: the provider is inside libonnxruntime in the release packages rather
# than in a separately fetched runtime, and the runtime's provider list did not name it. It is
# opt-in (`NRR_EXECUTION_PROVIDER=coreml`) because it measured *slower* than the CPU provider at
# every size the game uses - see patches/nrr/README.md for the numbers - so nothing about the
# default behaviour changes by building this.
#
# The portability fix (patches/nrr/0001) is still required at every revision seen so far:
# nrr_temporal.h gives TemporalAccumulator::apply() default arguments that default-construct *nested*
# structs - `const PhaseAlignedFrame& phase = PhaseAlignedFrame()` on the old pin, and that plus
# `const DepthProvider& depth = DepthProvider()` on this one. A default argument is read in the class
# body, where those types are still incomplete, so MSVC accepts it and clang rejects it ("default
# member initializer ... needed within definition of enclosing class ... outside of member
# functions"). The patch drops the defaults and adds forwarding overloads whose bodies are member
# functions, where the types are complete.
#
# Usage:  tools/build_nrr_macos.sh [work-dir]
# Needs:  cmake, a C++ toolchain, git, curl, python3.
#
# To finish the job the script cannot do for you: install NRR's released model beside the addon, at
# addons/nrr/models/upscale_msreal_scale.onnx. It is not in the NRR repository (models/ there holds
# two test fixtures, not weights), so it has to come from wherever the release artifacts live. Until
# it is there the game says so - "its release model: not installed" - and upscales pixel-perfect.

set -euo pipefail

# Overridable so a candidate revision can be built and measured before it is pinned
# here:  REVISION=<sha> tools/build_nrr_macos.sh [work-dir]
REVISION="${REVISION:-198dba707eae79470d49c70402a7e1fd129946d7}"
ORT_VERSION="1.30.0"
GODOT_CPP_TAG="10.0.0-stable"
API_VERSION="4.7"
VARIANT="${VARIANT:-template_debug}"
ARCH="$(uname -m)"
case "$ARCH" in arm64|aarch64) ORT_ARCH="arm64" ;; *) ORT_ARCH="x86_64" ;; esac

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="${1:-${TMPDIR:-/tmp}/nrr-build}"
NRR="$WORK/nrr"
GODOT_CPP="$WORK/godot-cpp"
ORT="$WORK/onnxruntime-osx-$ORT_ARCH-$ORT_VERSION"
BIN="$ROOT/addons/nrr/bin/macos/debug"

say() { printf '\n\033[1m[nrr] %s\033[0m\n' "$*"; }

mkdir -p "$WORK"

# ── 1. the two checkouts ─────────────────────────────────────────────────────────────────────────
if [ ! -d "$NRR/.git" ]; then
  say "cloning NRR"
  git clone --quiet https://github.com/samurai-official/nrr "$NRR"
fi
git -C "$NRR" fetch --quiet origin
git -C "$NRR" checkout --quiet "$REVISION"
say "NRR at $(git -C "$NRR" log --oneline -1)"

if [ ! -d "$GODOT_CPP" ]; then
  say "cloning godot-cpp ($GODOT_CPP_TAG)"
  git clone --quiet --depth 1 -b "$GODOT_CPP_TAG" https://github.com/godotengine/godot-cpp "$GODOT_CPP"
fi
# godot-cpp names its dumps by minor version with a hyphen: extension_api-4-7.json.
API_DUMP="extension_api-${API_VERSION//./-}.json"
if [ ! -f "$GODOT_CPP/gdextension/$API_DUMP" ]; then
  echo "godot-cpp has no $API_DUMP; the binding cannot be generated against Godot $API_VERSION" >&2
  exit 1
fi

# ── 2. ONNX Runtime, which the runtime links against ─────────────────────────────────────────────
if [ ! -f "$ORT/include/onnxruntime_c_api.h" ]; then
  say "fetching ONNX Runtime $ORT_VERSION for macOS $ORT_ARCH"
  mkdir -p "$NRR/third_party"
  curl -sSL -o "$WORK/ort.tgz" \
    "https://github.com/microsoft/onnxruntime/releases/download/v$ORT_VERSION/onnxruntime-osx-$ORT_ARCH-$ORT_VERSION.tgz"
  tar xzf "$WORK/ort.tgz" -C "$NRR/third_party"
  rm -f "$WORK/ort.tgz"
  if [ ! -d "$ORT" ] && [ -d "$NRR/third_party/onnxruntime-osx-$ORT_ARCH-$ORT_VERSION" ]; then
    mv "$NRR/third_party/onnxruntime-osx-$ORT_ARCH-$ORT_VERSION" "$ORT"
  fi
fi
[ -f "$ORT/include/onnxruntime_c_api.h" ] || { echo "no ONNX Runtime SDK at $ORT" >&2; exit 1; }

# ── 3. the portability fix, if this revision has the defect ──────────────────────────────────────
say "checking the revision, then applying patches/nrr"
python3 - "$NRR" <<'PY'
import pathlib, sys
nrr = pathlib.Path(sys.argv[1])
backend = (nrr / "runtime" / "backend_cpu.cpp").read_text()
symbols = ["compute_history_trust_mask_from_textures", "warp_input_history_to_nchw"]
called = [s for s in symbols if s in backend]
sources = [p for p in nrr.rglob("*")
           if p.suffix in (".cpp", ".h", ".hpp") and p.name not in ("backend_cpu.cpp", "accel_kernel.cpp")]
undefined = [s for s in called if not any(s in p.read_text(errors="ignore") for p in sources)]
if undefined:
    sys.exit("this revision calls %s and defines %s nowhere: it is the broken one, see this "
             "script's header for the revision to pin instead" % (", ".join(undefined), "them/them"))


PY

# ── 3b. this project's patches ───────────────────────────────────────────────────────────────────
# Applied by the series rather than by hand here, so the build is reproducible from "pinned commit
# + patches/nrr" like the engine is from "pinned commit + patches/openfight". Each patch carries
# the reason it exists; see patches/nrr/README.md for the compiler output behind it.
bash "$ROOT/patches/nrr/apply.sh" "$NRR"

# ── 4. configure and build ───────────────────────────────────────────────────────────────────────
say "configuring"
cmake -S "$NRR" -B "$NRR/build-godot" \
  -DNRR_BUILD_GODOT_PLUGIN=ON -DNRR_GODOT_CPP_PATH="$GODOT_CPP" \
  -DNRR_GODOT_API_VERSION="$API_VERSION" -DGODOTCPP_TARGET="$VARIANT" \
  -DCMAKE_BUILD_TYPE=Release -DNRR_BUILD_TESTS=OFF \
  -DNRR_ONNXRUNTIME_ROOT="$ORT" -DNRR_ONNXRUNTIME_FLAVOR=cpu \
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
  -DCMAKE_INSTALL_RPATH=@loader_path -DCMAKE_BUILD_WITH_INSTALL_RPATH=ON \
  > "$WORK/configure.log" 2>&1 || { tail -20 "$WORK/configure.log"; exit 1; }

say "building nrr_godot"
cmake --build "$NRR/build-godot" --target nrr_godot -j "$(sysctl -n hw.ncpu)" \
  > "$WORK/build.log" 2>&1 || { grep -iE 'error' "$WORK/build.log" | head -10; exit 1; }

BUILT="$(find "$NRR/build-godot" -name 'libnrr_godot.*.dylib' | head -1)"
[ -n "$BUILT" ] || { echo "the build produced no library" >&2; exit 1; }

# ── 5. install, beside the ONNX Runtime it needs ─────────────────────────────────────────────────
LIB="$(basename "$BUILT")"
say "installing $LIB into addons/nrr/bin/macos/debug"
mkdir -p "$BIN"
cp "$BUILT" "$BIN/"
# One real library and its two names, rather than the same 43 MB three times over: NRR asks for
# libonnxruntime, and only the loader's name for it matters.
cp "$ORT/lib/libonnxruntime.$ORT_VERSION.dylib" "$BIN/"
ln -sf "libonnxruntime.$ORT_VERSION.dylib" "$BIN/libonnxruntime.dylib"
ln -sf "libonnxruntime.$ORT_VERSION.dylib" "$BIN/libonnxruntime.1.dylib"

# ── 6. the descriptor, which upstream's README says to adjust on macOS ───────────────────────────
if grep -q 'framework/libnrr_godot' "$ROOT/addons/nrr/nrr.gdextension"; then
  say "pointing nrr.gdextension's macOS entries at the flat library this build writes"
  python3 - "$ROOT/addons/nrr/nrr.gdextension" "$LIB" <<'PY'
import re, sys, pathlib
path, lib = pathlib.Path(sys.argv[1]), sys.argv[2]
text = path.read_text()
text = re.sub(r'macos\.debug = ".*"',
              'macos.debug = "res://addons/nrr/bin/macos/debug/%s"' % lib, text)
text = re.sub(r'macos\.release = ".*"',
              'macos.release = "res://addons/nrr/bin/macos/release/%s"' % lib.replace("debug", "release"), text)
path.write_text(text)
print("  macos.debug ->", lib)
PY
fi

# ── 7. the released model, which is what makes the binding an upscaler ───────────────────────────
# It is published on Hugging Face rather than in the NRR repository (the model card says why: models/
# there is working state), and the addon looks for it beside itself, so this is where it goes.
MODEL_DIR="$ROOT/addons/nrr/models"
MODEL="upscale_msreal_scale.onnx"
MODEL_URL="https://huggingface.co/SamurAI-Official/NRR/resolve/main/$MODEL"
if [ ! -f "$MODEL_DIR/$MODEL" ]; then
  say "fetching the released model from Hugging Face"
  mkdir -p "$MODEL_DIR"
  curl -sSL -o "$MODEL_DIR/$MODEL" "$MODEL_URL" || {
    echo "could not fetch $MODEL_URL - NRR will load and pass frames through until it is there" >&2
    rm -f "$MODEL_DIR/$MODEL"
  }
fi
if [ -f "$MODEL_DIR/$MODEL" ]; then
  echo "  model:  $MODEL   ($(wc -c < "$MODEL_DIR/$MODEL" | tr -d ' ') bytes)"
else
  echo "  model:  not installed - the game upscales pixel-perfect and says so"
fi

say "done"
echo "  built:  $LIB   ($(du -h "$BIN/$LIB" | cut -f1))"
echo "  into:   $BIN"
echo
echo "Open the project in Godot and the addon will load. The title screen and the options screen both"
echo "say which of the three pieces is in use: the binding, the model, and a rendered frame to upscale -"
echo "a headless run has the first two and not the third."
