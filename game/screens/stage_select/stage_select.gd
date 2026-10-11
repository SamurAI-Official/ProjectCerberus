extends MenuScreen
## Stage select, then straight into the match.

func _configure() -> void:
	back_screen = "char_select"
	items = []

	for i in GameState.stages.size():
		var stage: Dictionary = GameState.stages[i]
		items.append({
			"id": str(i),
			"label": str(stage.get("name", "?")),
			"detail": str(stage.get("detail", "")),
		})

	if items.is_empty():
		items.append({"id": "-1", "label": "NO STAGES IN MANIFEST", "disabled": true})

func _after_build() -> void:
	set_heading("SELECT STAGE")
	set_footer("%s  vs  %s" % [GameState.fighter_name(0), GameState.fighter_name(1)])

func on_chosen(id: String) -> bool:
	if GameState.stages.is_empty():
		return false

	GameState.stage_index = int(id)
	GameState.goto("match")
	return true
