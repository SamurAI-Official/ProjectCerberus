extends Control
## Wall collision: does the stage actually have edges?
##
## openfight has no concept of a world bound anywhere in it -- nothing bounded a
## fighter's x -- so both fighters used to walk off the stage and keep going until
## the round ended. The engine patch (0003) clamps a fighter's x in moveXpos(),
## and this is the check that the clamp exists, is in the right place, and is set
## from the stage's own data rather than from a constant that drifted.
##
## It can be headless because the patch also exposes `get_player_x`, which is the
## only way to ask the question from outside: before it, the node published no
## position at all, which is why "walked off the stage" was never caught.
##
##   /Applications/Godot.app/Contents/MacOS/Godot --headless --path . \
##       res://tools/verify/walls.tscn

## How long to hold a direction before deciding the fighter has stopped. Sized for
## the longer of the two walks: from the left wall to the right wall is the whole
## arena, about 118 units, which at 0.34 units a frame is roughly 350 engine ticks
## -- and the engine runs those at 100 a second while Godot runs at 60, so a frame
## budget of 240 leaves margin on both walks rather than only the short one.
const PUSH_FRAMES := 240

var _failures: Array = []
var _phase := "setup"
var _frames := 0
var _engine = null
var _match_node: Node = null
var _bounds := Vector2.ZERO
var _notes: Array = []


func _ready() -> void:
	Engine.max_fps = 60
	print("=== stage walls ===")

	if not ClassDB.class_exists("OpenFightNode"):
		_fail("OpenFightNode is not registered")
		_finish()
		return

	GameState.picks = [0, 1]
	GameState.stage_index = 0
	GameState.attach_host(self)

	_bounds = GameState.stage_bounds()
	_notes.append("stage          : %s" % GameState.stage_name())
	_notes.append("declared bounds: min_x %.1f  max_x %.1f" % [_bounds.x, _bounds.y])

	if _bounds.y <= _bounds.x:
		_fail("the stage's bounds are not an interval: %s" % str(_bounds))

	if not GameState.goto("match"):
		_fail("could not enter the match")
		_finish()
		return

	_match_node = GameState.current_screen_node()
	var engine_node = _match_node.get_node_or_null("OpenFight")
	if engine_node == null:
		_fail("the match scene has no OpenFight child")
		_finish()
		return

	_engine = engine_node
	if not _engine.has_method("get_player_x"):
		_fail("the node has no get_player_x: patch 0003 is not applied to the build")
		_finish()
		return

	# The node must have been told the same numbers the stage declares, or the
	# walls exist somewhere other than where the data says.
	if not is_equal_approx(_engine.stage_min_x, _bounds.x) \
			or not is_equal_approx(_engine.stage_max_x, _bounds.y):
		_fail("the node's walls are (%.1f, %.1f) but the stage declares (%.1f, %.1f)"
				% [_engine.stage_min_x, _engine.stage_max_x, _bounds.x, _bounds.y])

	_notes.append("node walls     : min_x %.1f  max_x %.1f"
			% [_engine.stage_min_x, _engine.stage_max_x])
	_phase = "left"


func _process(_delta: float) -> void:
	if _engine == null or _phase == "done":
		return
	_frames += 1

	match _phase:
		"left":
			_walk("p1_left", "p1_right")
			if _frames > PUSH_FRAMES:
				_check_edge("left", _bounds.x)
				_phase = "right"
				_frames = 0
		"right":
			_walk("p1_right", "p1_left")
			if _frames > PUSH_FRAMES:
				_check_edge("right", _bounds.y)
				_phase = "arena"
				_frames = 0
		"arena":
			_check_edge("right", _bounds.y)
			_phase = "done"
			_finish()


## Holds `forward`, and holds the opposite released so a stale press cannot fight
## it. Also records the position so the assertion can report what it was.
func _walk(forward: String, back: String) -> void:
	Input.action_press(forward)
	Input.action_release(back)


## The edge is a property of the pair, not of one fighter.
##
## Walking right does not drive p1 into the wall -- it drives p1 into p2, and the
## pushbox carries p2 to the wall and pins it there while p1 stops behind it. That
## is the correct interaction and it makes "p1 reached the edge" the wrong
## assertion: on the right wall p1 stops at 103.2 against a bound of 108, because
## there is a fighter in the way. So the claim is that the pair reaches the edge,
## and that neither of them is ever outside it.
func _check_edge(side: String, expected: float) -> void:
	var xs := [float(_engine.get_player_x(0)), float(_engine.get_player_x(1))]
	var furthest := minf(xs[0], xs[1]) if side == "left" else maxf(xs[0], xs[1])
	_notes.append("%-11s: furthest %8.2f (edge %7.1f)   p1 %7.2f  p2 %7.2f"
			% [side + " wall", furthest, expected, xs[0], xs[1]])

	for index in [0, 1]:
		if xs[index] < _bounds.x - 0.001 or xs[index] > _bounds.y + 0.001:
			_fail("p%d is outside the arena at x %.2f (bounds %.1f..%.1f)"
					% [index + 1, xs[index], _bounds.x, _bounds.y])

	if is_equal_approx(furthest, expected):
		return
	if furthest < expected:
		_fail("nothing reached the %s wall: furthest x %.2f against an edge at %.1f"
				% [side, furthest, expected])
	else:
		_fail("something went through the %s wall: furthest x %.2f against an edge at %.1f"
				% [side, furthest, expected])


func _fail(message: String) -> void:
	_failures.append(message)
	printerr("FAIL: " + message)


func _finish() -> void:
	if _phase == "done" and _engine != null:
		Input.action_release("p1_left")
		Input.action_release("p1_right")

	print("")
	print("=== stage walls summary ===")
	for line in _notes:
		print("  " + line)

	# A wall that exists only because the check drove into it is not a wall. Both
	# edges have to be inside the arena the stage declares, and the arena has to
	# be wide enough for two fighters to stand in.
	if _bounds.y - _bounds.x < 20.0:
		_fail("the arena is only %.1f units wide" % (_bounds.y - _bounds.x))

	print("")
	if _failures.is_empty():
		print("PASS: the stage has edges and the fighters stop at them")
		get_tree().quit(0)
	else:
		printerr("%d assertion(s) failed" % _failures.size())
		get_tree().quit(1)
