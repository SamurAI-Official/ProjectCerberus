extends Node
## Owns a match: drives the HUD from the engine's signals and nothing else.
##
## Deliberately not a polling loop. Health, round rotation and the winner all
## arrive as signals from the patched engine (patches/openfight/0001), so if the
## HUD is wrong then the signal is wrong -- there is no second source of truth
## that could quietly disagree. The round clock is the one exception, because the
## engine has no per-second tick and polling it would be a signal per frame for no
## benefit.

signal match_finished(winner: int)

const DRAW := -1

## Fallbacks for running this scene with no flow host -- a verification scene, or
## a designer pressing F6 on match.tscn. GameState always wins when it has a
## roster.
const FALLBACK_FIGHTER := "res://data/ryu/ryu.yml"
const FALLBACK_MOVES := "res://data/ryu/moves.yml"
const FALLBACK_BACKGROUND := "res://data/background.png"

const PAUSE_LAYER := 10
const RESULT_DELAY := 2.6

@onready var _p1_bar: Control = $HUD/P1Health
@onready var _p2_bar: Control = $HUD/P2Health
@onready var _round_label: Label = $HUD/RoundLabel
@onready var _timer_label: Label = $HUD/TimerLabel
@onready var _announcer: Node = $HUD/Announcer
@onready var _result_label: Label = $HUD/Result

var _fight
var _round_over := false
var _match_done := false
var _pause_layer: CanvasLayer = null

func _ready() -> void:
	if not ClassDB.class_exists("OpenFightNode"):
		push_error("OpenFightNode is not registered -- run ./patches/openfight/apply.sh then ./tools/build/build_openfight.sh")
		return

	_spawn_fighter_node()

	# The fighter node is added above, so its setup_game() has already run and
	# queued ROUND_STARTED. Events are drained on the first process tick, not
	# during setup, so connecting here still catches round 1.
	_fight.hit.connect(_on_hit)
	_fight.round_started.connect(_on_round_started)
	_fight.round_ended.connect(_on_round_ended)
	_fight.match_ended.connect(_on_match_ended)

	_result_label.text = ""
	_announcer.clear_now()
	_sync_health()

## Built in code rather than placed in match.tscn, because the paths have to come
## from GameState and the node's own _ready() runs setup_game() immediately.
## Putting it in the scene would mean a window where the fighters loaded are the
## scene's defaults rather than the ones that were picked.
func _spawn_fighter_node() -> void:
	_fight = ClassDB.instantiate("OpenFightNode")
	_fight.name = "OpenFight"
	_fight.scale = Vector2(4, 4)
	_fight.player_one_path = _fighter_yaml(0)
	_fight.player_two_path = _fighter_yaml(1)
	_fight.moves_path = _moves_yaml(0)
	_fight.background_path = _background()

	add_child(_fight)
	move_child(_fight, 0)

## Reads a path from the flow host.
##
## This used `Engine.has_singleton("GameState")` as its guard, which is ALWAYS
## false here: has_singleton only reports singletons registered natively
## (GDExtension / Engine.register_singleton), while GameState is a GDScript
## autoload -- a Node under /root. So the guard failed, every path came back
## empty, and both players silently loaded FALLBACK_FIGHTER along with the
## fallback background. That was invisible for as long as ryu was the only entry
## in the roster, because the fallback was indistinguishable from the selection.
##
## get_node_or_null is the correct lookup for an autoload. has_method guards
## against a scene run with no host at all, where a designer pressing F6 on
## match.tscn should still get something on screen.
func _from_state(method: String, fallback: String, argument = null) -> String:
	var state := get_node_or_null("/root/GameState")
	var path: String = ""

	if state != null and state.has_method(method):
		path = state.call(method) if argument == null else state.call(method, argument)

	return path if not path.is_empty() else fallback

func _fighter_yaml(index: int) -> String:
	return _from_state("fighter_yaml", FALLBACK_FIGHTER, index)

func _moves_yaml(index: int) -> String:
	return _from_state("fighter_moves", FALLBACK_MOVES, index)

func _background() -> String:
	return _from_state("stage_background", FALLBACK_BACKGROUND)


func _process(_delta: float) -> void:
	if _fight == null:
		return

	# The clock is the only polled value, for the reason in the header comment.
	_timer_label.text = "%02d" % _fight.get_round_seconds_left()

func _on_hit(_attacker: int, _defender: int, _damage: int, _blocked: bool,
		_strength: String, _state: String) -> void:
	_sync_health()

