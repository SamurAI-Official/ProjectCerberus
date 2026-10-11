extends Control
## Video and audio options: does the game actually do what the screen says?
##
## Two questions, and the second is the one that matters.
##
## The first is whether each control moves the thing it names -- the upscaler picks
## a mode, the resolution changes the size the canvas is drawn at, the frame counter
## appears in the corner, the volume moves the master bus. Those are ordinary
## assertions.
##
## The second is whether the game tells the truth about NRR. "NRR is selected" and
## "NRR is upscaling" are different claims, and the failure mode this guards against
## is the one where a project ships a neural upscaler that silently is not running:
## the option is set, the picture looks fine, and nothing is upscaled. So the check
## asks the runtime what it is doing, and separately asserts that the sentence on
## the options screen agrees with the answer.
##
##   /Applications/Godot.app/Contents/MacOS/Godot --path . \
##       res://tools/verify/video_options.tscn
##
## Runs headless too, with the neural pass' own assertions skipped -- it needs
## rendered frames, and a headless run has none. What it does not skip is the
## honesty check, which is exactly the check that still means something there.

## Frames to let the pass run before asking what it did. Generous on purpose: the
## first frames of a run are the ones where the viewport read-back can still come
## back empty, and a check that asked too early would report "not upscaling" about
## a pass that was simply not warm.
const MEASURE_FRAMES := 60

var _failures: Array = []
var _done := false
var _frames := 0
var _phase := "apply"
var _notes: Array = []


func _ready() -> void:
	Engine.max_fps = 60
	print("=== video and audio options ===")
	print("  display  : %s" % DisplayServer.get_name())
	print("  renderer : %s" % ProjectSettings.get_setting("rendering/renderer/rendering_method", "?"))
	_check_defaults()
	_check_geometry_before()
	_check_sound()
	_check_persistence()
	_check_options_screen()
	_report_nrr_state()
	# Put the picture on NRR through the same path the options screen uses, and let
	# it run a few frames before asking what it did.
	UserSettings.set_show_fps(true)
	UserSettings.set_upscaler(Upscaler.NRR)
	_phase = "measure"


func _process(_delta: float) -> void:
	if _done:
		return
	if _phase == "measure":
		_frames += 1
		if _frames >= MEASURE_FRAMES:
			# The read-back has to be taken after the frame is drawn, so the rest of
			# the checks wait for that rather than running from here.
			_phase = "measuring"
			_measure.call_deferred()


func _measure() -> void:
	# Before the await, which is how the addon reads it: from _process, mid-frame.
	# If this is empty and the awaited one below is not, then the read-back is
	# simply not available at the point the pass asks for it, and no amount of
	# waiting inside the pass would fix it.
	_probe_readback("mid-frame")
	await RenderingServer.frame_post_draw
	_probe_readback("after draw")
	_check_nrr_runtime()
	_check_fps_overlay()
	_check_resolution_applied()
	_finish()


## What the neural pass depends on and cannot do without: a rendered frame it can
## read back. Probed here rather than inferred, because "the pass did nothing" and
## "there was nothing for it to read" are the same observation from outside, and
## only one of them is the pass' fault.
func _probe_readback(when: String) -> void:
	var texture := get_viewport().get_texture()
	if texture == null:
		_notes.append("read-back %-11s: no texture at all" % when)
		return
	var image := texture.get_image()
	if image == null:
		_notes.append("read-back %-11s: texture is %dx%d but get_image() returned null"
				% [when, texture.get_width(), texture.get_height()])
		return
	_notes.append("read-back %-11s: %dx%d, format %d"
			% [when, image.get_width(), image.get_height(), image.get_format()])


# ---------------------------------------------------------------------------
# Defaults, and the one the request named
# ---------------------------------------------------------------------------

func _check_defaults() -> void:
	if Upscaler.NRR != "nrr":
		_fail("the NRR mode id changed; the options file keys would stop matching")
	if not Upscaler.MODES.has(Upscaler.NRR):
		_fail("NRR is not among the upscalers offered")
	if Upscaler.MODES[0] != Upscaler.NRR:
		_fail("NRR is offered, but not first: %s" % str(Upscaler.MODES))
	# The shipped default is the whole point of the option existing, so it is
	# asserted rather than described.
	if Upscaler.DEFAULT_RESOLUTION != "native":
		_fail("the default render resolution is not native")


