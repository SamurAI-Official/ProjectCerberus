extends Control
## Debug capture: where does the engine actually put Tsu Ibano's boxes?
##
## `show_hitbox: true` makes the engine draw every hurtbox (blue) and hitbox (red)
## it is testing, so a screenshot of a live match is a *measurement* of the
## collision convention rather than a reading of it. That matters because
## `Animation::updateCollisions` anchors each box on the sprite's bounding-box
## corner, not on the player origin:
##
##     float width = inverted ? sprites[current]->getWidth() / 2
##                            : -sprites[current]->getWidth() / 2;
##     offense[current]->update(x_pos + width, y_pos - height / 2, inverted);
##
## so the same `x_pos` in the YAML lands somewhere different depending on the
## frame's declared width -- which is 30 for a body pose and 38 for a reach pose.
##
## This walks player one in, punches on a fixed period, and captures a timeline.
##
## It also asserts something, which is the point of keeping it in the suite: that
## the approach produces hits at all. A box anchoring error leaves the fight
## running perfectly -- every frame loads, every state is reachable, the HUD
## counts down -- and simply never connects, which the headless roster test
## reported as a 120-second timeout rather than as a box problem. This is the
## check that fails on that instead.
##
##   /Applications/Godot.app/Contents/MacOS/Godot --path . \
##       res://tools/verify/m3_boxes.tscn
##
## Captures land in user://box_*.png. Needs a real window, so never run it
## headless -- there is nothing to screenshot, and without the overlay there is
## nothing to look at either.

const HOLD_FRAMES := 4
## Matches m2_flow's period, so this reproduces that test's fight rather than a
## faster one: the round-2 stall only shows up at this cadence.
const PUNCH_PERIOD_FRAMES := 24
## Seconds at which to grab a frame. The last four are past the first round
## boundary on purpose: a fight that lands hits in round 1 and none in round 2
## looks identical in a summary, and different in these frames.
const CAPTURES := [0.10, 1.00, 3.00, 5.00, 6.50, 8.00, 10.00, 12.00]
const STOP_AFTER := 13.0

var _frames := 0
var _elapsed := 0.0
var _done := false
var _engine = null
var _next_capture := 0
var _last_health := [100, 100]
var _hits := 0
var _damage := 0
var _strengths := {}


func _ready() -> void:
	Engine.max_fps = 60

	if not ClassDB.class_exists("OpenFightNode"):
		printerr("OpenFightNode is not registered")
		get_tree().quit(1)
		return

	if DisplayServer.get_name() == "headless":
		printerr("this instrument needs a window; do not run it headless")
		get_tree().quit(2)
		return

	GameState.picks = [0, 1]
	GameState.stage_index = 0
	GameState.attach_host(self)

	print("matchup: %s vs %s in %s" % [
		GameState.fighter_name(0), GameState.fighter_name(1), GameState.stage_name()])

	if not GameState.goto("match"):
		printerr("could not enter the match")
		get_tree().quit(1)
		return

	var match_node = GameState.current_screen_node()
	var engine_node = match_node.get_node_or_null("OpenFight")
	if engine_node == null:
		printerr("the match scene has no OpenFight child")
		get_tree().quit(1)
		return

	_engine = engine_node
	engine_node.hit.connect(_on_hit)


func _on_hit(attacker: int, defender: int, damage: int, blocked: bool,
		strength: String, state: String) -> void:
	_hits += 1
	_damage += damage
	_strengths[strength] = true
	print("  HIT t=%.2fs attacker=%d defender=%d damage=%d blocked=%s strength=%s state=%s"
		% [_elapsed, attacker, defender, damage, str(blocked), strength, state])


func _process(delta: float) -> void:
	if _done:
		return

	_elapsed += delta
	_frames += 1

	Input.action_press("p1_right")
	Input.action_release("p1_left")
	if _frames % PUNCH_PERIOD_FRAMES == 0:
		Input.action_press("p1_a")
	elif _frames % PUNCH_PERIOD_FRAMES == HOLD_FRAMES:
		Input.action_release("p1_a")

	if _engine != null:
		for index in [0, 1]:
			var health: int = _engine.get_health(index)
			if health != _last_health[index]:
				print("  health p%d %d -> %d  (t=%.2fs)" % [index + 1, _last_health[index], health, _elapsed])
				_last_health[index] = health

	while _next_capture < CAPTURES.size() and _elapsed >= CAPTURES[_next_capture]:
		_capture(CAPTURES[_next_capture])
		_next_capture += 1

	if _elapsed >= STOP_AFTER:
		_finish()


func _capture(stamp: float) -> void:
	await RenderingServer.frame_post_draw
	var image := get_viewport().get_texture().get_image()
	var path := "user://box_%04d.png" % int(round(stamp * 100))
	var error := image.save_png(path)
	if error != OK:
		printerr("  could not save %s: error %d" % [path, error])
		return
	print("  captured t=%.2fs %dx%d -> %s" % [
		stamp, image.get_width(), image.get_height(), ProjectSettings.globalize_path(path)])


func _finish() -> void:
	if _done:
		return
	_done = true
	Input.action_release("p1_right")
	Input.action_release("p1_a")

	print("")
	print("=== M3 box overlay check ===")
	print("  elapsed  : %.2fs" % _elapsed)
	print("  hits     : %d (%d damage)" % [_hits, _damage])
	print("  strengths: %s" % str(_strengths.keys()))
	print("  captures : %s" % ProjectSettings.globalize_path("user://"))

	if _hits == 0:
		printerr("FAIL: the approach landed no hits in %.1fs -- the boxes do not "
			% _elapsed + "overlap, whatever they say in the YAML")
		print("  compare the captures above against the expected layout: a blue "
			+ "hurtbox over each fighter's body and a red hitbox on the fist")
		get_tree().quit(1)
		return

	print("PASS: hitboxes and hurtboxes connect in the engine")
	get_tree().quit(0)
