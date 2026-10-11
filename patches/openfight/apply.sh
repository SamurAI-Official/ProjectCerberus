#!/usr/bin/env bash
#
# Apply (or verify) the Project Cerberus patch series against vendor/openfight.
#
#   ./patches/openfight/apply.sh           # apply anything not yet applied
#   ./patches/openfight/apply.sh --check   # verify it would apply, change nothing
#
# The vendored engine is never hand-edited as a matter of record: every change
# lives in a numbered .patch file here, so the build can be reproduced from the
# pinned commit plus this series, and an upstream rebase is a rebase rather than
# archaeology. It also keeps the LGPL-3.0 story simple -- the modified engine
# source is these patches, published alongside the game.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TARGET="${REPO_ROOT}/vendor/openfight"
PATCH_DIR="${REPO_ROOT}/patches/openfight"

CHECK_ONLY="no"
if [[ "${1:-}" == "--check" ]]; then
    CHECK_ONLY="yes"
fi

if [[ ! -d "${TARGET}" ]]; then
    echo "error: ${TARGET} is missing -- run: git submodule update --init --recursive" >&2
    exit 1
fi

EXPECTED="$(cat "${PATCH_DIR}/PINNED_COMMIT")"
ACTUAL="$(git -C "${TARGET}" rev-parse HEAD)"
if [[ "${EXPECTED}" != "${ACTUAL}" ]]; then
    echo "warning: vendor/openfight is at ${ACTUAL}" >&2
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
# This cannot be asked one patch at a time. A per-patch `--reverse --check` is the
# obvious test and it is wrong the moment one patch shares a file with an earlier
# one: 0003 edits lines beside 0001's hunks, which changes the context that 0001's
# reverse check looks for, so 0001 reports "not applied" and the script applies it
# a second time -- failing, noisily, on a tree that is already correct.
#
# So the series is treated as the unit it is. The first patch is the test: if it
# still applies forward, nothing is in place and the series is applied in order.
# If it does not, the series is already in, and the LAST patch's reverse check
# confirms it -- the last patch being the only one no later change can disturb.
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
