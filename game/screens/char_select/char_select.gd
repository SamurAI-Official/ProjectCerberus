extends MenuScreen
## Fighter select: player 1 picks, then player 2, then on to stage select.
##
## One list used twice rather than two side-by-side panels. Two panels would be
## four mostly-empty boxes against a one-fighter dev roster, and picking in
## sequence is what a couch player expects anyway -- it stays one tap per player
## whatever the roster size grows to.

const PLAYERS := 2

var _choosing := 0

func _configure() -> void:
	back_screen = "title"
	items = []

	for i in GameState.fighters.size():
		var fighter: Dictionary = GameState.fighters[i]
		items.append({
			"id": str(i),
			"label": str(fighter.get("name", "?")),
			"detail": str(fighter.get("detail", "")),
		})

	if items.is_empty():
		# A disabled item rather than an empty screen, so the failure is visible
		# in the UI instead of looking like a hung menu.
		items.append({"id": "-1", "label": "NO FIGHTERS IN MANIFEST", "disabled": true})

func _after_build() -> void:
	_sync_labels()

func _sync_labels() -> void:
	set_heading("PLAYER %d - SELECT FIGHTER" % (_choosing + 1))
	if _choosing == 0 and GameState.fighters.size() > 1:
		set_footer("Player 1 picks first.")
	elif _choosing == 0:
		set_footer("The roster holds one fighter, so this pick is the only option. It grows in M3.")
	else:
		set_footer("Player 2 picks. Both players may pick the same fighter.")

func on_chosen(id: String) -> bool:
	if GameState.fighters.is_empty():
		return false

	GameState.picks[_choosing] = int(id)

	if _choosing < PLAYERS - 1:
		_choosing += 1
		_sync_labels()
		focus_first()
		return true

	GameState.goto("stage_select")
	return true
