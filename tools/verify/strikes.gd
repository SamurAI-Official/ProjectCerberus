extends Control
## Which attack does each button actually produce, and does a chain connect?
##
## The defender's damage identifies the attacker's state without needing to read
## it: the engine's table gives HIT_L 4, HIT_M 7, KNOCK_DOWN 10 and HIT_H 11, and
## each of the six normals carries a distinct one. So a button that reaches the
## wrong state shows up as the wrong number -- the cheapest instrument for
## calibrating a moveset, and the only one that works from outside the engine.
##
## Then it tries a chain, because the chain is the part that cannot be checked from
## the data: `combo: true` and the `from` lists say a jab MAY be cancelled into a
## straight, and only the running game says whether it does.
##
## Windowed on purpose. The engine steps every 10 ms and a headless Godot frame is
## about 1 ms, so a press long enough to be read in a real run can still fall
## between two ticks. A combo lives or dies on that margin, and measuring it at a
## frame rate nobody plays at would be measuring something else.
##
##   /Applications/Godot.app/Contents/MacOS/Godot --path . \
##       res://tools/verify/strikes.tscn

## The six normals: the action each is bound to, the damage it should do, and the
## state it should reach. Distinct damages are what make this measurable.
const BUTTONS := [
	{"action": "p1_a", "key": "LP", "state": "1punch", "damage": 7},
	{"action": "p1_b", "key": "MP", "state": "2punch", "damage": 7},
	{"action": "p1_c", "key": "HP", "state": "3punch", "damage": 11},
	{"action": "p1_x", "key": "LK", "state": "1kick", "damage": 4},
	{"action": "p1_y", "key": "MK", "state": "2kick", "damage": 7},
	{"action": "p1_z", "key": "HK", "state": "3kick", "damage": 10},
]

## Frames to hold a button: longer than one engine tick at any frame rate, because
## a press shorter than a tick is a press the engine never reads.
const HOLD := 10
## Frames with no input before a measurement. A button pressed while the previous
## attack is still playing is not a measurement -- and this is not hypothetical, it
## is what the first version of this file got wrong: it found the lights failing and
## the mediums passing, which is exactly the pattern you get when you measure the
## jabs from inside the jab. `1punch`'s `from` list is idle/walk/back, so a light
## pressed during a light is correctly ignored, and reading that as "the lights are
## broken" would have sent someone to fix the moveset. It is why every measurement
## below starts here instead.
const IDLE_SETTLE := 50
## Frames of silence after a press, so the attack has time to start and, if it is
## going to, land.
const SETTLE := 50
## Frames between the first and second press in the window sweep. The chain lives
## or dies on this number, so the sweep exists to report it as a range rather than
## assert one hand-picked value.
const GAPS := [2, 4, 6, 8, 10, 12, 16, 22, 30]

var _failures: Array = []
var _notes: Array = []
var _engine = null
var _phase := "approach"
var _frames := 0
var _index := 0
var _seen: Array = []
var _window: Dictionary = {}
var _chain_strengths: Array = []
var _chain_damage := 0
## The states player 1 passed through, in order, since the last phase began.
##
## This is the whole point of `get_player_state`. Damage can say that SOMETHING
## landed, but not which move, and not whether a move came out and missed -- so a
## follow-up that never fired and a follow-up that fired into thin air read
## identically. The trace tells them apart, and it is the only reading of a moveset
## that can be trusted: the state machine is what `from`, `trigger` and `combo`
## actually resolve into.
var _trace: Array = []
var _last_state := ""
## The defender's x range over the current phase. Sampled because a follow-up that
## comes out and misses while the opponent is in hit-stun can only be about where
## the two of them are, and the state trace cannot show position.
var _def_x_min := 0.0
var _def_x_max := 0.0




