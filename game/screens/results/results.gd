extends MenuScreen
## Post-match summary.
##
## Reads GameState.last_result, which MatchController wrote when the engine
## reported MATCH_ENDED. Reporting through GameState rather than through a signal
## is deliberate: the results screen can then be opened at any time (including
## directly by a test) and it still tells the truth about the last match.

func _configure() -> void:
	var result: Dictionary = GameState.last_result
	var winner := int(result.get("winner", -1))
	var wins: Array = result.get("wins", [0, 0])

	items = [
		{"id": "rematch", "label": "REMATCH", "detail": "Same fighters, same stage."},
		{"id": "characters", "label": "CHARACTER SELECT", "detail": "Change fighters."},
		{"id": "title", "label": "TITLE SCREEN", "detail": "Back to the main menu."},
	]

	if not bool(result.get("played", false)):
		set_heading("NO MATCH PLAYED")
		footer = "Play a match to see a result here."
		return

	if winner < 0:
		set_heading("DRAW GAME")
	else:
		set_heading("PLAYER %d WINS" % (winner + 1))

	footer = "%s %d - %d %s        %s        %d round(s)" % [
		str(result.get("p1", "-")), int(wins[0]), int(wins[1]),
		str(result.get("p2", "-")), str(result.get("stage", "-")),
		int(result.get("rounds", 0)),
	]

func on_chosen(id: String) -> bool:
	match id:
		"rematch":
			GameState.goto("match")
		"characters":
			GameState.goto("char_select")
		"title":
			GameState.goto("title")
		_:
			return false
	return true
