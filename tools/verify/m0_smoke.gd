extends Node
## M0 smoke test: run the fighting engine headless for a fixed number of frames
## and fail the process if it does not survive.
##
## Read this as the M0 acceptance gate, not a unit test. It answers one
## question -- "does the vendored engine actually step and render without
## faulting on this machine" -- in a couple of seconds, which is what makes it
## usable in CI and after every submodule bump.
##
## Caveat, stated so nobody mistakes the coverage for more than it is:
## NOTIFICATION_DRAW does not fire in headless, so this exercises GameContext
## (state machines, collision, object lifetime, the moves input parser) but NOT
## GodotRenderBackend. Rendering is verified separately via match.tscn.
##
##   /Applications/Godot.app/Contents/MacOS/Godot --headless \
##       --path . res://tools/verify/m0_smoke.tscn

const FRAMES := 600
const FIGHTER_YAML := "res://data/ryu/ryu.yml"
const MOVES_YAML := "res://data/ryu/moves.yml"

var _fight: Node2D
var _frame := 0

func _ready() -> void:
	if not ClassDB.class_exists("OpenFightNode"):
		printerr("FAIL: OpenFightNode is not registered -- build addons/openfight first")
		get_tree().quit(1)
		return

	# Required because GameContext::setup() silently returns false when a data
	# file is missing, which would otherwise look like a pass.
	for path in [FIGHTER_YAML, MOVES_YAML, "res://data/background.png"]:
		if not ResourceLoader.exists(path) and not FileAccess.file_exists(path):
			printerr("FAIL: missing data file %s" % path)
			get_tree().quit(1)
			return

	_fight = ClassDB.instantiate("OpenFightNode")
	_fight.name = "OpenFight"
	add_child(_fight)

	# The important assertion. setup_game() ends with set_process(running), and
	# `running` is the return value of GameContext::setup(), which is false when
	# any data file fails to load. So is_processing() is the only externally
	# visible evidence that the engine actually came up -- without this check a
	# completely broken data path would still look like a pass, because the node
	# stays in the tree either way.
	if not _fight.is_processing():
		printerr("FAIL: setup_game() did not enable processing -- GameContext::setup() returned false")
		printerr("      check that data/ryu/ryu.yml and data/ryu/moves.yml resolve under res://")
		get_tree().quit(1)
		return

	print("OpenFightNode instantiated and simulating; stepping %d frames" % FRAMES)

func _process(_delta: float) -> void:
	_frame += 1
	if _frame < FRAMES:
		return

	var alive := is_instance_valid(_fight) and _fight.is_inside_tree()
	var simulating := alive and _fight.is_processing()
	print("PASS: %d frames, alive=%s, simulating=%s, player_one_path=%s" % [
		_frame, str(alive), str(simulating), str(_fight.get_player_one_path())])
	get_tree().quit(0 if simulating else 1)