func _ready() -> void:
	Engine.max_fps = 60
	print("=== strike and combo calibration ===")

	if not ClassDB.class_exists("OpenFightNode"):
		_fail("OpenFightNode is not registered")
		_finish()
		return

	GameState.picks = [0, 1]
	GameState.stage_index = 0
	GameState.attach_host(self)
	_notes.append("fighter: %s" % GameState.fighter_name(0))
	if not GameState.goto("match"):
		_fail("could not enter the match")
		_finish()
		return

	var match_node = GameState.current_screen_node()
	_engine = match_node.get_node_or_null("OpenFight")
	if _engine == null:
		_fail("the match scene has no OpenFight child")
		_finish()
		return

	_engine.hit.connect(_on_hit)


func _on_hit(_attacker: int, _defender: int, damage: int, blocked: bool,
		strength: String, state: String) -> void:
	if blocked:
		return
	if _phase == "chain":
		_chain_damage += damage
		_chain_strengths.append(strength)
	else:
		# The distance at the moment the hit resolved. This is the number a hitbox
		# calibration is actually about: a move that connects at one spacing and
		# misses at a slightly wider one has a reach, and the reach is what decides
		# whether a follow-up can land.
		var distance := 0.0
		if _engine != null and is_instance_valid(_engine):
			distance = absf(float(_engine.get_player_x(0))
					- float(_engine.get_player_x(1)))
		_seen.append({"frame": _frames, "damage": damage, "strength": strength,
				"state": state, "distance": distance,
				"attacker_x": float(_engine.get_player_x(0)),
				"defender_x": float(_engine.get_player_x(1))})


## "7@13.1 into hurt_mid at 30.0/70.0" -- the damage, the spacing it landed at, the
## state it put the defender in, and where the two of them were. Every one of those
## is needed to explain why one spacing connects and a 0.3-unit difference does not.
func _hit_summary() -> String:
	var parts: Array = []
	for hit in _seen:
		parts.append("%d@%.1f into %s at %.1f/%.1f"
				% [int(hit["damage"]), float(hit["distance"]), str(hit["state"]),
					float(hit["attacker_x"]), float(hit["defender_x"])])
	return "[%s]" % ", ".join(PackedStringArray(parts))


## Samples player 1's state once a frame and records each change. Cheap, and it
## makes every phase self-describing in the log.
func _track_state() -> void:
	if _engine == null or not is_instance_valid(_engine):
		return
	var current := str(_engine.get_player_state(0))
	if current != _last_state:
		_trace.append(current)
		_last_state = current

	var x := float(_engine.get_player_x(1))
	if x > _def_x_max or _def_x_max == 0.0:
		_def_x_max = x
	if x < _def_x_min or _def_x_min == 0.0:
		_def_x_min = x


## Called at the top of every measurement phase.
##
## It resets the match and walks back in, and both halves are load-bearing. The
## health a probe spends accumulates, and a match that reaches its decision
## navigates to the results screen and takes the engine node with it -- so a long
## sweep that ignores this crashes partway through instead of reporting. The reset
## puts the fighters back at their start positions, out of range, so the phase has
## to walk them back together before it measures anything. Every phase therefore
## re-establishes the same precondition, and a phase that runs after an accidental
## KO still measures something true.
func _settle_from_idle() -> void:
	if _frames == 1:
		_trace.clear()
		_last_state = ""
		_def_x_min = 0.0
		_def_x_max = 0.0
		if _engine != null and is_instance_valid(_engine) \
				and _engine.has_method("reset_match"):
			_engine.reset_match()
	if _frames <= IDLE_SETTLE:
		Input.action_press("p1_right")
	else:
		Input.action_release("p1_right")


