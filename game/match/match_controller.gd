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

@onready var _fight = $OpenFight
@onready var _p1_bar: Control = $HUD/P1Health
@onready var _p2_bar: Control = $HUD/P2Health
@onready var _round_label: Label = $HUD/RoundLabel
@onready var _timer_label: Label = $HUD/TimerLabel
@onready var _announcer: Node = $HUD/Announcer
@onready var _result_label: Label = $HUD/Result

var _round_over := false
var _match_done := false

func _ready() -> void:
	if not ClassDB.class_exists("OpenFightNode"):
		push_error("OpenFightNode is not registered -- build addons/openfight first")
		return

	# Children are _ready() before their parent, so OpenFightNode has already run
	# setup_game(). That queued ROUND_STARTED but has not emitted it yet -- events
	# are drained on the first process tick -- so connecting here still catches
	# round 1.
	_fight.hit.connect(_on_hit)
	_fight.round_started.connect(_on_round_started)
	_fight.round_ended.connect(_on_round_ended)
	_fight.match_ended.connect(_on_match_ended)

	_result_label.text = ""
	_announcer.clear_now()
	_sync_health()

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
	await get_tree().create_timer(0.9).timeout

	# The round can end during the wait (a time-over on a short clock, or a test
	# forcing a KO), and announcing "FIGHT!" over a result would be worse than
	# saying nothing.
	if _round_over or _match_done:
		return

	_announcer.announce("FIGHT!", 0.7, 0.25)

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

	match_finished.emit(winner)

func _sync_health() -> void:
	if _fight == null:
		return
	_p1_bar.set_health(_fight.get_health(0))
	_p2_bar.set_health(_fight.get_health(1))