func _on_round_started(round_number: int) -> void:
	_round_over = false
	_result_label.text = ""
	_round_label.text = "ROUND %d" % round_number
	_sync_health()

	# At round start the engine guarantees health == max_health, because
	# Player::resetForRound() sets exactly that and startRound() emits this
	# signal immediately afterwards. So the current value IS the maximum, which
	# is how the bar learns each character's max without a second engine getter.
	_p1_bar.reset(_fight.get_health(0), _fight.get_health(0))
	_p2_bar.reset(_fight.get_health(1), _fight.get_health(1))

	_announce_round(round_number)

func _announce_round(round_number: int) -> void:
	_announcer.announce("ROUND %d" % round_number, 0.9, 0.25)

	# A Timer child rather than `await get_tree().create_timer(...)`: the match
	# scene is now replaced on match end and from the pause menu, and a coroutine
	# resumed after its node was freed is a dangling call. A Timer is freed with
	# the scene and simply never fires.
	var timer := Timer.new()
	timer.one_shot = true
	timer.wait_time = 0.9
	timer.process_mode = Node.PROCESS_MODE_ALWAYS
	timer.timeout.connect(func() -> void:
		# The round can end during the wait -- a time-over on a short clock, or a
		# test forcing a KO -- and shouting "FIGHT!" over a result would be worse
		# than saying nothing.
		if _round_over or _match_done:
			return
		_announcer.announce("FIGHT!", 0.7, 0.25))
	add_child(timer)
	timer.start()

func _on_round_ended(winner: int, time_over: bool) -> void:
	_round_over = true
	_sync_health()
	_announcer.announce("TIME OVER" if time_over else "K.O.", 1.4, 0.35)
	if winner == DRAW:
		_result_label.text = "DRAW ROUND"
	else:
		_result_label.text = "PLAYER %d TAKES ROUND %d" % [winner + 1, _fight.get_round()]

func _on_match_ended(winner: int) -> void:
	_match_done = true
	_round_over = true
	_sync_health()

	if winner == DRAW:
		_result_label.text = "DRAW GAME"
		_announcer.announce("DRAW GAME", 3.0, 0.9)
	else:
		_result_label.text = "PLAYER %d WINS" % [winner + 1]
		_announcer.announce("PLAYER %d WINS" % [winner + 1], 3.0, 0.9)

	# Report through GameState rather than a trailing signal, so the results
	# screen is truthful whenever it is opened -- including by a test that never
	# saw the match end.
	GameState.record_result(winner, [_fight.get_round_wins(0), _fight.get_round_wins(1)], _fight.get_round())
	match_finished.emit(winner)
	_leave_for_results()

## Leaves a beat for the win announcement before switching screens. Uses a Timer
## child for the same reason _announce_round does: a coroutine that resumes after
## its node is gone is a dangling call, and this node is freed by the transition
## it schedules.
func _leave_for_results() -> void:
	if not GameState.has_host():
		return

	var timer := Timer.new()
	timer.one_shot = true
	timer.wait_time = RESULT_DELAY
	timer.process_mode = Node.PROCESS_MODE_ALWAYS
	timer.timeout.connect(func() -> void: GameState.goto("results"))
	add_child(timer)
	timer.start()

# --- pause ------------------------------------------------------------------

func _unhandled_input(event: InputEvent) -> void:
	if not event.is_action_pressed("ui_cancel"):
		return

	get_viewport().set_input_as_handled()
	if get_tree().paused:
		_resume()
	else:
		_pause()

func _pause() -> void:
	if _pause_layer != null:
		return
	if _match_done:
		return

	_pause_layer = CanvasLayer.new()
	_pause_layer.layer = PAUSE_LAYER
	add_child(_pause_layer)

	var menu: Node = load("res://game/match/pause_menu.gd").new()
	menu.requested.connect(_on_pause_requested)
	_pause_layer.add_child(menu)

	# Paused last, after the menu is in the tree and set to
	# PROCESS_MODE_WHEN_PAUSED -- otherwise the menu would be frozen too.
	get_tree().paused = true

func _resume() -> void:
	get_tree().paused = false
	if _pause_layer != null and is_instance_valid(_pause_layer):
		remove_child(_pause_layer)
		_pause_layer.queue_free()
	_pause_layer = null

func _on_pause_requested(action: String) -> void:
	match action:
		"resume":
			_resume()
		"restart":
			_fight.reset_match()
			_round_over = false
			_match_done = false
			_result_label.text = ""
			_resume()
		"quit":
			# Unpause before navigating, or the next screen arrives frozen.
			_resume()
			GameState.goto("title")


func _sync_health() -> void:
	if _fight == null:
		return
	_p1_bar.set_health(_fight.get_health(0))
	_p2_bar.set_health(_fight.get_health(1))
