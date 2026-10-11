extends Node
## M1 acceptance test: run a real best-of-three match, headless, and check that
## health, rounds and signals all behave.
##
## What this is actually testing: the M1 patch to the vendored engine. Before it,
## `Player` had no health field, `GameContext` had no round concept, and
## OpenFightNode exposed no signals at all -- so this test cannot pass on an
## unpatched build, which is the point.
##
## Input is synthesised with Input.action_press() rather than real keystrokes,
## which works because OpenFightNode::readFrameInput() goes through
## InputMap::has_action() + Input::is_action_pressed().
##
## P1 walks forward into range and mashes light punch (LP -> 1punch -> HIT_H, 11
## damage). P2 intentionally does nothing, so P1 should win 2 rounds and the
## defender should be the only fighter losing health.
##
##   /Applications/Godot.app/Contents/MacOS/Godot --headless --path . \
##       res://tools/verify/m1_match.tscn

const FIGHTER_YAML := "res://data/ryu/ryu.yml"
const MOVES_YAML := "res://data/ryu/moves.yml"
const BACKGROUND := "res://data/background.png"

## 100 HP at 11 damage a hit is ~10 hits per round, two rounds, plus two 2.5s KO
## beats and the time to close distance. The cap is deliberately generous; the
## test exits as soon as the match ends.
const MAX_SECONDS := 180.0
const PUNCH_PERIOD_FRAMES := 24
const PUNCH_HOLD_FRAMES := 4

## Left untyped on purpose: OpenFightNode's members (player_one_path,
## get_health(), the signals) are not known to Node2D, and a typed declaration
## would make every one of them a static-analysis error rather than a dynamic
## lookup.
var _fight
var _elapsed := 0.0
var _frames := 0
var _done := false

# observations
var _hits := 0
var _chip_hits := 0
var _damage_seen := 0
var _attacker_wrong := 0
var _round_starts: Array = []
var _round_ends: Array = []
var _match_end := -999
var _min_health := [999, 999]
var _first_hit_logged := false
var _failures: Array = []

func _ready() -> void:
	# Uncapped headless would make each frame's delta tiny and the fixed-step
	# accumulator would starve, so pin the frame rate to the rate the engine was
	# tuned for (GAME_TIME_UPDATE_FREQ is 10ms, i.e. a 100Hz simulation).
	Engine.max_fps = 60

	if not ClassDB.class_exists("OpenFightNode"):
		_fail("OpenFightNode not registered -- build addons/openfight")
		return

	_fight = ClassDB.instantiate("OpenFightNode")
	_fight.player_one_path = FIGHTER_YAML
	_fight.player_two_path = FIGHTER_YAML
	_fight.moves_path = MOVES_YAML
	_fight.background_path = BACKGROUND
	add_child(_fight)

	# Connect after add_child but before the first process tick: setup_game()
	# already queued ROUND_STARTED, and events are drained once per tick.
	_fight.hit.connect(_on_hit)
	_fight.round_started.connect(_on_round_started)
	_fight.round_ended.connect(_on_round_ended)
	_fight.match_ended.connect(_on_match_ended)

	if not _fight.is_processing():
		_fail("setup_game() did not start processing -- GameContext::setup() returned false")
		return

	print("M1 match test started (max %.0fs)" % MAX_SECONDS)

func _process(delta: float) -> void:
	if _done:
		return

	_elapsed += delta
	_frames += 1

	_drive_input()

	# Health is polled as well as signalled, so a signal that fires while
	# get_health() disagrees is caught.
	if _fight != null and not _fight.is_match_over():
		for p in [0, 1]:
			_min_health[p] = min(_min_health[p], _fight.get_health(p))

	if _match_end != -999:
		_finish()
		return

	if _elapsed > MAX_SECONDS:
		_fail("timed out after %.0fs: hits=%d round_starts=%s round_ends=%s" % [
			_elapsed, _hits, str(_round_starts), str(_round_ends)])
		_finish()

func _drive_input() -> void:
	# Close the distance, then keep tapping light punch.
	Input.action_press("p1_right")
	Input.action_release("p1_left")

	var phase := _frames % PUNCH_PERIOD_FRAMES
	if phase == 0:
		Input.action_press("p1_a")
	elif phase == PUNCH_HOLD_FRAMES:
		Input.action_release("p1_a")

func _on_hit(attacker: int, defender: int, damage: int, blocked: bool, strength: String, state: String) -> void:
	_hits += 1
	_damage_seen += damage
	if blocked:
		_chip_hits += 1
	# P2 is idle, so every registered hit must be P1 attacking P2.
	if attacker != 0 or defender != 1:
		_attacker_wrong += 1

	if not _first_hit_logged:
		_first_hit_logged = true
		print("first hit: attacker=%d defender=%d damage=%d blocked=%s strength=%s state=%s -> p2 health=%d" % [
			attacker, defender, damage, str(blocked), strength, state, _fight.get_health(1)])

func _on_round_started(round_number: int) -> void:
	_round_starts.append(round_number)
	print("round %d started (p1=%d p2=%d hp)" % [round_number, _fight.get_health(0), _fight.get_health(1)])

func _on_round_ended(winner: int, time_over: bool) -> void:
	_round_ends.append({"winner": winner, "time_over": time_over})
	print("round ended: winner=%d time_over=%s wins=(%d,%d) health=(%d,%d)" % [
		winner, str(time_over), _fight.get_round_wins(0), _fight.get_round_wins(1),
		_fight.get_health(0), _fight.get_health(1)])

func _on_match_ended(winner: int) -> void:
	_match_end = winner
	print("match ended: winner=%d after %d hits" % [winner, _hits])

func _fail(message: String) -> void:
	_failures.append(message)
	printerr("FAIL: " + message)

func _finish() -> void:
	_done = true
	Input.action_release("p1_right")
	Input.action_release("p1_a")

	if _hits == 0:
		_fail("no hit signal was ever emitted")
	if _attacker_wrong > 0:
		_fail("%d hits reported the wrong attacker/defender pair" % _attacker_wrong)
	if _damage_seen <= 0:
		_fail("hits carried no damage")
	if _min_health[1] >= 100:
		_fail("defender health never dropped (min %d)" % _min_health[1])
	if _min_health[0] < 100:
		_fail("attacker lost health (%d) -- P2 was idle, so it never attacked" % _min_health[0])
	if _round_ends.is_empty():
		_fail("no round ever ended")
	if _round_starts.size() < 2:
		_fail("round 2 never started (round_started fired %d times)" % _round_starts.size())
	if _match_end == -999:
		_fail("match never ended")

	print("")
	print("=== M1 match test summary ===")
	print("  elapsed        : %.1fs (%d frames)" % [_elapsed, _frames])
	print("  hits           : %d (%d blocked, %d total damage)" % [_hits, _chip_hits, _damage_seen])
	print("  rounds started : %s" % str(_round_starts))
	print("  rounds ended   : %s" % str(_round_ends))
	print("  final wins     : (%d, %d)" % [_fight.get_round_wins(0), _fight.get_round_wins(1)])
	print("  match winner   : %d" % _match_end)
	print("  min health     : p1=%d p2=%d" % [_min_health[0], _min_health[1]])

	if _failures.is_empty():
		print("PASS: hits, damage, round rotation and match end all behaved")
		get_tree().quit(0)
	else:
		printerr("%d assertion(s) failed" % _failures.size())
		get_tree().quit(1)

