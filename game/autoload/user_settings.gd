extends Node
## Persisted user settings: the whole of what the options screen can change.
##
## Deliberately all presentation and no gameplay. The settings a fighting game
## normally exposes that are *not* here -- rounds per match, the round clock length
## -- live in the engine patch as compile-time constants
## (GameContext::ROUNDS_TO_WIN, ROUND_TIME_MS). Offering a menu toggle for those
## would be a control that silently does nothing, which is worse than not offering
## it. They need engine support first; until then they are not in the menu.
##
## Audio is the one setting here whose subject matter is thin, and it says so where
## it is offered rather than in a comment nobody reads: the game has no audio cues
## yet, so this is the gain the first one will be played at. It is a real control on
## a real bus -- not a control that does nothing, a control with nothing on the
## other end yet -- and the note on the options screen is what keeps that visible.
##
## Named UserSettings rather than Settings so it can never be confused with Godot's
## ProjectSettings.

const PATH := "user://settings.cfg"

const SOUND_LEVELS := ["off", "low", "full"]
const DEFAULT_SOUND := "full"
## Quiet is -14 dB: loud enough to punctuate a blow, quiet enough to sit under
## anything else somebody has playing.
const LOW_DB := -14.0

var fullscreen := false
var vsync_enabled := true
var upscaler := Upscaler.NRR
var render_resolution := Upscaler.DEFAULT_RESOLUTION
var show_fps := false
var sound := DEFAULT_SOUND

## The mode the picture is actually being presented with, which is not always the
## one that was asked for -- see Upscaler.apply(). Kept because "NRR is selected"
## and "NRR is running" are different claims and the options screen has to be able
## to tell them apart.
var active_upscaler := ""

func _ready() -> void:
	load_from_disk()
	apply()

func load_from_disk() -> void:
	var config := ConfigFile.new()

	# A missing file is the normal first run, not an error: defaults stand.
	if config.load(PATH) != OK:
		return

	fullscreen = bool(config.get_value("display", "fullscreen", fullscreen))
	vsync_enabled = bool(config.get_value("display", "vsync", vsync_enabled))
	show_fps = bool(config.get_value("display", "show_fps", show_fps))

	# A hand-edited or corrupt file must not be trusted into a mode that does not
	# exist. An unknown upscaler falls back to the default rather than being passed
	# through to a branch that would read it as "not NRR" and quietly pick nearest
	# while the file still claimed otherwise.
	var saved_upscaler := str(config.get_value("video", "upscaler", upscaler))
	upscaler = saved_upscaler if Upscaler.MODES.has(saved_upscaler) else Upscaler.NRR

	var saved_resolution := str(config.get_value("video", "resolution", render_resolution))
	render_resolution = saved_resolution if Upscaler.RESOLUTION_IDS.has(saved_resolution) \
			else Upscaler.DEFAULT_RESOLUTION

	var saved_sound := str(config.get_value("audio", "level", sound))
	sound = saved_sound if SOUND_LEVELS.has(saved_sound) else DEFAULT_SOUND

func save_to_disk() -> Error:
	var config := ConfigFile.new()
	config.set_value("display", "fullscreen", fullscreen)
	config.set_value("display", "vsync", vsync_enabled)
	config.set_value("display", "show_fps", show_fps)
	config.set_value("video", "upscaler", upscaler)
	config.set_value("video", "resolution", render_resolution)
	config.set_value("audio", "level", sound)
	return config.save(PATH)

## Puts every setting on the running game. Called at startup and after each change,
## because a setting that has been chosen and not applied is a setting the player
## cannot see.
##
## The viewport settings are applied even headless. They are viewport settings, not
## window-mode settings -- a headless run still has a window object and a viewport --
## and a check that could only observe them on a machine with a display would be a
## check nobody runs. What it cannot do headless is attach the neural pass, which
## `Upscaler.apply()` decides for itself and reports through `active_upscaler`.
func apply() -> void:
	active_upscaler = Upscaler.apply(upscaler, self, render_resolution)
	_apply_audio()

	# The frame counter is attached here, to the settings owner, rather than to the
	# flow host. A frame rate is a fact about the program, not about the screen you
	# are on, so it must be up before the first screen and outlive the last one --
	# and a host that a screen can replace is neither of those things.
	FpsCounter.set_shown(self, show_fps)

	# The headless DisplayServer has no window to configure, and asking it to change
	# window mode is noise in CI rather than a failure.
	if DisplayServer.get_name() == "headless":
		return

	DisplayServer.window_set_mode(
			DisplayServer.WINDOW_MODE_FULLSCREEN if fullscreen else DisplayServer.WINDOW_MODE_WINDOWED)
	DisplayServer.window_set_vsync_mode(
			DisplayServer.VSYNC_ENABLED if vsync_enabled else DisplayServer.VSYNC_DISABLED)


# ---------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------

## The master bus, which is where a volume control belongs: everything the game
## ever plays is routed through it, so nothing has to be added here when the first
## cue is.
func _apply_audio() -> void:
	var bus := AudioServer.get_bus_index("Master")
	if bus < 0:
		return
	AudioServer.set_bus_mute(bus, sound == "off")
	AudioServer.set_bus_volume_db(bus, sound_db())


func sound_is_on() -> bool:
	return sound != "off"


func sound_db() -> float:
	return LOW_DB if sound == "low" else 0.0


func sound_label() -> String:
	return "SOUND:  %s" % sound.to_upper()


# ---------------------------------------------------------------------------
# Setters. Each applies and then saves, in that order, so the file never records a
# state the running game is not in.
# ---------------------------------------------------------------------------

func set_fullscreen(value: bool) -> void:
	if fullscreen == value:
		return
	fullscreen = value
	apply()
	save_to_disk()

func set_vsync(value: bool) -> void:
	if vsync_enabled == value:
		return
	vsync_enabled = value
	apply()
	save_to_disk()

## Returns the mode actually in use, which is not always the one asked for.
func set_upscaler(value: String) -> String:
	upscaler = value if Upscaler.MODES.has(value) else Upscaler.NRR
	apply()
	save_to_disk()
	return active_upscaler

func set_render_resolution(value: String) -> void:
	render_resolution = value if Upscaler.RESOLUTION_IDS.has(value) else Upscaler.DEFAULT_RESOLUTION
	apply()
	save_to_disk()

func set_show_fps(value: bool) -> void:
	show_fps = value
	apply()
	save_to_disk()

func set_sound(value: String) -> String:
	sound = value if SOUND_LEVELS.has(value) else DEFAULT_SOUND
	_apply_audio()
	save_to_disk()
	return sound

