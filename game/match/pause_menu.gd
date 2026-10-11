extends MenuScreen
## In-match pause overlay.
##
## While this is up the scene tree is paused, and this node runs in
## PROCESS_MODE_WHEN_PAUSED so the menu still responds. OpenFightNode keeps the
## default inherit mode, so the match stops stepping -- which is what a pause
## should do, and it means nothing has to be added to the engine for it.
##
## It reports intent through a signal rather than acting on the match directly.
## The menu should not know how to restart a match; MatchController owns that.

signal requested(action: String)

func _configure() -> void:
	process_mode = Node.PROCESS_MODE_WHEN_PAUSED
	background_color = Color(0.02, 0.02, 0.03, 0.82)
	heading = "PAUSED"
	items = [
		{"id": "resume", "label": "RESUME", "detail": "Back to the match."},
		{"id": "restart", "label": "RESTART MATCH", "detail": "Reset both fighters and the round count."},
		{"id": "quit", "label": "QUIT TO TITLE", "detail": "Abandon the match."},
	]
	footer = "ESC resumes."

func on_chosen(id: String) -> bool:
	requested.emit(id)
	return true
