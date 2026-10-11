extends Control
## One fighter's health bar.
##
## Two values, deliberately: `target_health` is what the engine reports and
## `display_health` is what is drawn. A fighting-game bar that snaps to its new
## value looks broken, so the drawn value chases the true one -- but that means
## anything asserting on this bar must read `target_health`, because
## `display_health` is intended to be behind it.
##
## Healing is the exception: refilling between rounds is instant, because nobody
## wants to watch a bar creep back up while a round is already starting.

@export var mirror := false
@export var drain_speed := 55.0  ## HP per second the drawn bar chases at

var max_health := 100
var target_health := 100
var display_health := 100.0

@onready var _fill: ColorRect = $Fill
@onready var _shell: ColorRect = $Shell

func _ready() -> void:
	display_health = float(target_health)
	_apply()

func set_health(hp: int, maximum: int = -1) -> void:
	if maximum > 0:
		max_health = maximum
	target_health = clampi(hp, 0, max_health)
	if not is_inside_tree():
		display_health = float(target_health)
	_apply()

## Used at the start of every round: no animation, jump straight to full.
func reset(hp: int, maximum: int) -> void:
	max_health = maxi(1, maximum)
	target_health = clampi(hp, 0, max_health)
	display_health = float(target_health)
	_apply()

func ratio() -> float:
	if max_health <= 0:
		return 0.0
	return clampf(display_health / float(max_health), 0.0, 1.0)

func _process(delta: float) -> void:
	if is_equal_approx(display_health, float(target_health)):
		return

	if display_health > float(target_health):
		display_health = maxf(float(target_health), display_health - drain_speed * delta)
	else:
		display_health = float(target_health)

	_apply()

func _apply() -> void:
	if _fill == null or _shell == null:
		return

	# The shell is the full-width track; the fill is laid out manually inside it
	# so it can shrink from either edge. Deliberately not anchored: an anchored
	# Control gets its size overwritten, and mirroring P2's bar relies on setting
	# position/size directly.
	var track := _shell.size.x
	var filled := track * ratio()

	_fill.size = Vector2(filled, _shell.size.y)
	if mirror:
		_fill.position = Vector2(_shell.position.x + (track - filled), _shell.position.y)
	else:
		_fill.position = Vector2(_shell.position.x, _shell.position.y)

	# Low health reads as danger without needing a separate "hit" flash.
	var low := ratio() <= 0.25
	_fill.color = Color(0.86, 0.22, 0.18) if low else Color(0.98, 0.78, 0.2)

func _notification(what: int) -> void:
	if what == NOTIFICATION_RESIZED:
		_apply()
