extends RefCounted
class_name Upscaler
## How the game's 768x432 picture becomes whatever the window is, and the one
## place that knows what this machine can actually do about it.
##
## The game is drawn at 768x432 and enlarged, so every pixel presented is an
## enlargement of a pixel that was drawn. How that enlargement happens is the
## difference between crisp pixel art and a soft smear, and it is a matter of
## taste: hence an option rather than a constant.
##
## Three ways, in the order the options screen offers them:
##
##   * NRR -- the neural path, offered but NOT the default. This is the
##     SamurAI-Official NRR runtime (github.com/samurai-official/nrr), whose Godot
##     4 addon is vendored at addons/nrr. It needs three things: the native
##     binding, which is per-platform build output upstream does not commit and
##     which tools/build_nrr_macos.sh builds; the released model, published at
##     huggingface.co/SamurAI-Official/NRR and installed beside the addon; and a
##     rendered frame to upscale. Where any of the three is missing the addon
##     reports itself unavailable and passes the frame through untouched -- it
##     never fabricates a neural frame, and neither does this file. It is off by
##     default because on this game's flat 16-colour art it costs ~767 ms/frame on
##     the CPU against ~8 ms for nearest, and tools/nrr_model_report.py scores its
##     output *worse* than the classical filter -- so the default is Nearest. It
##     stays in the menu for anyone who wants it on this art regardless.
##   * Nearest -- integer scaling with the canvas filter off: the pixel-perfect
##     path, the default, and what NRR falls back to on a machine that cannot run
##     it.
##   * Smooth -- the same scale with the filter on, for soft edges.
##
## The rule this file is built on is NRR's own: no capability is claimed that was
## not measured. Every claim the options screen makes about NRR comes from
## `nrr_state()` asking the engine, not from this file assuming it.

const NRR := "nrr"
const NEAREST := "nearest"
const SMOOTH := "smooth"

const MODES := [NRR, NEAREST, SMOOTH]

## The size the game was drawn at. Rendering above this spends fill rate on detail
## the 16-colour art does not have, and then hands the neural pass a frame that is
## already full size -- the one thing an upscaler cannot improve.
const BASE_SIZE := Vector2i(768, 432)

## The addon, and the path the released model is looked for at when the addon
## cannot be read to ask.
const ADDON := "res://addons/nrr"
const MODEL := "res://addons/nrr/models/upscale_msreal_scale.onnx"

const LABELS := {
	NRR: "NRR - neural upscale",
	NEAREST: "Nearest - pixel perfect",
	SMOOTH: "Smooth - soft edges",
}


static func label(mode: String) -> String:
	return str(LABELS.get(mode, LABELS[NEAREST]))


static func cycle_mode(mode: String, step: int) -> String:
	var index := MODES.find(mode)
	if index < 0:
		index = 0
	return MODES[posmod(index + step, MODES.size())]


## The internal render resolution, and why it is a separate control from the window
## size. It is the size the game actually draws at, so it is what the neural pass
## has to reconstruct from: lowering it is the setting that buys frame time, and it
## is the only control on the video page that does.
##
## `content_scale_size` is Godot's name for it. Setting it makes the engine draw
## the canvas at this size and present it larger, which is exactly the arrangement
## an upscaler is for.
const RESOLUTIONS := [
	{"id": "native", "size": Vector2i(768, 432), "label": "768 x 432   native"},
	{"id": "three_quarter", "size": Vector2i(576, 324), "label": "576 x 324   three quarter"},
	{"id": "half", "size": Vector2i(384, 216), "label": "384 x 216   half"},
	{"id": "quarter", "size": Vector2i(192, 108), "label": "192 x 108   quarter"},
]
const DEFAULT_RESOLUTION := "native"

const RESOLUTION_IDS := ["native", "three_quarter", "half", "quarter"]


static func resolution_size(id: String) -> Vector2i:
	for entry in RESOLUTIONS:
		if str(entry["id"]) == id:
			return entry["size"]
	return BASE_SIZE


static func resolution_label(id: String) -> String:
	for entry in RESOLUTIONS:
		if str(entry["id"]) == id:
			return str(entry["label"])
	return str(RESOLUTIONS[0]["label"])


