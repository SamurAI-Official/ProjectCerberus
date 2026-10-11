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

const DEFAULT_SCENE := "res://game/screens/match/match.tscn"
const WARMUP_FRAMES := 150

## Which scene to capture. Overridable so the same harness covers the composed
## match view and the menus, which is the point of a code-built UI: it needs
## looking at.
##
##   Godot --path . res://tools/verify/m2_render.tscn -- --scene=res://game/main.tscn
func _scene_path() -> String:
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--scene="):
			return arg.substr("--scene=".length())
	return DEFAULT_SCENE

func _output_path() -> String:
	var base := _scene_path().get_file().get_basename()
	return "user://capture_%s.png" % base

var _frames := 0
var _captured := false

func _ready() -> void:
	add_child(load(_scene_path()).instantiate())

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

	var absolute := ProjectSettings.globalize_path(_output_path())
	if image.save_png(_output_path()) != OK:
		printerr("FAIL: could not write %s" % absolute)
		get_tree().quit(1)
		return

	print("PASS: rendered %s (%dx%d) -> %s" % [_scene_path(), image.get_width(), image.get_height(), absolute])
	get_tree().quit(0)
