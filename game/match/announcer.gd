extends Label
## Round copy: "ROUND 1", "FIGHT!", "K.O.", "TIME OVER", "PLAYER 1 WINS".
##
## A timed label, kept out of MatchController so the wording lives in one place
## and so a headless test can assert on what was actually shown.

var last_message := ""
var _hold := 0.0
var _fade := 0.4

func announce(message: String, seconds := 1.2, fade := 0.35) -> void:
	last_message = message
	text = message
	_hold = seconds
	_fade = maxf(fade, 0.001)
	modulate.a = 1.0

func clear_now() -> void:
	last_message = ""
	text = ""
	_hold = 0.0
	modulate.a = 0.0

func is_showing() -> bool:
	return modulate.a > 0.0 and not text.is_empty()

func _process(delta: float) -> void:
	if _hold > 0.0:
		_hold -= delta
		return

	if modulate.a > 0.0:
		modulate.a = maxf(0.0, modulate.a - delta / _fade)
