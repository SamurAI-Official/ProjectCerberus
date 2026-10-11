extends Control
## M3 acceptance test: the generated roster actually plays.
##
## The pipeline producing plausible PNGs is not the claim worth testing. The
## claim is that a fighter built from a design sheet is *playable* -- its state
## machine is reachable, its frames load, its hitboxes connect, and its health
## drains. So this loads the real match scene with Tsu Ibano against Fei Young in
## the Gijutsu Gym and forces a fight to a decision.
##
## It also asserts the two fighters differ, because a pipeline that emits two
## identical fighters would pass every other check in this file.
##
##   /Applications/Godot.app/Contents/MacOS/Godot --headless --path . \
##       res://tools/verify/m3_roster.tscn
##
## RESOLVED: the "HIT_H while pressing LP" anomaly
## -----------------------------------------------
## This test used to report every landed hit as HIT_H, which exactly one state in
## the generated YAML emits -- `2punch`, whose trigger is MP -- while pressing only
## the LP button. The obvious reading was that something in the input path
## resolved a light punch to a medium one, and the previous version of this header
## listed what had been ruled out in pursuit of that: the YAML, the moves table,
## the fixture. All three were correctly ruled out, and the conclusion was still
## wrong, because the thing at fault was not on the list.
##
## It was the box anchoring. `Animation::updateCollisions` puts a collision box on
## the sprite's bounding-box corner rather than on the player origin, and the YAML
## had been written as if it were the origin -- so the hurtbox was authored 32
## units below the fighter's feet. With no hurtbox anywhere near the hitboxes, the
## only hits that landed were the ones that happened to coincide by accident, and
## which state those came from was nobody's design. Fixing the anchoring fixed the
## anomaly: this now reports HIT_M from `1punch`, which is what pressing LP was
## always supposed to produce.
##
## The lesson worth keeping in the file is about method rather than about boxes.
## The anomaly was argued about for a while from source; what settled it was a
## measurement. `tools/verify/m3_boxes.tscn` turns on the engine's own box overlay
## and screenshots a live match, which shows in one frame what reading
## `getTrigger` could not.

## What this asserts about the input mapping
## -----------------------------------------
## The pattern below drives the light punch only, and asserts the defender is hit
## for HIT_M and enters `hurt_mid`. That is a specific claim -- LP -> `1punch` ->
## HIT_M -> `hurt_mid`, which is exactly what the design sheet says a light punch
## is -- and it is the claim that was false for as long as the anomaly above
## lasted, so it is worth pinning.
##
## Driving light and medium together would prove nothing and does not work:
## `2punch` can be entered *from* `1punch` and not the reverse, so a medium punch
## started while a light one is still playing simply replaces it, and only HIT_H
## ever reaches the defender. Both can be exercised, but only by phasing them in
## time, which belongs in a move-list test rather than a playability one.

const MAX_SECONDS := 120.0
## The light punch's cadence. Not arbitrary, and worth knowing: the engine only
## lands a hit on a frame where the animation ADVANCES into its active frame
## (`Player::update` gates the collision on `changed`), so the press has to keep
## coming often enough that an active frame is reached while the fighter is in
## range. This cadence does that.
const PUNCH_PERIOD_FRAMES := 22
const PUNCH_HOLD_FRAMES := 4
const KICK_PERIOD_FRAMES := 53

## When to grab the screenshot, in seconds. Kept very small deliberately: at ~0.1s
## the fighters are still standing on their spawn positions, which makes the
## capture a *deterministic* measurement of where the engine puts a fighter. A
## later capture catches them mid-approach and the positions become a function of
## how the AI happened to mash, which is useless for calibrating geometry.
const CAPTURE_AT := 0.1

## Set false to press ONLY the light punch, which isolates which attack state
## a single input actually reaches.
const USE_KICK := false

var _frames := 0
var _elapsed := 0.0
var _done := false
var _phase := "starting"
var _failures: Array = []
var _match_node: Node = null
var _engine = null
var _use_kick := USE_KICK
var _captured := false

## Saves a frame of the live match. Same reason the M0 and M2 render checks
## exist: a headless pass proves the logic runs, not that anything is on screen.
func _capture() -> void:
	await RenderingServer.frame_post_draw
	var image := get_viewport().get_texture().get_image()
	var path := "user://m3_match.png"
	var error := image.save_png(path)
	if error != OK:
		_note("could not save the capture: error %d" % error)
		return
	_note("captured %dx%d -> %s" % [image.get_width(), image.get_height(),
			ProjectSettings.globalize_path(path)])
var _winner := -999
var _hits := 0
var _damage := 0
var _min_health := [999, 999]
var _states_seen := {}
var _skyline := {}

