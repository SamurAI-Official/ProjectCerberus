#!/usr/bin/env bash
#
# Build the openfight GDExtension for the host machine and install it at
# addons/openfight/bin/, which is where Godot discovers it under res://.
#
# Why this script exists rather than "just run scons":
#
#   * Upstream's CI cross-compiles through Docker images
#     (platform/osxcross/build_lib_*.sh) because it ships *universal*
#     x86_64+arm64 macOS frameworks. For local development we only need the
#     host architecture, so we call SCons natively and skip osxcross entirely.
#
#   * The extension links exactly one third-party library: yaml-cpp. SConstruct
#     hard-codes the path it expects that library at:
#         vendor/openfight/addons/openfight/bin/<platform>/<debug|release>/
#             vcpkg_installed/<triplet>/{lib,include}
#     which upstream populates with vcpkg. We populate it from Homebrew instead
#     because bootstraping vcpkg costs ~10 minutes and a gigabyte for one
#     header-only-ish library.
#
# CAVEAT -- must be resolved before building for anyone but this machine:
#     Homebrew ships yaml-cpp as a *dylib* whose install name is absolute
#     (/opt/homebrew/opt/yaml-cpp/lib/libyaml-cpp.0.9.dylib), so the framework
#     produced here only loads on a machine with that exact keg. A distributable
#     needs a static yaml-cpp instead:
#         cmake -S yaml-cpp -B b -DBUILD_SHARED_LIBS=OFF -DCMAKE_BUILD_TYPE=Release
#         cmake --build b -j
#     then drop libyaml-cpp.a into the lib/ path below. Tracked as a TODO.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENDOR="${REPO_ROOT}/vendor/openfight"
TARGET="${OPENFIGHT_TARGET:-template_debug}"
JOBS="${OPENFIGHT_JOBS:-$(sysctl -n hw.ncpu 2>/dev/null || nproc 2>/dev/null || echo 4)}"

if [[ ! -d "${VENDOR}" ]]; then
    echo "error: vendor/openfight is missing. Run: git submodule update --init --recursive" >&2
    exit 1
fi

# dev_build selects which vcpkg_installed/<env>/ directory SConstruct links from.
DEV_BUILD="${OPENFIGHT_DEV_BUILD:-yes}"

case "$(uname -s)" in
    Darwin) PLATFORM="macos"; TRIPLET="universal-osxcross" ;;
    Linux)  PLATFORM="linux"; TRIPLET="x64-linux" ;;
    *)      echo "error: unsupported host $(uname -s); use the upstream Docker flow" >&2; exit 1 ;;
esac

if [[ "${PLATFORM}" == "macos" ]]; then
    ARCH="${OPENFIGHT_ARCH:-$(uname -m)}"
    DEPS_DIR="${VENDOR}/addons/openfight/bin/${PLATFORM}/debug/vcpkg_installed/${TRIPLET}"
    LIBPATH="${VENDOR}/addons/openfight/bin/${PLATFORM}/release/vcpkg_installed/${TRIPLET}"

    YAML_PREFIX="$(brew --prefix yaml-cpp)"
    echo "==> linking yaml-cpp from ${YAML_PREFIX}"
    for env_dir in "${DEPS_DIR}" "${LIBPATH}"; do
        mkdir -p "${env_dir}"
        ln -sfn "${YAML_PREFIX}/lib" "${env_dir}/lib"
        ln -sfn "${YAML_PREFIX}/include" "${env_dir}/include"
    done
fi

echo "==> scons platform=${PLATFORM} target=${TARGET} dev_build=${DEV_BUILD} -j${JOBS}"
cd "${VENDOR}"
python3 -m SCons \
    "platform=${PLATFORM}" \
    "target=${TARGET}" \
    "arch=${ARCH:-$(uname -m)}" \
    "dev_build=${DEV_BUILD}" \
    debug_symbols=no \
    use_hot_reload=no \
    "-j${JOBS}"

BUILD_OUT="${VENDOR}/addons/openfight/bin"
INSTALL_DIR="${REPO_ROOT}/addons/openfight/bin"

if [[ ! -d "${BUILD_OUT}" ]]; then
    echo "error: scons reported success but ${BUILD_OUT} does not exist" >&2
    exit 1
fi

echo "==> installing into addons/openfight/bin/"
mkdir -p "$(dirname "${INSTALL_DIR}")"
rm -rf "${INSTALL_DIR}"
cp -R "${BUILD_OUT}" "${INSTALL_DIR}"

echo "==> built artifacts:"
find "${INSTALL_DIR}" -maxdepth 4 \( -name '*.gdextension' -o -name 'libopenfightgodot*' \) -print

echo
echo "Verify with:"
echo "  /Applications/Godot.app/Contents/MacOS/Godot --headless --path '${REPO_ROOT}' --quit"