func _check_geometry_before() -> void:
	var window := get_window()
	if window == null:
		_fail("no window to apply the render resolution to")
		return
	_notes.append("content scale size before: %s" % str(window.content_scale_size))


# ---------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------

func _check_sound() -> void:
	var bus := AudioServer.get_bus_index("Master")
	if bus < 0:
		_fail("there is no Master bus to put a volume on")
		return
	var before := AudioServer.get_bus_volume_db(bus)
	UserSettings.set_sound("low")
	if not is_equal_approx(AudioServer.get_bus_volume_db(bus), UserSettings.LOW_DB):
		_fail("sound=low did not move the master bus (%.1f dB)"
				% AudioServer.get_bus_volume_db(bus))
	if AudioServer.is_bus_mute(bus):
		_fail("sound=low muted the bus")
	UserSettings.set_sound("off")
	if not AudioServer.is_bus_mute(bus):
		_fail("sound=off did not mute the master bus")
	UserSettings.set_sound("full")
	if AudioServer.is_bus_mute(bus) or not is_equal_approx(AudioServer.get_bus_volume_db(bus), 0.0):
		_fail("sound=full did not restore the master bus (%.1f dB, muted=%s)"
				% [AudioServer.get_bus_volume_db(bus), str(AudioServer.is_bus_mute(bus))])
	_notes.append("master bus %.0f dB -> %.0f dB across off/low/full"
			% [before, AudioServer.get_bus_volume_db(bus)])


# ---------------------------------------------------------------------------
# Persistence, including the values a hand-edited file can carry
# ---------------------------------------------------------------------------

func _check_persistence() -> void:
	UserSettings.set_upscaler(Upscaler.SMOOTH)
	UserSettings.set_render_resolution("half")
	UserSettings.set_show_fps(true)
	UserSettings.set_sound("low")

	# Wipe the in-memory copy the way a fresh launch would, then read it back.
	UserSettings.upscaler = ""
	UserSettings.render_resolution = ""
	UserSettings.show_fps = false
	UserSettings.sound = ""
	UserSettings.load_from_disk()
	if UserSettings.upscaler != Upscaler.SMOOTH:
		_fail("the upscaler did not survive a save/load: '%s'" % UserSettings.upscaler)
	if UserSettings.render_resolution != "half":
		_fail("the render resolution did not survive: '%s'" % UserSettings.render_resolution)
	if not UserSettings.show_fps:
		_fail("the frame counter toggle did not survive")
	if UserSettings.sound != "low":
		_fail("the sound level did not survive: '%s'" % UserSettings.sound)

	# A corrupt file must fall back rather than be trusted into a mode that does not
	# exist -- the failure that would otherwise read as "not NRR, so use nearest"
	# while the file still claimed NRR.
	var config := ConfigFile.new()
	config.set_value("video", "upscaler", "definitely-not-a-mode")
	config.set_value("video", "resolution", "also-not-a-size")
	config.set_value("audio", "level", "eleven")
	config.save(UserSettings.PATH)
	UserSettings.load_from_disk()
	if UserSettings.upscaler != Upscaler.NRR:
		_fail("a corrupt upscaler did not fall back to NRR: '%s'" % UserSettings.upscaler)
	if UserSettings.render_resolution != Upscaler.DEFAULT_RESOLUTION:
		_fail("a corrupt resolution did not fall back: '%s'" % UserSettings.render_resolution)
	if UserSettings.sound != UserSettings.DEFAULT_SOUND:
		_fail("a corrupt sound level did not fall back: '%s'" % UserSettings.sound)
	_notes.append("a corrupt settings file falls back to %s / %s / %s"
			% [UserSettings.upscaler, UserSettings.render_resolution, UserSettings.sound])


# ---------------------------------------------------------------------------
# The screen itself
# ---------------------------------------------------------------------------

