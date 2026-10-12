extends Control
## What does the binding actually hand back for a ratio-2 model?
##
## A tool, not a check: it asserts nothing and writes what it measured. `nrr_probe.gd` answers
## "which sizes are accepted"; this answers the question that follows, and which the probe cannot:
## *what is in the frame that comes back*. Both images are written to build/nrr/ so the answer can
## be looked at rather than inferred.
##
##   /Applications/Godot.app/Contents/MacOS/Godot --headless --path . \
##       res://tools/verify/nrr_output_check.tscn
##
## Why a test pattern and not a game frame: the pattern is chosen so the three possible mechanisms
## are distinguishable by eye.
##
##   * a same-size refinement  -> the whole checkerboard, every block, softened
##   * the ratio-2 output cropped to the input size -> the top-left quarter of the blocks, magnified
##   * the ratio-2 output resampled back down -> the whole board, blurred, at the input size
##
## The ratio-2 model is the sharpest case for this because a 2x output is exactly divisible, so a
## crop and a resample are both exact operations and neither hides behind a fractional ratio.

const MODEL := "res://addons/nrr/models/upscale_msreal_scale.onnx"

# Small on purpose: a 2x model at 128x72 produces 256x144, which is enough to tell the three
# mechanisms apart and costs ~15 ms to run.
const WIDTH := 128
const HEIGHT := 72

const OUT_DIR := "res://build/nrr"


func _make_pattern() -> Image:
	var image := Image.create(WIDTH, HEIGHT, false, Image.FORMAT_RGBA8)
	var block := 8
	for y in HEIGHT:
		for x in WIDTH:
			var on := ((x / block) + (y / block)) % 2 == 0
			image.set_pixel(x, y, Color(1.0, 1.0, 1.0, 1.0) if on else Color(0.0, 0.0, 0.0, 1.0))
	# A one-pixel white frame, so a crop is unmistakable: a crop of the top-left quarter loses the
	# right and bottom edges entirely, while any full-frame operation keeps all four.
	for x in WIDTH:
		image.set_pixel(x, 0, Color(1.0, 0.0, 0.0, 1.0))
		image.set_pixel(x, HEIGHT - 1, Color(0.0, 1.0, 0.0, 1.0))
	for y in HEIGHT:
		image.set_pixel(0, y, Color(0.0, 0.0, 1.0, 1.0))
		image.set_pixel(WIDTH - 1, y, Color(1.0, 1.0, 0.0, 1.0))
	return image


func _mean_abs_difference(a: Image, b: Image) -> float:
	if a.get_width() != b.get_width() or a.get_height() != b.get_height():
		return -1.0
	var total := 0.0
	for y in a.get_height():
		for x in a.get_width():
			var pa := a.get_pixel(x, y)
			var pb := b.get_pixel(x, y)
			total += absf(pa.r - pb.r) + absf(pa.g - pb.g) + absf(pa.b - pb.b)
	return total / float(a.get_width() * a.get_height() * 3)


func _ready() -> void:
	var nrr := NRR.new()
	print("=== nrr output content check ===")
	if not nrr.initialize():
		print("initialize failed: %s" % nrr.last_error)
		get_tree().quit(1)
		return
	var loaded: bool = nrr.load_model(MODEL)
	print("model      : %s  loaded=%s  err='%s'" % [MODEL, str(loaded), nrr.last_error])
	if not loaded:
		get_tree().quit(1)
		return
	print("model_info : %s" % nrr.model_info())

	var input := _make_pattern()
	var out = nrr.render_frame(input)
	if not (out is Image):
		print("render_frame returned %s" % typeof(out))
		get_tree().quit(1)
		return
	var result: Image = out

	print("input      : %dx%d" % [input.get_width(), input.get_height()])
	print("output     : %dx%d  passthrough=%s  %.2f ms  err='%s'" % [
		result.get_width(), result.get_height(), str(nrr.last_render_was_passthrough),
		nrr.last_render_time_ms(), nrr.last_error])
	print("mad(out,in): %.4f   (0.0 would be a byte-identical passthrough)" % \
		_mean_abs_difference(result, input))

	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(OUT_DIR))
	var in_path := "%s/output_check_input.png" % OUT_DIR
	var out_path := "%s/output_check_result.png" % OUT_DIR
	input.save_png(in_path)
	result.save_png(out_path)
	print("wrote      : %s" % in_path)
	print("wrote      : %s" % out_path)

	# Corner probes, as numbers, so the answer does not depend on anyone opening the PNGs: the four
	# corners of the input are red/green/blue/yellow, and where those colours turn up in the output
	# says which of the three mechanisms ran.
	print("output corners: TL=%s TR=%s BL=%s BR=%s" % [
		str(result.get_pixel(0, 0)), str(result.get_pixel(result.get_width() - 1, 0)),
		str(result.get_pixel(0, result.get_height() - 1)),
		str(result.get_pixel(result.get_width() - 1, result.get_height() - 1))])

	nrr.shutdown()
	get_tree().quit(0)
