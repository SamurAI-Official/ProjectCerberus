extends Node
## Persisted user settings.
##
## Deliberately small, and deliberately only display options. Gameplay settings
## that a fighting game normally exposes -- rounds per match, the round clock
## length -- live in the engine patch as compile-time constants
## (GameContext::ROUNDS_TO_WIN, ROUND_TIME_MS). Offering a menu toggle for those
## would be a control that silently does nothing, which is worse than not
## offering it. They need engine support first; until then they are not in the
## menu.
##
## Named UserSettings rather than Settings so it can never be confused with
## Godot's ProjectSettings.

const PATH := "user://settings.cfg"

var fullscreen := false
var vsync_enabled := true

func _ready() -> void:
	load_from_disk()
	apply()

func load_from_disk() -> void:
	var config := ConfigFile.new()

	# A missing file is the normal first run, not an error: defaults stand.
	if config.load(PATH) != OK:
		return

	fullscreen = config.get_value("display", "fullscreen", fullscreen)
	vsync_enabled = config.get_value("display", "vsync", vsync_enabled)

func save_to_disk() -> Error:
	var config := ConfigFile.new()
	config.set_value("display", "fullscreen", fullscreen)
	config.set_value("display", "vsync", vsync_enabled)
	return config.save(PATH)

func apply() -> void:
	# The headless DisplayServer has no window to configure, and asking it to
	# change window mode is noise in CI rather than a failure.
	if DisplayServer.get_name() == "headless":
		return

	DisplayServer.window_set_mode(
			DisplayServer.WINDOW_MODE_FULLSCREEN if fullscreen else DisplayServer.WINDOW_MODE_WINDOWED)
	DisplayServer.window_set_vsync_mode(
			DisplayServer.VSYNC_ENABLED if vsync_enabled else DisplayServer.VSYNC_DISABLED)

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