## Next and previous, so the options screen cycles one line rather than growing by
## four entries that are all the same question.
static func cycle_resolution(id: String, step: int) -> String:
	var index := RESOLUTION_IDS.find(id)
	if index < 0:
		index = 0
	return RESOLUTION_IDS[posmod(index + step, RESOLUTION_IDS.size())]


## Where the released model has to be for the addon to find it: asked of the addon,
## because upstream owns that path (its own RELEASE_MODEL_PATH) and a game holding
## its own copy of the string would go on reporting "not installed" for a year
## after it moved. The constant above is only what to fall back to when the addon
## cannot be read at all.
static func model_path() -> String:
	var script := load(ADDON + "/nrr_post_process.gd") as GDScript
	if script != null:
		var declared := str(script.get_script_constant_map().get("RELEASE_MODEL_PATH", ""))
		if declared != "":
			return declared
	return MODEL


## What NRR can do here, measured rather than assumed: whether the addon is
## vendored at all, whether its native library loaded on this platform, whether the
## released model is installed beside it, and a sentence naming whichever is
## missing.
##
## Deliberately answered by asking the engine whether the class is registered
## rather than by calling NRR.initialize(): a missing binding makes initialize()
## push a warning, and a probe that complains every time the menu opens is a probe
## that trains people to ignore the log.
static func nrr_state() -> Dictionary:
	var vendored := FileAccess.file_exists(ADDON + "/nrr.gdextension")
	var binding := ClassDB.class_exists("NRRNative")
	# FileAccess rather than ResourceLoader, which is the addon's own reasoning: a
	# .onnx has no importer, so it is a raw resource and ResourceLoader.exists()
	# reports false for a file that is sitting right there.
	var model := FileAccess.file_exists(model_path())
	var reason := "ready"
	if not vendored:
		reason = "the addon is not vendored at addons/nrr"
	elif not binding:
		reason = "its native library is not built for %s" % OS.get_name()
	elif not model:
		reason = "its released model is not installed beside the addon"
	return {
		"vendored": vendored,
		"binding": binding,
		"model": model,
		"ready": vendored and binding and model,
		"reason": reason,
	}


## Whether the neural pass can actually run here: the binding, the model, and a
## frame to work on. The third is not obvious and is not optional -- the node reads
## the rendered viewport back every frame, and Godot's headless display server
## renders nothing, so the capture comes back null. That is not the addon being
## wrong; it is a node for a windowed game. So the pass is attached where there are
## frames and not where there are none, and the mode in use says which.
static func can_run_nrr() -> bool:
	if DisplayServer.get_name() == "headless":
		return false
	return bool(nrr_state()["ready"])


## One line for the options screen: what will actually happen, in plain words.
##
## `host` is the node the pass is attached to, and passing it is what keeps this
## from over-claiming. Installation is not operation: the binding, the model and a
## rendered frame can all be present while the runtime declines every single frame,
## and from the outside that looks exactly like a working upscaler that happens to
## be producing a good picture. So when a host is given, the runtime is asked what
## it last did -- and the answer, not the file listing, is what the screen says.
static func report(mode: String, host: Node = null) -> String:
	if mode != NRR:
		return "In use: %s." % label(mode)
	var state := nrr_state()
	if not bool(state["ready"]):
		return "NRR selected, but %s - the picture is upscaled pixel-perfect instead." % str(state["reason"])
	if DisplayServer.get_name() == "headless":
		return "NRR is installed, but this run has no frames to upscale."
	if host == null:
		return "NRR is selected and installed; choosing this again cycles the upscalers."
	var live := stats(host)
	if live.is_empty():
		return "NRR is selected and installed; its pass has not reported a frame yet."
	if not bool(live.get("initialised", false)) or not bool(live.get("available", false)):
		return "NRR is installed but its runtime did not start: %s" % str(live.get("error", ""))
	if bool(live.get("passthrough", true)):
		var why := str(live.get("error", ""))
		if why == "":
			why = "the runtime declined the frame and did not say why"
		return "NRR is running but declining every frame: %s" % why
	return "In use: NRR, upscaling through its release model as %s." % str(live.get("backend", "?"))


