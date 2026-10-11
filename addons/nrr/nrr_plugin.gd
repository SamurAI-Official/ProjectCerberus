@tool
extends EditorPlugin

## NRR editor plugin entry point.
##
## Registered by plugin.cfg's `script=` line, so Godot instantiates this when
## the plugin is enabled. It probes the native binding once on enable and puts
## the result in the editor console, so "the plugin is enabled" is never
## confused with "neural rendering is running" - the exact confusion the old
## XML descriptor created, where the descriptor was not even parsed.

const _MENU_ITEM := "NRR status"


func _enter_tree() -> void:
	# Patched for this project: Godot 4's add_tool_menu_item() returns void, where Godot 3's returned
	# the item id. Assigning it to an int is a parse error, so the plugin could never load at all -
	# not because a binding was missing, which is what this project first assumed, but because the
	# line cannot compile under Godot 4 whatever is built. remove_tool_menu_item() takes the name
	# rather than an id in Godot 4 too, so no id was needed to begin with.
	add_tool_menu_item(_MENU_ITEM, _print_status)
	_print_status()


func _exit_tree() -> void:
	remove_tool_menu_item(_MENU_ITEM)


func _print_status() -> void:
	var nrr := NRR.new()
	var ok := nrr.initialize()
	if not ok:
		print_rich(
			"[NRR] plugin enabled, native binding NOT loaded for this platform "
			+ "(%s). Rendering is passthrough; build engine_plugins/godot/src "
			+ "and copy the library into addons/nrr/bin/ to enable it."
			% nrr.last_error)
		return

	var caps := nrr.capabilities()
	# Patched for this project: % binds tighter than + in GDScript, so the line below used to parse as
	# "…entry_points=%d " + ("neural_acceleration=%s" % [four arguments]) - one placeholder fed four
	# arguments, which Godot reports as "not all arguments converted during string formatting" and
	# which printed the whole line with its %s markers still in it. The brackets make the format string
	# the concatenation, which is what was meant.
	print_rich(
		("[NRR] native binding loaded. library=%s backend=%s entry_points=%d "
		+ "neural_acceleration=%s") % [nrr.library_version(), nrr.backend_name(),
		   nrr.native_entry_point_count(),
		   str(caps.get("neural_acceleration", "absent"))])
	nrr.shutdown()