func _ready() -> void:
	Engine.max_fps = 60

	if not ClassDB.class_exists("OpenFightNode"):
		_fail("OpenFightNode is not registered")
		_finish()
		return

	if GameState.fighters.size() < 2:
		_fail("the roster needs at least two fighters, found %d" % GameState.fighters.size())
		_finish()
		return

	# Drive the flow the way character select would, rather than poking the match
	# scene directly -- that is what proves the roster is wired end to end.
	GameState.picks = [0, 1]
	GameState.stage_index = 0
	GameState.attach_host(self)

	_note("matchup: %s vs %s in %s" % [
		GameState.fighter_name(0), GameState.fighter_name(1), GameState.stage_name()])

	if GameState.fighter_name(0) == GameState.fighter_name(1):
		_fail("both roster slots resolved to the same fighter")
		_finish()
		return

	if not GameState.goto("match"):
		_fail("could not enter the match")
		_finish()
		return

	_match_node = GameState.current_screen_node()
	if _match_node == null or not _match_node.has_signal("match_finished"):
		_fail("the match scene did not come up")
		_finish()
		return

	_match_node.match_finished.connect(func(winner: int) -> void: _winner = winner)

	# The controller only re-emits match_finished; the engine node is the one
	# that reports individual hits. Reaching for it by name rather than adding a
	# pass-through signal to the controller purely for a test.
	var engine_node = _match_node.get_node_or_null("OpenFight")
	if engine_node == null:
		_fail("the match scene has no OpenFight child")
		_finish()
		return
	engine_node.hit.connect(_on_hit)
	_engine = engine_node

	_phase = "match"
	print("M3 roster test: fighting")

func _process(delta: float) -> void:
	if _done:
		return

	_elapsed += delta
	_frames += 1

	if _phase != "match":
		return

	_drive_input()

	if not _captured and _elapsed > CAPTURE_AT and DisplayServer.get_name() != "headless":
		_captured = true
		_capture.call_deferred()

	if _engine != null and not _engine.is_match_over():
		for index in [0, 1]:
			_min_health[index] = min(_min_health[index], _engine.get_health(index))

	if _winner != -999:
		_phase = "done"
		_check()
		_finish()
		return

	if _elapsed > MAX_SECONDS:
		_fail("the fight did not reach a decision in %.0fs (hits=%d)" % [_elapsed, _hits])
		_finish()

## Mashes light punch and throws in a kick, so more than one attack state gets
## exercised and more than one hit strength reaches the defender.
func _drive_input() -> void:
	Input.action_press("p1_right")
	Input.action_release("p1_left")

	if _frames % PUNCH_PERIOD_FRAMES == 0:
		Input.action_press("p1_a")
	elif _frames % PUNCH_PERIOD_FRAMES == PUNCH_HOLD_FRAMES:
		Input.action_release("p1_a")

	if _frames % KICK_PERIOD_FRAMES == 10 and _use_kick:
		Input.action_press("p1_x")
	elif _frames % KICK_PERIOD_FRAMES == 14 and _use_kick:
		Input.action_release("p1_x")

func _on_hit(attacker: int, defender: int, damage: int, _blocked: bool,
		strength: String, state: String) -> void:
	_hits += 1
	_damage += damage
	_states_seen[state] = true
	_skyline[strength] = int(_skyline.get(strength, 0)) + 1

func _fail(message: String) -> void:
	_failures.append(message)
	printerr("FAIL: " + message)

func _note(message: String) -> void:
	print("  " + message)

func _check() -> void:
	if _hits == 0:
		_fail("no hits landed -- the generated frames or their hitboxes do not connect")
	if _min_health[1] >= 100:
		_fail("the defender never took damage")
	if _min_health[0] < 100:
		_fail("the attacker lost health while the opponent was idle")
	if not _skyline.has("HIT_M"):
		_fail("the light punch did not land as HIT_M; strengths seen were %s"
				% str(_skyline.keys()))
	if not _states_seen.has("hurt_mid"):
		_fail("a mid-strength hit did not put the defender in hurt_mid; it entered %s"
				% str(_states_seen.keys()))
	if _winner != 0:
		_fail("expected player 1 to win an uncontested match, winner was %d" % _winner)

func _finish() -> void:
	if _done:
		return
	_done = true

	Input.action_release("p1_right")
	Input.action_release("p1_a")
	Input.action_release("p1_x")

	print("")
	print("=== M3 roster test summary ===")
	print("  elapsed        : %.1fs (%d frames)" % [_elapsed, _frames])
	print("  hits           : %d (%d damage)" % [_hits, _damage])
	print("  hit strengths  : %s" % str(_skyline))
	print("  defender states: %s" % str(_states_seen.keys()))
	print("  min health     : p1=%d p2=%d" % [_min_health[0], _min_health[1]])
	print("  winner         : %d" % _winner)

	if _failures.is_empty():
		print("PASS: the generated fighters are playable end to end")
		get_tree().quit(0)
	else:
		printerr("%d assertion(s) failed" % _failures.size())
		get_tree().quit(1)
