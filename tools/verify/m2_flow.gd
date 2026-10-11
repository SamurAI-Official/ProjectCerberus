extends Control
## M2 acceptance test: the whole menu flow, headless.
##
## This is M2's real criterion -- "Title -> CharSelect -> StageSelect -> Match ->
## Results -> rematch, no dead ends" -- so it drives the flow the way the UI does,
## by calling each screen's activation handler, and asserts on which screen comes
## up next. No window, no input device, no pixels.
##
## It also covers the two things that break quietly: that InputBindings is
## idempotent (a second application must add nothing, or every launch would stack
## duplicate events), and that UserSettings round-trips through disk.
##
## The test node is the flow host, so screens are added as its children.
##
##   /Applications/Godot.app/Contents/MacOS/Godot --headless --path . \
##       res://tools/verify/m2_flow.tscn

const MAX_MATCH_SECONDS := 90.0
const RESULT_GRACE_SECONDS := 18.0
const PUNCH_PERIOD_FRAMES := 24
const PUNCH_HOLD_FRAMES := 4

var _frames := 0
var _elapsed := 0.0
var _phase := "starting"
var _done := false
var _failures: Array = []
var _match_finished := -999
var _match_node: Node = null

func _ready() -> void:
	Engine.max_fps = 60
	GameState.attach_host(self)

	if not ClassDB.class_exists("OpenFightNode"):
		_fail("OpenFightNode is not registered")
		_finish()
		return

	_check_manifest_loaded()
	_check_input_bindings()
	_check_settings_roundtrip()
	_check_flow_into_match()

	if _failures.is_empty() and _phase == "match":
		print("M2 flow test: reached the match; playing it out")
	else:
		_finish()

func _process(delta: float) -> void:
	if _done:
		return

	_elapsed += delta
	_frames += 1

	if _phase == "match":
		_drive_input()
		if _match_finished != -999:
			_phase = "post_match"
			_note("match reported winner %d" % _match_finished)
		elif _elapsed > MAX_MATCH_SECONDS:
			_fail("the match did not finish within %.0fs" % MAX_MATCH_SECONDS)
			_finish()
		return

	if _phase == "post_match":
		if GameState.current_screen == "results":
			_check_results()
			_finish()
		elif _elapsed > MAX_MATCH_SECONDS + RESULT_GRACE_SECONDS:
			# MatchController only hands off when a flow host is attached; here
			# there is one, so this means the handoff itself is broken.
			_fail("the match never handed off to the results screen")
			_finish()

func _drive_input() -> void:
	Input.action_press("p1_right")
	Input.action_release("p1_left")
	var phase := _frames % PUNCH_PERIOD_FRAMES
	if phase == 0:
		Input.action_press("p1_a")
	elif phase == PUNCH_HOLD_FRAMES:
		Input.action_release("p1_a")

func _fail(message: String) -> void:
	_failures.append(message)
	printerr("FAIL: " + message)

func _note(message: String) -> void:
	print("  " + message)

func _expect_screen(expected: String) -> bool:
	if GameState.current_screen != expected:
		_fail("expected screen '%s', flow is on '%s'" % [expected, GameState.current_screen])
		return false
	return true

# --- individual checks ------------------------------------------------------

func _check_manifest_loaded() -> void:
	if GameState.fighters.is_empty():
		_fail("the fighter manifest did not load")
	else:
		_note("roster: %d entr(ies), first is '%s'" % [GameState.fighters.size(), GameState.fighter_name(0)])

	if GameState.stages.is_empty():
		_fail("the stage manifest did not load")
	else:
		_note("stages: %d entr(ies), first is '%s'" % [GameState.stages.size(), GameState.stage_name()])

func _check_input_bindings() -> void:
	var sampled := ["p1_up", "p1_down", "p1_left", "p1_right", "p1_a", "p1_z", "p2_up",
			"p2_down", "p2_left", "p2_right", "p2_a", "p2_z"]
	var unbound: Array = []

	for action in sampled:
		if not InputMap.has_action(action):
			unbound.append(action + " (missing action)")
			continue

		var has_pad := false
		for event in InputMap.action_get_events(action):
			if event is InputEventJoypadButton or event is InputEventJoypadMotion:
				has_pad = true
				break
		if not has_pad:
			unbound.append(action)

	if unbound.is_empty():
		_note("gamepad bindings present on all %d sampled actions" % sampled.size())
	else:
		_fail("no gamepad binding on: " + ", ".join(unbound))

	# Idempotency matters: InputBindings runs on every launch, so a non-idempotent
	# version would stack a duplicate event onto every action each time.
	var second_pass := InputBindings.apply_defaults()
	if second_pass != 0:
		_fail("InputBindings.apply_defaults() added %d event(s) on a second run" % second_pass)
	else:
		_note("InputBindings is idempotent (second run added 0 events)")