## Puts a mode on the picture and gives back the one actually in use, which is not
## always the one asked for. `host` is any node inside the tree -- the menu, the
## options screen, the match -- because that is what the window and the viewport
## are reached through.
static func apply(mode: String, host: Node, resolution: String = DEFAULT_RESOLUTION) -> String:
	if host == null or not host.is_inside_tree():
		return mode
	var window := host.get_window()
	if window != null:
		window.content_scale_mode = Window.CONTENT_SCALE_MODE_CANVAS_ITEMS
		window.content_scale_aspect = Window.CONTENT_SCALE_ASPECT_EXPAND
		window.content_scale_size = resolution_size(resolution)

	if mode == SMOOTH:
		_stretch(window, false)
		_filter(host, true)
		detach(host)
		return SMOOTH

	if mode == NEAREST:
		_stretch(window, true)
		_filter(host, false)
		detach(host)
		return NEAREST

	# NRR. The pixel-perfect path is set first, so that if the neural pass turns out
	# to be unavailable the picture is already right rather than left in whatever
	# state it was in.
	_stretch(window, true)
	_filter(host, false)
	if not can_run_nrr():
		detach(host)
		return NEAREST
	if _attach_nrr(host) == null:
		detach(host)
		return NEAREST
	return NRR


static func _stretch(window: Window, integer: bool) -> void:
	if window == null:
		return
	window.content_scale_stretch = Window.CONTENT_SCALE_STRETCH_INTEGER if integer \
		else Window.CONTENT_SCALE_STRETCH_FRACTIONAL


## The filter the canvas draws textures with: off for the pixel-perfect path, on for
## the smooth one. The project sets nearest for the game's own art, and this is the
## per-run override of that. Set on the viewport rather than through the
## RenderingServer so that it can be read back and checked.
static func _filter(host: Node, smooth: bool) -> void:
	var vp := host.get_viewport()
	if vp == null:
		return
	vp.canvas_item_default_texture_filter = \
		Viewport.DEFAULT_CANVAS_ITEM_TEXTURE_FILTER_LINEAR if smooth \
		else Viewport.DEFAULT_CANVAS_ITEM_TEXTURE_FILTER_NEAREST


## The neural pass, when this machine has one: the addon's own post-process node,
## which its README documents as the intended use ("Add an NRRPostProcess node to a
## scene, or drive NRR directly"). Everything about the neural render happens in
## there -- the model, the temporal history, the honest passthrough when the binding
## is absent -- so there is nothing here to reimplement, only to attach.
##
## Loaded by path rather than named as a class, because the game has to run on a
## checkout where the addon is not there at all.
static func _attach_nrr(host: Node) -> Node:
	var existing := host.get_node_or_null("NRRPostProcess")
	if existing != null:
		return existing
	var script := load(ADDON + "/nrr_post_process.gd") as GDScript
	if script == null:
		return null
	var node = script.new()
	if node == null:
		return null
	node.name = "NRRPostProcess"
	host.add_child(node)
	return node


## Takes the neural pass back off, for a mode that does not want it. Left in the
## tree it keeps running, and keeps being paid for.
static func detach(host: Node) -> void:
	if host == null or not host.is_inside_tree():
		return
	var node := host.get_node_or_null("NRRPostProcess")
	if node != null:
		host.remove_child(node)
		node.queue_free()


## What the attached pass is currently doing, for a check that has to tell "the
## integration ran" from "it declined" from "it is off". An empty dictionary means
## no pass is attached, which is itself an answer.
static func stats(host: Node) -> Dictionary:
	if host == null:
		return {}
	var node := host.get_node_or_null("NRRPostProcess")
	if node == null:
		return {}
	var nrr = node.get("_nrr")
	if nrr == null:
		return {"attached": true, "initialised": false}
	return {
		"attached": true,
		"initialised": true,
		"available": bool(nrr.get("available")),
		"model": str(nrr.get("loaded_model")),
		"passthrough": bool(nrr.get("last_render_was_passthrough")),
		"backend": str(nrr.call("backend_name")),
		"render_time_ms": float(nrr.call("last_render_time_ms")),
		"error": str(nrr.get("last_error")),
	}
