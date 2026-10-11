class_name MenuScreen
extends Control
## Shared chrome for the code-built menu screens.
##
## Screens are scripts rather than scenes so the flow is testable headless: a
## test can instantiate one, activate an item, and assert on what it did -- with
## no window, no input device, and no imported art.
##
## Navigation is Godot's own focus system (real Buttons plus grab_focus()) rather
## than a hand-rolled index. That gets the keyboard, the gamepad -- the built-in
## ui_* actions already include the d-pad and the left stick -- and the mouse for
## free, and it cannot drift out of sync with what is drawn.

signal chosen(id: String)

var heading := ""
var footer := ""
var back_screen := "" ## ui_cancel target; empty disables back navigation
var background_color := Color(0.043, 0.043, 0.055, 1.0)
var items: Array = [] ## [{id, label, detail, disabled}]

var _heading_label: Label
var _footer_label: Label
var _detail: Label
var _buttons: Dictionary = {}

func _ready() -> void:
	_configure()
	_build()
	_focus_first()
	_after_build()

## Subclasses set heading/items/footer here. Runs from _ready, so autoloads and
## the manifests are available.
func _configure() -> void:
	pass

## Runs after the tree exists, for subclasses that need the built nodes.
func _after_build() -> void:
	pass

## Return true to mark the item handled. The default warns, so a typo in an item
## id is loud rather than a dead button.
func on_chosen(id: String) -> bool:
	push_warning("%s: unhandled menu item '%s'" % [get_script().resource_path, id])
	return false

func set_heading(text: String) -> void:
	heading = text
	if _heading_label != null:
		_heading_label.text = text

func set_footer(text: String) -> void:
	footer = text
	if _footer_label != null:
		_footer_label.text = text

## For options screens, whose labels show current state rather than a fixed name.
func set_item_label(id: String, text: String) -> void:
	if _buttons.has(id):
		_buttons[id].text = text

func focus_first() -> void:
	_focus_first()

func _build() -> void:
	set_anchors_preset(Control.PRESET_FULL_RECT)

	var background := ColorRect.new()
	background.color = background_color
	background.set_anchors_preset(Control.PRESET_FULL_RECT)
	background.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(background)

	var margin := MarginContainer.new()
	margin.set_anchors_preset(Control.PRESET_FULL_RECT)
	margin.add_theme_constant_override("margin_left", 56)
	margin.add_theme_constant_override("margin_right", 56)
	margin.add_theme_constant_override("margin_top", 34)
	margin.add_theme_constant_override("margin_bottom", 30)
	add_child(margin)

	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 8)
	margin.add_child(column)

	_heading_label = Label.new()
	_heading_label.text = heading
	_heading_label.add_theme_font_size_override("font_size", 28)
	column.add_child(_heading_label)

	var list := VBoxContainer.new()
	list.add_theme_constant_override("separation", 3)
	column.add_child(list)

	for item in items:
		var id := str(item.get("id", ""))
		var button := Button.new()
		button.text = str(item.get("label", id))
		button.alignment = HORIZONTAL_ALIGNMENT_LEFT
		button.focus_mode = Control.FOCUS_ALL
		button.disabled = bool(item.get("disabled", false))
		var detail := str(item.get("detail", ""))
		button.pressed.connect(func() -> void: _activate(id))
		button.focus_entered.connect(func() -> void: _show_detail(detail))
		list.add_child(button)
		_buttons[id] = button

	_detail = Label.new()
	_detail.add_theme_font_size_override("font_size", 13)
	_detail.add_theme_color_override("font_color", Color(0.70, 0.72, 0.80))
	_detail.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	column.add_child(_detail)

	_footer_label = Label.new()
	_footer_label.text = footer
	_footer_label.add_theme_font_size_override("font_size", 12)
	_footer_label.add_theme_color_override("font_color", Color(0.50, 0.52, 0.60))
	_footer_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	column.add_child(_footer_label)

func _show_detail(text: String) -> void:
	if _detail != null:
		_detail.text = text

func _activate(id: String) -> void:
	if on_chosen(id):
		chosen.emit(id)

func _focus_first() -> void:
	for item in items:
		var id := str(item.get("id", ""))
		if _buttons.has(id) and not _buttons[id].disabled:
			_buttons[id].grab_focus()
			return

func _unhandled_input(event: InputEvent) -> void:
	if back_screen.is_empty():
		return
	if event.is_action_pressed("ui_cancel"):
		get_viewport().set_input_as_handled()
		GameState.goto(back_screen)
