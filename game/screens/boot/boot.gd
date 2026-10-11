extends Node2D
## M0 boot check.
##
## Two different failures both look like "the game does not run", so this
## separates them and prints evidence for each:
##
##   1. the dynamic library was never built / is not on the path the
##      .gdextension descriptor lists -> Godot logs "can't open dynamic library"
##   2. the library exists but was built against a different Godot API dump
##      -> Godot refuses to load it, same silent result
##
## In both cases ClassDB.class_exists("OpenFightNode") is false, so that single
## call is the real gate. Run headless to read it from a terminal:
##
##   /Applications/Godot.app/Contents/MacOS/Godot --headless --path . --quit

const OPENFIGHT_CLASS := "OpenFightNode"

@onready var _status: Label = $Status

func _ready() -> void:
	var lines: PackedStringArray = []
	lines.append("Project Cerberus - M0 boot check")
	lines.append("Godot %s" % Engine.get_version_info().get("string", "unknown"))
	lines.append("")

	if ClassDB.class_exists(OPENFIGHT_CLASS):
		lines.append("[ OK ] %s GDExtension registered" % OPENFIGHT_CLASS)
		var names: PackedStringArray = []
		for prop in ClassDB.class_get_property_list(OPENFIGHT_CLASS, true):
			names.append(str(prop.get("name")))
		lines.append("       properties: %s" % ", ".join(names))
		lines.append("")
		lines.append("Next: godot res://game/screens/match/match.tscn")
	else:
		lines.append("[FAIL] %s is not registered" % OPENFIGHT_CLASS)
		lines.append("       expected library from:")
		lines.append("         addons/openfight/bin/godotopenfight.gdextension")
		lines.append("       build it with:")
		lines.append("         tools/build/build_openfight.sh")

	for line in lines:
		print(line)
	_status.text = "\n".join(lines)