func _check_options_screen() -> void:
	var script := load("res://game/screens/options/options.gd") as GDScript
	if script == null:
		_fail("the options screen script does not load")
		return
	var screen = script.new()
	if screen == null:
		_fail("the options screen does not instantiate")
		return
	add_child(screen)

	var ids: Array = []
	for item in screen.items:
		ids.append(str(item.get("id", "")))
	var required := ["upscaler", "resolution", "fps", "sound", "fullscreen", "vsync", "back"]
	for want in required:
		if not ids.has(want):
			_fail("the options screen does not offer '%s' (it offers %s)" % [want, str(ids)])
	_notes.append("options items  : %s" % str(ids))

	# Cycling has to visit every mode and land back where it started, and the label
	# has to follow it -- a control whose label does not move is the failure this
	# screen is arranged to avoid.
	UserSettings.set_upscaler(Upscaler.NRR)
	for _step in range(Upscaler.MODES.size()):
		screen.on_chosen("upscaler")
	if UserSettings.upscaler != Upscaler.NRR:
		_fail("cycling the upscaler %d times did not return to NRR (at '%s')"
				% [Upscaler.MODES.size(), UserSettings.upscaler])
	# Explicit typing: `screen` came from an untyped `GDScript.new()`, so the
	# compiler cannot infer the return type of anything called on it.
	var upscaler_label: String = screen.label_of("upscaler")
	if not upscaler_label.begins_with("UPSCALER:"):
		_fail("the upscaler label does not name the setting: '%s'" % upscaler_label)
	_notes.append("upscaler label : %s" % upscaler_label)
	_notes.append("upscaler detail: %s" % screen.detail_of("upscaler").replace("\n", " | "))
	_notes.append("sound label    : %s" % screen.label_of("sound"))

	# Every control has to explain itself when it is looked at, and has to have left
	# the game in a state its own label describes.
	for id in required:
		if screen.detail_of(id) == "":
			_fail("the options item '%s' explains nothing" % id)
	if screen.label_of("resolution") == "" or screen.label_of("fps") == "":
		_fail("a video option has no label")

	remove_child(screen)
	screen.queue_free()


# ---------------------------------------------------------------------------
# NRR: is it installed, and is it running
# ---------------------------------------------------------------------------

func _report_nrr_state() -> void:
	var state := Upscaler.nrr_state()
	_notes.append("nrr vendored=%s binding=%s model=%s" % [
		str(state["vendored"]), str(state["binding"]), str(state["model"])])
	_notes.append("nrr model path : %s" % Upscaler.model_path())
	_notes.append("nrr report     : %s" % Upscaler.report(Upscaler.NRR))
	# The pass' own view of itself. Read directly rather than through Upscaler.stats,
	# because when a pass declines to run, the question is which of its gates closed.
	var node := UserSettings.get_node_or_null("NRRPostProcess")
	if node == null:
		_notes.append("nrr node       : not attached")
		return
	_notes.append("nrr node       : enabled=%s passthrough=%s overlay=%s processing=%s editor_hint=%s"
			% [str(node.get("enabled")), str(node.get("passthrough")),
				"yes" if node.get("_overlay") != null else "no",
				str(node.is_processing()), str(Engine.is_editor_hint())])


func _check_nrr_runtime() -> void:
	var state := Upscaler.nrr_state()
	var report := Upscaler.report(UserSettings.upscaler, UserSettings)

	if DisplayServer.get_name() == "headless":
		# Documented rather than skipped: the pass needs rendered frames, and the
		# sentence the options screen shows has to say exactly that.
		if not report.contains("no frames"):
			_fail("headless: the report does not explain why NRR is not upscaling: '%s'" % report)
		return

	if not bool(state["ready"]):
		# A checkout with no built binding is a legitimate state, not a test failure.
		# What is not legitimate is claiming otherwise, so that is what is checked.
		if not report.contains(str(state["reason"])):
			_fail("the report does not name what is missing: '%s'" % report)
		return

	# Asked of the same host the settings attach the pass to -- UserSettings applies
	# it to itself, so that is where it lives. Asking the wrong node returns an empty
	# dictionary, which reads identically to "nothing was attached".
	var stats := Upscaler.stats(UserSettings)
	if stats.is_empty():
		_fail("NRR is ready but no post-process pass was attached")
		return
	if not bool(stats.get("initialised", false)):
		_fail("the pass is attached but the runtime was never created")
		return
	if not bool(stats.get("available", false)):
		_fail("the runtime was created but did not initialise: %s" % str(stats.get("error", "")))
		return
	if str(stats.get("model", "")) == "":
		_fail("the runtime initialised but loaded no model")

	_notes.append("nrr backend    : %s" % str(stats.get("backend", "")))
	_notes.append("nrr model      : %s" % str(stats.get("model", "")))
	_notes.append("nrr last error : '%s'" % str(stats.get("error", "")))
	var node := UserSettings.get_node_or_null("NRRPostProcess")
	if node != null:
		_notes.append("nrr frames out : %s" % str(node.get("_frame_index")))
	_notes.append("nrr last frame : %.2f ms, passthrough=%s"
			% [float(stats.get("render_time_ms", 0.0)), str(stats.get("passthrough", true))])

	# The assertion that matters, and it is deliberately not "NRR is upscaling".
	# Whether the runtime accepts this game's frames is a fact about the model that
	# no amount of configuration changes -- the published one takes 512x512 and this
	# game draws 768x432 -- so failing here would fail on a correct machine. What is
	# non-negotiable is that the screen does not claim an upscale it is not
	# performing: installation, operation and the sentence shown have to agree.
	var running := not bool(stats.get("passthrough", true))
	if running:
		if not report.begins_with("In use: NRR"):
			_fail("NRR is upscaling but the screen does not say so: '%s'" % report)
		_notes.append("nrr verdict    : upscaling (%s)" % report)
	else:
		if report.begins_with("In use: NRR, upscaling"):
			_fail("NRR is not upscaling and the screen says it is: '%s'" % report)
		_notes.append("nrr verdict    : declining, and the screen says so")


