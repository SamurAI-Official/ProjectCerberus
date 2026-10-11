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
# ── Upstream revision: a0443a2, pinned on purpose ────────────────────────────────────────────────
# The newest commit on main (4779165, "Make the Godot addon an upscaler for the released model, and
# feed the token it declares") DOES NOT COMPILE, on any platform. It changed runtime/backend_cpu.cpp
# and runtime/accel_kernel.cpp so that they call
#     compute_history_trust_mask_from_textures()   and   warp_input_history_to_nchw()
# neither of which is defined anywhere in the tree, and use
#     TemporalAccumulator::phase_aligned_source()  and   PhaseAlignedFrame::input_render
# neither of which runtime/nrr_temporal.h declares - the header was not touched by that commit and
# does not mention NRRPhaseAlignedSource at all. The commit before it (a0443a2) refers to none of
# those symbols, which is why it is the revision this pins.
#
# Two suggestions for whoever fixes that upstream. First, commit the definitions. Second, one that
# is not about that commit at all - it is in a0443a2 too, so this build patches it automatically
# whichever revision is pinned (see step 3 below). nrr_temporal.h gives TemporalAccumulator::apply() a
# default argument of `const PhaseAlignedFrame& phase = PhaseAlignedFrame()`, which reads the nested
# struct's default member initializers in the class body, where that struct is still incomplete. MSVC
# allows that; Apple clang and GCC reject it ("default member initializer ... needed within definition
# of enclosing class ... outside of member functions"). The portable form:
#     Result apply(const NRRFrameInput&, std::vector<uint8_t>&, uint32_t, uint32_t,
#                  const MotionProvider&, const PhaseAlignedFrame&);
#     Result apply(const NRRFrameInput& input, std::vector<uint8_t>& rgb8, uint32_t width,
#                  uint32_t height, const MotionProvider& motion) {
#         PhaseAlignedFrame none;                     /* built in a member function body, where
#                                                        the type is complete */
#         return apply(input, rgb8, width, height, motion, none);
#     }
#
# Usage:  tools/build_nrr_macos.sh [work-dir]
# Needs:  cmake, a C++ toolchain, git, curl, python3.
#
# To finish the job the script cannot do for you: install NRR's released model beside the addon, at
# addons/nrr/models/upscale_msreal_scale.onnx. It is not in the NRR repository (models/ there holds
# two test fixtures, not weights), so it has to come from wherever the release artifacts live. Until
# it is there the game says so - "its release model: not installed" - and upscales pixel-perfect.

set -euo pipefail

REVISION="a0443a2"
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
say "checking the revision for the two known defects"
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

header = nrr / "runtime" / "nrr_temporal.h"
text = header.read_text()
default_arg = "                 const PhaseAlignedFrame& phase = PhaseAlignedFrame());"
if default_arg not in text:
    print("  nrr_temporal.h needs no patch at this revision")
else:
    text = text.replace(default_arg, """                 const PhaseAlignedFrame& phase);

    /* Added by this build: the default frame is built in a member function body rather than as a
     * default argument, because a default argument is read in the class body where PhaseAlignedFrame
     * is still incomplete. MSVC allows that; clang and GCC do not. */
    Result apply(const NRRFrameInput& input,
                 std::vector<uint8_t>& rgb8,
                 uint32_t width, uint32_t height,
                 const MotionProvider& motion) {
        PhaseAlignedFrame none;
        return apply(input, rgb8, width, height, motion, none);
    }""", 1)
    header.write_text(text)
    print("  patched nrr_temporal.h: default argument -> forwarding overload")

# The editor plugin, which is pure GDScript and therefore broken for everyone rather than only for
# people without a built library. Two Godot 3 leftovers:
#   1. add_tool_menu_item() returned an item id in Godot 3 and returns void in Godot 4, so assigning
#      it to an int is a parse error and the plugin cannot load at all.
#   2. "%s" % [...] binds tighter than the + that joins the format string to its other half, so four
#      arguments were fed to a one-placeholder string ("not all arguments converted").
plugin = nrr / "engine_plugins" / "godot" / "nrr_plugin.gd"
ptext = plugin.read_text()
godot3_id = ('var _status_item := -1\n\n\nfunc _enter_tree() -> void:\n'
             '\t_status_item = add_tool_menu_item(_MENU_ITEM, _print_status)\n'
             '\t_print_status()\n\n\nfunc _exit_tree() -> void:\n'
             '\tif _status_item != -1:\n\t\tremove_tool_menu_item(_MENU_ITEM)\n'
             '\t\t_status_item = -1\n')
if godot3_id in ptext:
    ptext = ptext.replace(godot3_id,
        'func _enter_tree() -> void:\n\tadd_tool_menu_item(_MENU_ITEM, _print_status)\n'
        '\t_print_status()\n\n\nfunc _exit_tree() -> void:\n'
        '\tremove_tool_menu_item(_MENU_ITEM)\n', 1)
    print("  patched nrr_plugin.gd: the Godot 3 tool-menu item id")
tighter = '\t\t"[NRR] native binding loaded. library=%s backend=%s entry_points=%d "\n'
if tighter in ptext:
    ptext = ptext.replace(tighter,
        '\t\t("[NRR] native binding loaded. library=%s backend=%s entry_points=%d "\n', 1)
    ptext = ptext.replace('+ "neural_acceleration=%s"\n\t\t% [nrr.library_version()',
        '+ "neural_acceleration=%s") % [nrr.library_version()', 1)
    print("  patched nrr_plugin.gd: the format string % binds tighter than +")
if ptext != plugin.read_text():
    plugin.write_text(ptext)
PY

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
