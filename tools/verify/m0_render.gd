extends Node
## Renders the stock match for a few frames and writes a PNG.
##
## m0_smoke.tscn cannot cover this: NOTIFICATION_DRAW never fires in headless, so
## GodotRenderBackend is never exercised there. This scene must be run WITHOUT
## --headless, and it leaves an image behind that can actually be looked at
## rather than assumed.
##
##   /Applications/Godot.app/Contents/MacOS/Godot --path . \
##       res://tools/verify/m0_render.tscn

const OUT_PATH := "user://m0_render.png"
const WARMUP_FRAMES := 90

var _frames := 0
var _captured := false

func _ready() -> void:
	add_child(load("res://game/screens/match/match.tscn").instantiate())

func _process(_delta: float) -> void:
	if _captured:
		return

	_frames += 1
	if _frames < WARMUP_FRAMES:
		return

	_captured = true
	_capture()

func _capture() -> void:
	# The viewport texture is only valid after the frame has actually been
	# drawn, so wait for the render server rather than reading it inline.
	await RenderingServer.frame_post_draw

	var image := get_viewport().get_texture().get_image()
	if image == null or image.is_empty():
		printerr("FAIL: viewport produced no image -- the render backend drew nothing")
		get_tree().quit(1)
		return

	var absolute := ProjectSettings.globalize_path(OUT_PATH)
	var error := image.save_png(OUT_PATH)
	if error != OK:
		printerr("FAIL: could not write %s (error %d)" % [absolute, error])
		get_tree().quit(1)
		return

	print("PASS: rendered %dx%d -> %s" % [image.get_width(), image.get_height(), absolute])
	get_tree().quit(0)