# ---------------------------------------------------------------------------
# The overlay and the render resolution
# ---------------------------------------------------------------------------

func _check_fps_overlay() -> void:
	var counter := FpsCounter.find(UserSettings)
	if counter == null:
		_fail("the frame counter was switched on and nothing was attached")
		return
	if not counter.visible:
		_fail("the frame counter is attached but hidden")
	var rect := counter.rect()
	var area := get_viewport().get_visible_rect().size
	if rect.size.x <= 0.0 or rect.size.y <= 0.0:
		_fail("the frame counter has no size: %s" % str(rect))
	if rect.end.x > area.x + 1.0:
		_fail("the frame counter runs off the right edge (%.1f of %.1f)"
				% [rect.end.x, area.x])
	if rect.position.y > area.y * 0.5:
		_fail("the frame counter is not in the upper half (top %.1f of %.1f)"
				% [rect.position.y, area.y])
	_notes.append("fps overlay rect %s within %s, showing '%s'"
			% [str(rect), str(area), counter.last_text])
	UserSettings.set_show_fps(false)
	if counter.visible:
		_fail("the frame counter stayed on screen with its setting off")


func _check_resolution_applied() -> void:
	var window := get_window()
	if window == null:
		return
	for id in Upscaler.RESOLUTION_IDS:
		UserSettings.set_render_resolution(id)
		var want := Upscaler.resolution_size(id)
		if window.content_scale_size != want:
			_fail("resolution '%s' did not reach the window: %s != %s"
					% [id, str(window.content_scale_size), str(want)])
	_notes.append("render resolution reached the window at all of %s"
			% str(Upscaler.RESOLUTION_IDS))

	UserSettings.set_upscaler(Upscaler.SMOOTH)
	if get_viewport().canvas_item_default_texture_filter \
			!= Viewport.DEFAULT_CANVAS_ITEM_TEXTURE_FILTER_LINEAR:
		_fail("Smooth did not switch the canvas filter to linear")
	UserSettings.set_upscaler(Upscaler.NEAREST)
	if get_viewport().canvas_item_default_texture_filter \
			!= Viewport.DEFAULT_CANVAS_ITEM_TEXTURE_FILTER_NEAREST:
		_fail("Nearest did not switch the canvas filter back to nearest")
	_notes.append("canvas filter follows the upscaler (linear for smooth, nearest otherwise)")


# ---------------------------------------------------------------------------

func _fail(message: String) -> void:
	_failures.append(message)
	printerr("FAIL: " + message)


func _finish() -> void:
	if _done:
		return
	_done = true

	print("")
	print("=== video and audio options summary ===")
	for line in _notes:
		print("  " + line)

	# Left as it was found: the shipped defaults. A check that leaves a machine on
	# half resolution and sound off changes the next one's premises.
	UserSettings.set_upscaler(Upscaler.NRR)
	UserSettings.set_render_resolution(Upscaler.DEFAULT_RESOLUTION)
	UserSettings.set_show_fps(false)
	UserSettings.set_sound(UserSettings.DEFAULT_SOUND)

	print("")
	if _failures.is_empty():
		print("PASS: every option does what the screen says")
		get_tree().quit(0)
	else:
		printerr("%d assertion(s) failed" % _failures.size())
		get_tree().quit(1)



