#!/usr/bin/env bash
#
# Apply (or verify) the Project Cerberus patch series against an NRR checkout.
#
#   ./patches/nrr/apply.sh                  # apply anything not yet applied
#   ./patches/nrr/apply.sh --check          # verify it would apply, change nothing
#   ./patches/nrr/apply.sh <checkout>       # a checkout somewhere other than the default
#
# NRR is not a submodule here, unlike vendor/openfight: tools/build_nrr_macos.sh clones it into a
# build work directory, applies this series, builds the native library and installs that into
# addons/nrr/. What this project vendors is NRR's Godot-side addon -- the GDScript wrapper, the
# descriptor, the shaders -- because the library is per-platform build output and upstream's own
# README asks that it not be committed. The checkout is therefore a build input, and the series is
# applied to it in place: the build is reproducible from "pinned commit + this series" either way,
# and the alternative (forking) would make the two fixes below a branch to go and find.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PATCH_DIR="${REPO_ROOT}/patches/nrr"

TARGET="${TMPDIR:-/tmp}/nrr-build/nrr"
CHECK_ONLY="no"
for arg in "$@"; do
    case "${arg}" in
        --check) CHECK_ONLY="yes" ;;
        *) TARGET="${arg}" ;;
    esac
done

if [[ ! -d "${TARGET}" ]]; then
    echo "error: no NRR checkout at ${TARGET}" >&2
    echo "       make one with: tools/build_nrr_macos.sh [work-dir]" >&2
    exit 1
fi

EXPECTED="$(cat "${PATCH_DIR}/PINNED_COMMIT")"
ACTUAL="$(git -C "${TARGET}" rev-parse HEAD 2>/dev/null || echo unknown)"
if [[ "${EXPECTED}" != "${ACTUAL}" ]]; then
    echo "warning: the NRR checkout is at ${ACTUAL}" >&2
    echo "         this series was written against ${EXPECTED}" >&2
fi

shopt -s nullglob
patches=("${PATCH_DIR}"/*.patch)
shopt -u nullglob

if [[ ${#patches[@]} -eq 0 ]]; then
    echo "error: no patches found in ${PATCH_DIR}" >&2
    exit 1
fi

# Is the series already in place?
#
# This cannot be asked one patch at a time, for the reason patches/openfight/apply.sh records: a
# per-patch `--reverse --check` breaks the moment two patches touch one file, because a later
# patch's hunks change the context an earlier one's reverse check looks for. So the series is
# treated as the unit it is -- the first patch is the test, and the last patch confirms.
first="${patches[0]}"
last="${patches[${#patches[@]}-1]}"

if git -C "${TARGET}" apply --check "${first}" 2>/dev/null; then
    already_applied="no"
elif git -C "${TARGET}" apply --reverse --check "${last}" 2>/dev/null; then
    already_applied="yes"
else
    echo "error: ${TARGET} is in neither state this script can act on:" >&2
    echo "       the series does not apply, and the last patch is not present" >&2
    echo "       either. Resolve it by hand rather than letting the script guess" >&2
    echo "       which half of the series is missing." >&2
    exit 1
fi

for patch in "${patches[@]}"; do
    name="$(basename "${patch}")"

    if [[ "${already_applied}" == "yes" ]]; then
        echo "  = ${name} (already applied)"
        continue
    fi

    if [[ "${CHECK_ONLY}" == "yes" ]]; then
        git -C "${TARGET}" apply --check "${patch}"
        echo "  + ${name} (applies cleanly)"
    else
        git -C "${TARGET}" apply "${patch}"
        echo "  + ${name} (applied)"
    fi
done

echo "series complete"
