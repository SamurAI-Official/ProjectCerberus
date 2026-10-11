extends Node
## M2 acceptance test: the match HUD tracks the engine.
##
## Headless, so nothing is drawn -- what is checked is that the HUD's *state*
## follows the engine's signals, which is where HUD bugs actually live. Pixels
## are covered by m0_render.tscn (engine transparency) and by running the match
## scene for real.
##
## Drives the same synthetic input as the M1 test: P1 walks in and mashes light
## punch, P2 idles, so P1 should take two rounds and the HUD should follow.
##
##   /Applications/Godot.app/Contents/MacOS/Godot --headless --path . \
##       res://tools/verify/m2_hud.tscn

const SCENE := "res://game/screens/match/match.tscn"
const MAX_SECONDS := 120.0
const PUNCH_PERIOD_FRAMES := 24
const PUNCH_HOLD_FRAMES := 4

var _match: Node
var _bar1
var _bar2
var _announcer
var _round_label: Label
var _timer_label: Label
var _result_label: Label

var _elapsed := 0.0
var _frames := 0
var _done := false
var _finished_winner := -999
var _announcements: Array = []
var _round_labels: Array = []
var _timer_values: Array = []
var _min_target := [999, 999]
var _failures: Array = []

func _ready() -> void:
	Engine.max_fps = 60

	if not ClassDB.class_exists("OpenFightNode"):
		_fail("OpenFightNode not registered")
		_finish()
		return

	_match = load(SCENE).instantiate()
	add_child(_match)

	# add_child() has run the subtree's _ready(), so the controller has already
	# connected to the engine and these paths resolve.
	_bar1 = _match.get_node("HUD/P1Health")
	_bar2 = _match.get_node("HUD/P2Health")
	_announcer = _match.get_node("HUD/Announcer")
	_round_label = _match.get_node("HUD/RoundLabel")
	_timer_label = _match.get_node("HUD/TimerLabel")
	_result_label = _match.get_node("HUD/Result")

	_match.match_finished.connect(_on_match_finished)
	print("M2 HUD test started")

func _process(delta: float) -> void:
	if _done:
		return

	_elapsed += delta
	_frames += 1

	Input.action_press("p1_right")
	Input.action_release("p1_left")
	var phase := _frames % PUNCH_PERIOD_FRAMES
	if phase == 0:
		Input.action_press("p1_a")
	elif phase == PUNCH_HOLD_FRAMES:
		Input.action_release("p1_a")

	_sample()

	if _finished_winner != -999:
		# The controller announces the winner on match end; give the announcer a
		# moment to have actually shown it before asserting.
		if _elapsed > 0.0 and _announcer.last_message.begins_with("PLAYER"):
			_finish()
			return

	if _elapsed > MAX_SECONDS:
		_fail("timed out after %.0fs" % _elapsed)
		_finish()

func _sample() -> void:
	if _match == null:
		return

	for i in [0, 1]:
		var bar = _bar1 if i == 0 else _bar2
		_min_target[i] = min(_min_target[i], bar.target_health)

	var label := _round_label.text
	if not label.is_empty() and not _round_labels.has(label):
		_round_labels.append(label)

	var t := _timer_label.text
	if not t.is_empty() and not _timer_values.has(t):
		_timer_values.append(t)

	var msg: String = _announcer.last_message
	if not msg.is_empty() and not _announcements.has(msg):
		_announcements.append(msg)

func _on_match_finished(winner: int) -> void:
	_finished_winner = winner

func _fail(message: String) -> void:
	_failures.append(message)
	printerr("FAIL: " + message)

func _finish() -> void:
	if _done:
		return
	_done = true
	Input.action_release("p1_right")
	Input.action_release("p1_a")

	if _min_target[1] >= 100:
		_fail("P2's health bar never moved (min target %d)" % _min_target[1])
	if _min_target[0] < 100:
		_fail("P1's health bar moved (%d) but P1 was the only fighter acting" % _min_target[0])
	if not _round_labels.has("ROUND 2"):
		_fail("round label never reached ROUND 2 (saw %s)" % str(_round_labels))
	if _timer_values.size() < 2:
		_fail("the round clock never changed (saw %s)" % str(_timer_values))
	if not _announcements.has("ROUND 1"):
		_fail("never announced ROUND 1 (saw %s)" % str(_announcements))
	if _announcements.filter(func(m): return m.begins_with("PLAYER") and m.ends_with("WINS")).is_empty():
		_fail("never announced a winner (saw %s)" % str(_announcements))
	if _result_label.text != "PLAYER 1 WINS":
		_fail("result label reads '%s', expected 'PLAYER 1 WINS'" % _result_label.text)
	if _finished_winner != 0:
		_fail("match_finished reported winner %d, expected 0" % _finished_winner)

	print("")
	print("=== M2 HUD test summary ===")
	print("  elapsed       : %.1fs (%d frames)" % [_elapsed, _frames])
	print("  bar target min: p1=%d p2=%d" % [_min_target[0], _min_target[1]])
	print("  round labels  : %s" % str(_round_labels))
	print("  timer samples : %d distinct (first=%s last=%s)" % [
		_timer_values.size(), _timer_values[0] if _timer_values.size() > 0 else "-",
		_timer_values[-1] if _timer_values.size() > 0 else "-"])
	print("  announcements : %s" % str(_announcements))
	print("  result label  : '%s'" % _result_label.text)
	print("  winner        : %d" % _finished_winner)

	if _failures.is_empty():
		print("PASS: health, rounds, clock and announcements all tracked the engine")
		get_tree().quit(0)
	else:
		printerr("%d assertion(s) failed" % _failures.size())
		get_tree().quit(1)
