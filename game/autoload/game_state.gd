extends Node
## Menu flow, the pending match configuration, and the last match result.
##
## One object rather than separate GameState and MatchConfig autoloads: "what
## match am I about to play" and "where am I in the flow" disagreeing is a class
## of bug that is cheap to avoid by simply not creating it. Character select
## writes this, MatchController reads it, Results reports into it.
##
## Screens are swapped as children of a host rather than via
## change_scene_to_file(), so the flow can be driven from a test: attach a host,
## walk goto(), assert on which screen is current.

signal screen_changed(screen_id: String)

## Screens may be a script (code-built menu) or a scene (the match, which needs
## an OpenFightNode and a HUD tree). Both are loaded the same way.
const SCREENS := {
	"title": "res://game/screens/title/title.gd",
	"char_select": "res://game/screens/char_select/char_select.gd",
	"stage_select": "res://game/screens/stage_select/stage_select.gd",
	"match": "res://game/screens/match/match.tscn",
	"results": "res://game/screens/results/results.gd",
	"options": "res://game/screens/options/options.gd",
}

const FIGHTER_MANIFEST := "res://data/fighters/manifest.json"
const STAGE_MANIFEST := "res://data/stages/manifest.json"

var fighters: Array = []
var stages: Array = []

## Pending match: indices into `fighters`. Both may be the same entry, which is
## the normal case for a mirror match and for the single-fighter dev roster.
var picks := [0, 0]
var stage_index := 0

var last_result := {
	"played": false, "winner": -1, "wins": [0, 0], "rounds": 0,
	"p1": "", "p2": "", "stage": "",
}

var current_screen := ""

var _host: Node = null
var _screen: Node = null

func _ready() -> void:
	fighters = _read_array(FIGHTER_MANIFEST)
	stages = _read_array(STAGE_MANIFEST)

func attach_host(host: Node) -> void:
	_host = host

func has_host() -> bool:
	return _host != null and is_instance_valid(_host)

func current_screen_node() -> Node:
	return _screen

## Returns false when the screen could not be shown. Callers do not have to check
## -- a missing host is a warning, not a crash -- but tests do.
func goto(screen_id: String) -> bool:
	if not SCREENS.has(screen_id):
		push_error("GameState.goto: unknown screen '%s'" % screen_id)
		return false

	if not has_host():
		# A verification scene may drive one screen directly with no flow host.
		# Navigation is then a no-op rather than a crash.
		push_warning("GameState.goto('%s') ignored: no host attached" % screen_id)
		return false

	var node := _instantiate(SCREENS[screen_id])
	if node == null:
		return false

	if _screen != null and is_instance_valid(_screen):
		_host.remove_child(_screen)
		_screen.queue_free()

	_screen = node
	_host.add_child(node)
	current_screen = screen_id
	screen_changed.emit(screen_id)
	return true

# --- roster and stages -------------------------------------------------------

func get_fighter(index: int) -> Dictionary:
	if fighters.is_empty():
		return {}
	return fighters[clampi(index, 0, fighters.size() - 1)]

func get_stage() -> Dictionary:
	if stages.is_empty():
		return {}
	return stages[clampi(stage_index, 0, stages.size() - 1)]

func fighter_yaml(index: int) -> String:
	return get_fighter(index).get("yaml", "")

func fighter_moves(index: int) -> String:
	return get_fighter(index).get("moves", "")

func fighter_name(index: int) -> String:
	return get_fighter(index).get("name", "?")

func stage_background() -> String:
	return get_stage().get("background", "")

func stage_name() -> String:
	return get_stage().get("name", "?")

func record_result(winner: int, wins: Array, rounds: int) -> void:
	last_result = {
		"played": true,
		"winner": winner,
		"wins": [int(wins[0]) if wins.size() > 0 else 0, int(wins[1]) if wins.size() > 1 else 0],
		"rounds": rounds,
		"p1": fighter_name(picks[0]),
		"p2": fighter_name(picks[1]),
		"stage": stage_name(),
	}

# --- internals --------------------------------------------------------------

func _instantiate(path: String) -> Node:
	if path.ends_with(".tscn"):
		var scene := load(path) as PackedScene
		if scene == null:
			push_error("GameState: could not load scene %s" % path)
			return null
		return scene.instantiate()

	var script := load(path) as GDScript
	if script == null:
		push_error("GameState: could not load screen script %s" % path)
		return null

	var instance = script.new()
	if not (instance is Node):
		push_error("GameState: %s does not extend Node" % path)
		return null
	return instance

func _read_array(path: String) -> Array:
	# load() first, because that is the export-safe path (Godot treats .json as a
	# resource). The FileAccess fallback keeps a non-exported run and the tooling
	# working even if the JSON importer is unavailable.
	var resource := load(path)
	if resource is JSON:
		var data = resource.data
		if data is Array:
			return data
		push_error("GameState: %s is not a JSON array" % path)
		return []

	if FileAccess.file_exists(path):
		var parsed = JSON.parse_string(FileAccess.get_file_as_string(path))
		if parsed is Array:
			return parsed
		push_error("GameState: %s is not a JSON array" % path)
		return []

	push_error("GameState: missing manifest %s" % path)
	return []
