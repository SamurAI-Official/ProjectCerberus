extends Node
## Renders the full match scene (engine + HUD) and writes a PNG.
##
## The companion to m0_render.tscn, which deliberately renders the bare engine
## scene. This one is for the composed game view, so the HUD's layout and the
## CanvasLayer's independence from the Camera2D are checked with eyes rather than
## argued about.
##
##   /Applications/Godot.app/Contents/MacOS/Godot --path . \
##       res://tools/verify/m2_render.tscn

const SCENE := "res://game/screens/match/match.tscn"
const OUT_PATH := "user://m2_match.png"
const WARMUP_FRAMES := 150

var _frames := 0
var _captured := false

func _ready() -> void:
	add_child(load(SCENE).instantiate())

func _process(_delta: float) -> void:
	if _captured:
		return

	_frames += 1
	if _frames < WARMUP_FRAMES:
		return

	_captured = true
	_capture()

func _capture() -> void:
	await RenderingServer.frame_post_draw

	var image := get_viewport().get_texture().get_image()
	if image == null or image.is_empty():
		printerr("FAIL: viewport produced no image")
		get_tree().quit(1)
		return

	var absolute := ProjectSettings.globalize_path(OUT_PATH)
	if image.save_png(OUT_PATH) != OK:
		printerr("FAIL: could not write %s" % absolute)
		get_tree().quit(1)
		return

	print("PASS: rendered %dx%d -> %s" % [image.get_width(), image.get_height(), absolute])
	get_tree().quit(0)
