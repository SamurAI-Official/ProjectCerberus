extends Node
## Default gamepad bindings for the fighting actions.
##
## The KEYBOARD half of the control scheme lives in project.godot, for two
## reasons: the action *names* are load-bearing (OpenFightNode::readFrameInput()
## looks up "p1_up".."p2_z" by name and silently reads nothing if one is
## missing), and upstream shipped them there.
##
## The GAMEPAD half is applied here instead of hand-written into project.godot
## because Godot's InputEvent serialisation has changed shape across 4.x
## (`key_label` and `location` were added in 4.3), and because any future
## rebinding UI has to go through InputMap anyway. Everything below is additive
## and idempotent: it never clobbers a keyboard binding, and re-running it is a
## no-op.
##
## Pads are per-player on purpose -- P1 is device 0, P2 is device 1. A fighting
## game needs two pads, and device -1 ("any device") would make both fighters
## respond to a single controller.

## Face and shoulder buttons. The mapping puts a 6-button fighter layout onto a
## 4-button pad: light/medium on the face, heavy on the shoulders.
const BUTTONS := {
	"a": JOY_BUTTON_X, # LP
	"b": JOY_BUTTON_Y, # MP
	"c": JOY_BUTTON_LEFT_SHOULDER, # HP
	"x": JOY_BUTTON_A, # LK
	"y": JOY_BUTTON_B, # MK
	"z": JOY_BUTTON_RIGHT_SHOULDER, # HK
	"up": JOY_BUTTON_DPAD_UP,
	"down": JOY_BUTTON_DPAD_DOWN,
	"left": JOY_BUTTON_DPAD_LEFT,
	"right": JOY_BUTTON_DPAD_RIGHT,
}

## Left stick as well as the d-pad, so either feels natural for movement.
## InputEventJoypadMotion only cares about the SIGN of axis_value.
const AXES := {
	"up": [JOY_AXIS_LEFT_Y, -1.0],
	"down": [JOY_AXIS_LEFT_Y, 1.0],
	"left": [JOY_AXIS_LEFT_X, -1.0],
	"right": [JOY_AXIS_LEFT_X, 1.0],
}

func _ready() -> void:
	apply_defaults()

## Adds any missing default. Returns how many events were added, which is what a
## test asserts on.
func apply_defaults() -> int:
	var added := 0

	for player in [0, 1]:
		for suffix in BUTTONS:
			var action := "p%d_%s" % [player + 1, suffix]
			var button: int = BUTTONS[suffix]
			if not _has_joy_button(action, player, button):
				added += _add(action, _joy_button(player, button))

		for suffix in AXES:
			var action := "p%d_%s" % [player + 1, suffix]
			var axis: int = AXES[suffix][0]
			var value: float = AXES[suffix][1]
			if not _has_joy_axis(action, player, axis, value):
				added += _add(action, _joy_axis(player, axis, value))

	return added

func _add(action: String, event: InputEvent) -> int:
	if not InputMap.has_action(action):
		# Creating it keeps the game playable on a pad, but this is a real
		# problem: the engine would then have an action with no keyboard route.
		push_warning("InputBindings: '%s' is missing; is project.godot's [input] block intact?" % action)
		InputMap.add_action(action)

	InputMap.action_add_event(action, event)
	return 1

# Field comparisons rather than InputEvent.is_match(): the device and axis
# semantics of is_match() are easy to get subtly wrong, and getting them wrong
# here would silently stack duplicate events on every launch.
func _has_joy_button(action: String, device: int, button: int) -> bool:
	for event in InputMap.action_get_events(action):
		if event is InputEventJoypadButton and event.device == device and event.button_index == button:
			return true
	return false

func _has_joy_axis(action: String, device: int, axis: int, value: float) -> bool:
	for event in InputMap.action_get_events(action):
		if event is InputEventJoypadMotion and event.device == device and event.axis == axis:
			if signf(event.axis_value) == signf(value):
				return true
	return false

func _joy_button(device: int, button: int) -> InputEventJoypadButton:
	var event := InputEventJoypadButton.new()
	event.device = device
	event.button_index = button
	event.pressed = false
	return event

func _joy_axis(device: int, axis: int, value: float) -> InputEventJoypadMotion:
	var event := InputEventJoypadMotion.new()
	event.device = device
	event.axis = axis
	event.axis_value = value
	return event
