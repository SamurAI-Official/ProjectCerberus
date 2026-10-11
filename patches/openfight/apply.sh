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

for patch in "${patches[@]}"; do
    name="$(basename "${patch}")"

    # `--reverse --check` succeeds only when the patch is already applied, which
    # makes this idempotent instead of failing on the second run.
    if git -C "${TARGET}" apply --reverse --check "${patch}" 2>/dev/null; then
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
