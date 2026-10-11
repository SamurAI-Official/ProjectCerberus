extends MenuScreen
## Display options -- and only display options.
##
## Rounds per match and the round clock length are compile-time constants in the
## engine patch (GameContext::ROUNDS_TO_WIN, ROUND_TIME_MS). Putting a toggle for
## them in this menu would be a control that silently does nothing, which is
## worse than not offering it, so they are absent until the engine exposes them.

func _configure() -> void:
	back_screen = "title"
	items = [
		{"id": "fullscreen", "label": _fullscreen_label(), "detail": "Toggle borderless fullscreen."},
		{"id": "vsync", "label": _vsync_label(), "detail": "Toggle vertical sync."},
		{"id": "back", "label": "BACK", "detail": "Return to the title screen."},
	]
	footer = "Applied immediately and saved to user://settings.cfg"

func _fullscreen_label() -> String:
	return "FULLSCREEN:  ON" if UserSettings.fullscreen else "FULLSCREEN:  OFF"

func _vsync_label() -> String:
	return "V-SYNC:  ON" if UserSettings.vsync_enabled else "V-SYNC:  OFF"

func on_chosen(id: String) -> bool:
	match id:
		"fullscreen":
			UserSettings.set_fullscreen(not UserSettings.fullscreen)
			set_item_label("fullscreen", _fullscreen_label())
		"vsync":
			UserSettings.set_vsync(not UserSettings.vsync_enabled)
			set_item_label("vsync", _vsync_label())
		"back":
			GameState.goto("title")
		_:
			return false
	return true
