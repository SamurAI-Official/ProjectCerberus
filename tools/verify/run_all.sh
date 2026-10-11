#!/usr/bin/env bash
#
# Run every verification scene and report a single pass/fail.
#
# For CI, and for "did I just break something" before a commit. Each scene is a
# standalone Godot run, so a crash in one cannot take the suite down with it.
#
#   ./tools/verify/run_all.sh
#   GODOT_HEADLESS_ONLY=1 ./tools/verify/run_all.sh   # skip the render scenes
#
# The render scenes need a real window and a GPU, so a headless CI box should set
# GODOT_HEADLESS_ONLY=1. Note that this means CI covers the simulation and the
# HUD's state but not a single pixel -- m0_render and m2_render are the only
# things that would catch a rendering regression, and they need a display.

set -uo pipefail # deliberately not -e: every test should run, and the exit code
                 # should be the aggregate rather than the first failure

GODOT="${GODOT:-/Applications/Godot.app/Contents/MacOS/Godot}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG_DIR="${TMPDIR:-/tmp}/cerberus-verify"

cd "${REPO_ROOT}"
mkdir -p "${LOG_DIR}"

if [[ ! -x "${GODOT}" ]]; then
    echo "error: Godot not found at ${GODOT} (override with GODOT=/path/to/Godot)" >&2
    exit 2
fi

failed=0

run() {
    local name="$1"
    shift
    local log="${LOG_DIR}/${name}.log"

    printf '  %-10s ' "${name}"
    if "$@" >"${log}" 2>&1; then
        echo "PASS"
    else
        echo "FAIL"
        sed 's/^/               | /' "${log}" | tail -20
        failed=1
    fi
}

# A fresh clone has no .godot/ import cache and every scene would fail on missing
# resources, so import once up front. Its own failure is not fatal -- the scenes
# report the real problem.
echo "importing assets..."
"${GODOT}" --headless --path . --import >"${LOG_DIR}/import.log" 2>&1 || true

echo "validating manifests..."
if python3 "${REPO_ROOT}/tools/validate/validate_manifest.py"; then
    echo "  OK"
else
    echo "  FAIL"
    failed=1
fi

echo "running verification scenes:"
run m0_smoke "${GODOT}" --headless --path . res://tools/verify/m0_smoke.tscn
run m1_match "${GODOT}" --headless --path . res://tools/verify/m1_match.tscn
run m2_hud "${GODOT}" --headless --path . res://tools/verify/m2_hud.tscn
run m2_flow "${GODOT}" --headless --path . res://tools/verify/m2_flow.tscn
run m3_roster "${GODOT}" --headless --path . res://tools/verify/m3_roster.tscn
# Walls. Headless because patch 0003 exposes get_player_x, which is what makes the
# question answerable without a screen: before it the node published no position,
# so "walked off the stage" could not be seen from a test at all.
run walls "${GODOT}" --headless --path . res://tools/verify/walls.tscn

if [[ "${GODOT_HEADLESS_ONLY:-0}" == "1" ]]; then
    echo "  (render scenes skipped: GODOT_HEADLESS_ONLY=1)"
else
    run m0_render "${GODOT}" --path . res://tools/verify/m0_render.tscn
    run m2_render "${GODOT}" --path . res://tools/verify/m2_render.tscn
    # The only check that fails when hitboxes and hurtboxes stop overlapping. The
    # headless roster test notices too, but it reports it as a 120-second timeout
    # rather than as a box problem, which is a much longer walk to the same place.
    run m3_boxes "${GODOT}" --path . res://tools/verify/m3_boxes.tscn
    # Video and audio options, including whether the neural upscaler is actually
    # upscaling or merely installed -- two states that look identical from outside.
    # Windowed, because the pass needs rendered frames before it will say anything.
    run video_options "${GODOT}" --path . res://tools/verify/video_options.tscn
fi

echo
if [[ ${failed} -eq 0 ]]; then
    echo "all verification scenes passed"
else
    echo "FAILURES -- logs in ${LOG_DIR}" >&2
fi

exit ${failed}