func _process(_delta: float) -> void:
	if _engine == null or not is_instance_valid(_engine) or _phase == "done":
		return
	_frames += 1
	_track_state()

	# Approach: hold forward and jab until something lands. Walking into range is a
	# precondition for measuring anything, not a thing being measured.
	if _phase == "approach":
		Input.action_press("p1_right")
		if _frames % SETTLE == 0:
			Input.action_press("p1_a")
		if _frames % SETTLE == HOLD:
			Input.action_release("p1_a")
		if not _seen.is_empty():
			_release_all()
			_notes.append("in range after %d frames" % _frames)
			_seen.clear()
			_phase = "buttons"
			_frames = 0
			_index = 0
		if _frames > 1500:
			_fail("the fighters never came into range")
			_finish()
		return

	# One button at a time, always from idle. Neutral is the only state where all six
	# normals are legal, so it is the only place a button can be measured.
	if _phase == "buttons":
		_settle_from_idle()
		if _frames == IDLE_SETTLE:
			Input.action_press(String(BUTTONS[_index]["action"]))
		if _frames == IDLE_SETTLE + HOLD:
			Input.action_release(String(BUTTONS[_index]["action"]))
		if _frames > IDLE_SETTLE + SETTLE:
			_judge_button()
			_index += 1
			_frames = 0
			_seen.clear()
			if _index >= BUTTONS.size():
				_phase = "window"
				_index = 0
				_notes.append("")
				_notes.append("window sweep: light, then medium, gap frames later")
		return

	# The sweep. Two hits means the medium came out; the FRAME the second one lands
	# says whether it cancelled the light or waited for it to end, and that is the
	# difference between a chain and two attacks in a row.
	if _phase == "window":
		_settle_from_idle()
		var gap := int(GAPS[_index])
		if _frames == IDLE_SETTLE:
			Input.action_press("p1_a")
		if _frames == IDLE_SETTLE + HOLD:
			Input.action_release("p1_a")
		if _frames == IDLE_SETTLE + gap:
			Input.action_press("p1_b")
		if _frames == IDLE_SETTLE + gap + HOLD:
			Input.action_release("p1_b")
		if _frames > IDLE_SETTLE + gap + SETTLE * 2:
			_release_all()
			_judge_window(gap)
			_index += 1
			_frames = 0
			_seen.clear()
			if _index >= GAPS.size():
				_judge_window_summary()
				_phase = "chain"
				_frames = 0
				_chain_damage = 0
				_chain_strengths.clear()
		return

	# The finisher: light, medium, heavy. Three hits with the last one heavy is the
	# whole claim -- a run that can only ever be two lights is two options.
	#
	# It uses the LATEST gap the sweep found a cancel at, not the middle of that range,
	# and the difference is not cosmetic. A follow-up's active frame arrives 10-11 frames
	# after its press while the opponent is unhittable for ~9 frames after each hit, so
	# pressing later is what clears the stun. The earliest working gap is the one that
	# barely clears it, and the heavy -- whose active frame is the latest of the three --
	# then misses. Measured: at the middle gap the run lands the light and the heavy and
	# loses the straight, which is what a "combo" that is really two moves looks like.
	if _phase == "chain":
		_settle_from_idle()
		var gap := int(_window.get("best_gap", 8))
		if _frames == IDLE_SETTLE:
			Input.action_press("p1_a")
		if _frames == IDLE_SETTLE + HOLD:
			Input.action_release("p1_a")
		if _frames == IDLE_SETTLE + gap:
			Input.action_press("p1_b")
		if _frames == IDLE_SETTLE + gap + HOLD:
			Input.action_release("p1_b")
		if _frames == IDLE_SETTLE + gap * 2:
			Input.action_press("p1_c")
		if _frames == IDLE_SETTLE + gap * 2 + HOLD:
			Input.action_release("p1_c")
		if _frames > IDLE_SETTLE + gap * 2 + SETTLE * 2:
			_release_all()
			_judge_chain()
			_phase = "done"
			_finish()



func _release_all() -> void:
	for button in BUTTONS:
		Input.action_release(String(button["action"]))
	Input.action_release("p1_right")
	Input.action_release("p1_left")
	Input.action_release("p1_a")
	Input.action_release("p1_b")
	Input.action_release("p1_c")


func _judge_button() -> void:
	var expected: Dictionary = BUTTONS[_index]
	var state := str(expected["state"])
	var reached := _trace.has(state)
	var damages: Array = []
	for hit in _seen:
		damages.append(int(hit["damage"]))

	var verdict := "entered" if reached else "NOT ENTERED"
	_notes.append("  %-2s  %-8s %-12s %s"
			% [str(expected["key"]), state, verdict, _hit_summary()])
	_notes.append("      states: %s" % str(_trace))

	if not reached:
		_fail("%s never entered %s -- the states it passed through were %s"
				% [str(expected["key"]), state, str(_trace)])
	if not damages.has(int(expected["damage"])):
		_fail("%s reached %s but dealt %s, not the %d the move is worth"
				% [str(expected["key"]), state,
					str(damages) if not damages.is_empty() else "nothing",
					int(expected["damage"])])


