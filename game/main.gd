extends Control
## Entry point. Applies settings, checks the world is actually playable, and
## hands the flow to GameState.
##
## The M0 extension diagnostics that used to live here now live in
## game/screens/boot/boot.tscn, which is still the quickest way to ask "is the
## GDExtension loaded?" without walking any menus -- and, importantly, it is a
## separate scene from the game so a broken build shows a readable message rather
## than an empty window.

func _ready() -> void:
	# Both of these present as "nothing responds" if left silent, which is the
	# worst possible failure mode for a menu. Say what is wrong instead.
	if not ClassDB.class_exists("OpenFightNode"):
		_fail("OpenFightNode is not registered.\n\nBuild the extension:\n  ./patches/openfight/apply.sh\n  ./tools/build/build_openfight.sh")
		return

	if GameState.fighters.is_empty() or GameState.stages.is_empty():
		_fail("Roster or stage manifest is empty.\n\nExpected:\n  data/fighters/manifest.json\n  data/stages/manifest.json")
		return

	GameState.attach_host(self)
	GameState.goto("title")

func _fail(message: String) -> void:
	push_error(message)

	var label := Label.new()
	label.text = message
	label.add_theme_font_size_override("font_size", 16)
	label.set_anchors_preset(Control.PRESET_FULL_RECT)
	label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	add_child(label)
