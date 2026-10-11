extends MenuScreen
## Everything the options screen can change, in one page.
##
## Video first, because it is the one thing on this page a player can see the effect
## of immediately, and because the upscaler is the setting with a real story behind
## it: the game ships choosing the neural path and says plainly when the machine
## cannot run it.
##
## What is *not* here matters as much. Rounds per match and the round clock length
## are compile-time constants in the engine patch (GameContext::ROUNDS_TO_WIN,
## ROUND_TIME_MS). Putting a toggle for them in this menu would be a control that
## silently does nothing, which is worse than not offering it, so they are absent
## until the engine exposes them.
##
## Every item is chosen rather than toggled with a second key: pressing the item
## again moves it to its next value. That is one control per setting, it behaves
## identically on a keyboard and a pad, and the label always shows where it landed.

func _configure() -> void:
	back_screen = "title"
	items = [
		{"id": "upscaler", "label": "", "detail": ""},
		{"id": "resolution", "label": "", "detail": ""},
		{"id": "fps", "label": "", "detail": ""},
		{"id": "sound", "label": "", "detail": ""},
		{"id": "fullscreen", "label": "", "detail": ""},
		{"id": "vsync", "label": "", "detail": ""},
		{"id": "back", "label": "BACK", "detail": "Return to the title screen."},
	]
	footer = "Applied immediately and saved to user://settings.cfg"
	for item in items:
		refresh(str(item["id"]))


## One item, brought up to date from the live settings. Called after every change so
## the screen cannot describe a state the game is not in.
func refresh(id: String) -> void:
	match id:
		"upscaler":
			set_item_label(id, "UPSCALER:  %s" % Upscaler.label(UserSettings.upscaler))
			set_item_detail(id, _upscaler_detail())
		"resolution":
			set_item_label(id, "RENDER RESOLUTION:  %s"
					% Upscaler.resolution_label(UserSettings.render_resolution))
			set_item_detail(id, _resolution_detail())
		"fps":
			set_item_label(id, "FPS COUNTER:  %s" % ("ON" if UserSettings.show_fps else "OFF"))
			set_item_detail(id,
					"Shows the frame rate in the upper right corner of the render window.\n"
					+ "Off by default: it is a diagnostic, and a diagnostic nobody can turn "
					+ "off is a watermark.")
		"sound":
			set_item_label(id, UserSettings.sound_label())
			set_item_detail(id, _sound_detail())
		"fullscreen":
			set_item_label(id, "FULLSCREEN:  %s" % ("ON" if UserSettings.fullscreen else "OFF"))
			set_item_detail(id, "Borderless fullscreen.")
		"vsync":
			set_item_label(id, "V-SYNC:  %s" % ("ON" if UserSettings.vsync_enabled else "OFF"))
			set_item_detail(id,
					"Vertical sync. Off allows tearing in exchange for a shorter input "
					+ "delay, which a fighting game notices.")
		_:
			pass

## The upscaler's line says what is set *and* what is running, because they are not
## always the same thing and only one of them is a fact about this machine.
func _upscaler_detail() -> String:
	var lines := [Upscaler.report(UserSettings.upscaler, UserSettings)]
	var active := UserSettings.active_upscaler
	if active != "" and active != UserSettings.upscaler:
		lines.append("Running as: %s." % Upscaler.label(active))
	lines.append("Choose again to cycle %s." % ", ".join(Upscaler.MODES))
	return "\n".join(lines)


func _resolution_detail() -> String:
	return ("The size the game is drawn at, before anything enlarges it to fit the "
			+ "window. This is what the upscaler has to reconstruct from, so it is the "
			+ "one control here that buys frame time: lower it and the neural pass has "
			+ "more to do, not less.\nChoose again to cycle the sizes.")


## The honest version. The game has no cues yet, and this says so rather than
## letting a silence be mistaken for the setting working.
func _sound_detail() -> String:
	var running := "The master bus is muted." if not UserSettings.sound_is_on() \
			else "The master bus is at %.0f dB." % UserSettings.sound_db()
	return ("%s\nThe game has no audio cues yet, so this is the gain the first one "
			% running) + "will be played at rather than something you can hear today.\n" \
			+ "Choose again to cycle off, low and full."


func on_chosen(id: String) -> bool:
	match id:
		"upscaler":
			UserSettings.set_upscaler(Upscaler.cycle_mode(UserSettings.upscaler, 1))
		"resolution":
			UserSettings.set_render_resolution(
					Upscaler.cycle_resolution(UserSettings.render_resolution, 1))
		"fps":
			UserSettings.set_show_fps(not UserSettings.show_fps)
		"sound":
			UserSettings.set_sound(_next_sound())
		"fullscreen":
			UserSettings.set_fullscreen(not UserSettings.fullscreen)
		"vsync":
			UserSettings.set_vsync(not UserSettings.vsync_enabled)
		"back":
			GameState.goto("title")
		_:
			return false
	refresh(id)
	return true


func _next_sound() -> String:
	var index := UserSettings.SOUND_LEVELS.find(UserSettings.sound)
	if index < 0:
		index = 0
	return UserSettings.SOUND_LEVELS[posmod(index + 1, UserSettings.SOUND_LEVELS.size())]
