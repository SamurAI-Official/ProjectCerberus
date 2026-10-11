extends Control
## Which frame sizes does the released NRR model actually accept?
##
## A tool, not a check: it asserts nothing and prints what it measured. It exists
## because the model card and the artifact disagree. The card describes a graph
## with "dynamic H/W" that outputs 2x the input and takes a `scale` tier token;
## this model accepts one size and returns it unchanged, and the only way to know
## that is to ask it size by size.
##
##   /Applications/Godot.app/Contents/MacOS/Godot --headless --path . \
##       res://tools/verify/nrr_probe.tscn
##
## Measured on the vendored artifact, macOS arm64, CPU provider: 512x512 is the
## only size accepted; every other size comes back with "conflicts with the model's
## static input shape" and a zero-millisecond render. That is why the game says it
## is not upscaling -- it draws at 768x432.
##
## Runs headless, which is how NRR's own Godot verification runs it: the runtime
## needs no window, only frames it is handed.

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
