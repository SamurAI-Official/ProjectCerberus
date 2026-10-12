extends Control
## Which frame sizes does the vendored NRR binding accept, and what does it return for each?
##
## A tool, not a check: it asserts nothing and prints what it measured. What it measures is the
## *binding*, not the model -- a distinction that has already cost this project one wrong entry in
## its README, so it is worth stating twice. `tools/nrr_model_report.py` measures the model through
## ONNX Runtime directly; this measures the addon, which is the thing the game actually calls.
##
##   /Applications/Godot.app/Contents/MacOS/Godot --headless --path . \
##       res://tools/verify/nrr_probe.tscn
##
## The earlier reading of this file, and of the README, was wrong, and the correction is the point
## of keeping the tool: 512x512 was the only size that "worked", every other size came back with
## "conflicts with the model's static input shape" and a zero-millisecond render, and the cause was
## written down as a binding that predates the released model. It was not that. The macOS build was
## falling back to NRR's *placeholder* inference path, because NRR's CMake only looked for an ONNX
## Runtime in the Android and Windows layouts and never in the macOS/Unix one -- and that path
## reports a fixed 1x3x512x512 input shape, so 512x512 was the only size it agreed to "run", at
## 1.9 ms, without executing a model at all. With the layout arm added (patches/nrr/0003) the
## runtime accepts every size and reports the model's real, fully dynamic shapes; with the
## read-back fixed (patches/nrr/0004) each size returns the *model's* output grid rather than a
## zero-filled image at the input size.
##
## Measured on this machine, macOS arm64, CPU execution provider, release build, at the time of
## writing -- the right-hand column is the ratio the model's own head produces, which is why a
## 2.5x model is needed for 768x432 -> 1920x1080:
##
##   384x216  ->  768x432    200 ms   (half-resolution canvas -> canvas)
##   768x432  -> 1536x864    834 ms   (canvas -> the 2x model's tier)
##   1024x576 -> 2048x1152  1440 ms
##
## Runs headless, which is how NRR's own Godot verification runs it: the runtime needs no window,
## only frames it is handed.

const MODEL := "res://addons/nrr/models/upscale_msreal_scale.onnx"

const SIZES := [
	Vector2i(64, 48), Vector2i(128, 72), Vector2i(128, 128),
	Vector2i(192, 108), Vector2i(256, 144), Vector2i(256, 256),
	Vector2i(384, 216), Vector2i(512, 288), Vector2i(512, 512),
	Vector2i(768, 432), Vector2i(1024, 576), Vector2i(1024, 1024),
]


func _ready() -> void:
	var nrr := NRR.new()
	print("=== nrr model shape probe ===")
	if not nrr.initialize():
		print("initialize failed: %s" % nrr.last_error)
		get_tree().quit(1)
		return
	print("backend     : %s" % nrr.backend_name())
	print("capabilities: %s" % str(nrr.capabilities()))
	print("load_model  : %s  err='%s'" % [str(nrr.load_model(MODEL)), nrr.last_error])
	print("model_info  : %s" % nrr.model_info())
	print("")
	for size in SIZES:
		var img := Image.create(size.x, size.y, false, Image.FORMAT_RGBA8)
		img.fill(Color(0.3, 0.5, 0.7, 1.0))
		var out = nrr.render_frame(img)
		var shape := "null"
		if out is Image:
			var result: Image = out
			shape = "%dx%d" % [result.get_width(), result.get_height()]
		print("  %-11s -> %-11s passthrough=%-5s %.2f ms  err='%s'" % [
			"%dx%d" % [size.x, size.y], shape, str(nrr.last_render_was_passthrough),
			nrr.last_render_time_ms(), nrr.last_error])
	nrr.shutdown()
	get_tree().quit(0)