## One gap in the sweep.
##
## A cancel is not "two hits landed". It is `2punch` appearing directly after
## `1punch` in the trace with no return to idle in between. Two hits a gap apart can
## equally mean the light ran to completion and the medium was a fresh move -- which
## is what the sweep first reported, and what reads as a working combo to anyone
## watching the damage numbers.
func _judge_window(gap: int) -> void:
	var damages: Array = []
	for hit in _seen:
		damages.append(int(hit["damage"]))

	var cancel := false
	for i in max(_trace.size() - 1, 0):
		if str(_trace[i]) == "1punch" and str(_trace[i + 1]) == "2punch":
			cancel = true
	if cancel:
		var cancels: Array = _window.get("cancels", [])
		cancels.append(gap)
		_window["cancels"] = cancels
	if _seen.size() >= 2:
		var connected: Array = _window.get("connected", [])
		connected.append(gap)
		_window["connected"] = connected

	_notes.append("  gap %2d  %-6s  %d hit(s) %s   defender x %.1f..%.1f   states: %s"
			% [gap, "CANCEL" if cancel else "no", _seen.size(), _hit_summary(),
				_def_x_min, _def_x_max, str(_trace)])


## If no gap in the sweep cancelled, the medium never came out during the light, and
## that is the user-visible bug: a combo that stops at the lights.
func _judge_window_summary() -> void:
	var cancels: Array = _window.get("cancels", [])
	var connected: Array = _window.get("connected", [])
	_notes.append("")
	if cancels.is_empty():
		_fail("no medium ever cancelled the light at any gap in %s frames (%d gap(s) "
				% [str(GAPS), connected.size()]
				+ "produced two hits, but each time the light had already ended): the "
				+ "combo stops at the light attacks, exactly as reported")
		return
	_window["best_gap"] = int(cancels[cancels.size() - 1])
	_notes.append("  cancels at %s frames; using %d for the finisher"
			% [str(cancels), int(_window["best_gap"])])



## A chain is three hits. Two means the straight cancelled the jab and nothing
## cancelled the straight; three means the whole run connected; one means it is
## three separate moves with a pause between them.
func _judge_chain() -> void:
	_notes.append("")
	_notes.append("chain LP,MP,HP -> %d hit(s), %d damage, strengths %s"
			% [_chain_strengths.size(), _chain_damage, str(_chain_strengths)])
	_notes.append("  states: %s" % str(_trace))
	if _chain_strengths.is_empty():
		_fail("the chain landed nothing")
		return
	if not _cancelled("1punch", "2punch"):
		_fail("the finisher run never cancelled the light into the straight: %s"
				% str(_trace))
	if _chain_strengths.count("HIT_H") == 0:
		_fail("the chain never reached a heavy (%s). A run that can only ever be the "
				% str(_chain_strengths)
				+ "two lights is not a chain, it is two options.")
	if _chain_strengths.size() < 3:
		_fail("the chain connected %d hit(s) of 3 (%s)"
				% [_chain_strengths.size(), str(_chain_strengths)])


## True when `second` follows `first` in the trace with nothing in between -- i.e.
## the machine went straight from one to the other, which is what a cancel is.
func _cancelled(first: String, second: String) -> bool:
	for i in max(_trace.size() - 1, 0):
		if str(_trace[i]) == first and str(_trace[i + 1]) == second:
			return true
	return false



func _fail(message: String) -> void:
	_failures.append(message)
	printerr("FAIL: " + message)


func _finish() -> void:
	_release_all()
	print("")
	print("=== strike calibration summary ===")
	for line in _notes:
		print(line)
	print("")
	if _failures.is_empty():
		print("PASS: every button reaches its move and the chain finishes on a heavy")
		get_tree().quit(0)
	else:
		printerr("%d assertion(s) failed" % _failures.size())
		get_tree().quit(1)


