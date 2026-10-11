extends MenuScreen
## Title screen -- the entry point of the flow.

func _configure() -> void:
	heading = "PROJECT CERBERUS"
	items = [
		{"id": "play", "label": "PLAY", "detail": "Local versus. Best of three rounds."},
		{"id": "options", "label": "OPTIONS", "detail": "Display settings."},
		{"id": "quit", "label": "QUIT", "detail": "Leave the game."},
	]
	footer = ("P1  S/Z/X/C move,  J/K/L and M/,/. attack        "
			+ "P2  arrows + numpad        Gamepads: P1 uses pad 1, P2 uses pad 2")

func on_chosen(id: String) -> bool:
	match id:
		"play":
			GameState.goto("char_select")
		"options":
			GameState.goto("options")
		"quit":
			get_tree().quit()
		_:
			return false
	return true