func _check_settings_roundtrip() -> void:
	var original: bool = UserSettings.vsync_enabled
	UserSettings.set_vsync(not original)

	var config := ConfigFile.new()
	if config.load(UserSettings.PATH) != OK:
		_fail("settings were not written to %s" % UserSettings.PATH)
	else:
		var stored: bool = config.get_value("display", "vsync", original)
		if stored == original:
			_fail("settings did not round-trip: wrote %s, read back %s" % [str(not original), str(stored)])
		else:
			_note("settings round-trip through %s" % UserSettings.PATH)

	UserSettings.set_vsync(original)

func _check_flow_into_match() -> void:
	if not GameState.goto("title"):
		_fail("goto('title') refused")
		return
	if not _expect_screen("title"):
		return

	var title := GameState.current_screen_node()
	if not (title is MenuScreen):
		_fail("the title screen is not a MenuScreen")
		return

	title.on_chosen("play")
	if not _expect_screen("char_select"):
		return

	# Both picks happen on the same screen, which is why this node is reused.
	var select := GameState.current_screen_node()
	select.on_chosen("0")
	if GameState.picks[0] != 0:
		_fail("player 1's pick was not recorded")
	if not _expect_screen("char_select"):
		return

	select.on_chosen("0")
	if GameState.picks[1] != 0:
		_fail("player 2's pick was not recorded")
	if not _expect_screen("stage_select"):
		return

	var stages := GameState.current_screen_node()
	stages.on_chosen("0")
	if not _expect_screen("match"):
		return

	_match_node = GameState.current_screen_node()
	if _match_node == null:
		_fail("the match screen did not instantiate")
		return
	if not _match_node.has_signal("match_finished"):
		_fail("the match screen has no match_finished signal")
		return

	_match_node.match_finished.connect(func(winner: int) -> void: _match_finished = winner)
	_phase = "match"
	_note("flow reached the match: title -> char select x2 -> stage select -> match")

func _check_results() -> void:
	var result: Dictionary = GameState.last_result
	if not bool(result.get("played", false)):
		_fail("GameState.last_result was not recorded when the match ended")
		return

	var winner := int(result.get("winner", -1))
	if winner != _match_finished:
		_fail("last_result winner %d disagrees with the match_finished signal %d" % [winner, _match_finished])
	else:
		_note("last_result agrees with the signal: winner %d" % winner)

	var wins: Array = result.get("wins", [0, 0])
	var total := int(wins[0]) if wins.size() > 0 else 0
	total += int(wins[1]) if wins.size() > 1 else 0
	if total != 2:
		_fail("a finished best-of-three should total 2 round wins, got %d (%s)" % [total, str(wins)])
	else:
		_note("round wins total 2: %s" % str(wins))

	if str(result.get("p1", "")).is_empty() or str(result.get("stage", "")).is_empty():
		_fail("last_result is missing the fighter or stage names: %s" % str(result))

	var screen := GameState.current_screen_node()
	if not (screen is MenuScreen):
		_fail("the results screen is not a MenuScreen")
		return
	_note("results screen heading: '%s'" % screen.heading)

	# Rematch is the last hop in the loop, and the one a player hits most.
	screen.on_chosen("rematch")
	if not _expect_screen("match"):
		return
	_note("rematch re-entered the match")

func _finish() -> void:
	if _done:
		return
	_done = true

	Input.action_release("p1_right")
	Input.action_release("p1_a")

	print("")
	print("=== M2 flow test summary ===")
	print("  elapsed     : %.1fs (%d frames)" % [_elapsed, _frames])
	print("  final screen: %s" % GameState.current_screen)
	print("  picks       : %s" % str(GameState.picks))
	print("  last result : winner=%d wins=%s" % [
		int(GameState.last_result.get("winner", -1)), str(GameState.last_result.get("wins", []))])

	if _failures.is_empty():
		print("PASS: full menu flow with no dead ends")
		get_tree().quit(0)
	else:
		printerr("%d assertion(s) failed" % _failures.size())
		get_tree().quit(1)

