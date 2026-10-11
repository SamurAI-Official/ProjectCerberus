extends CanvasLayer
class_name FpsCounter
## The frame rate, in the upper right corner of the render area.
##
## A CanvasLayer rather than part of any screen, because the number is about the
## program rather than about the menu you happen to be on: a frame rate that only
## appeared during a match would be missing exactly when a slow menu was the thing
## worth looking at. Attached once to the flow host, and nothing else needs to know
## it exists.
##
## It is off by default. A frame counter is a diagnostic, and a diagnostic that
## nobody can turn off is a watermark.

const NODE_NAME := "FpsCounter"
## Inset from the corner, in the game's own pixels. Enough to clear the bezel,
## small enough not to read as part of the HUD.
const MARGIN := 4
const FONT_SIZE := 12

## Text as shown, kept so a check can read the same string the player sees rather
## than recomputing it and asserting on its own arithmetic.
var last_text := ""

var _label: Label
var _elapsed := 0.0
var _frames := 0


func _init() -> void:
	layer = 128
	name = NODE_NAME


func _ready() -> void:
	var canvas := Control.new()
	canvas.name = "FpsCanvas"
	canvas.set_anchors_preset(Control.PRESET_FULL_RECT)
	canvas.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(canvas)

	_label = Label.new()
	_label.name = "FpsLabel"
	# Anchored to the corner and grown leftwards, so the text never runs off the
	# right edge however many digits the frame rate grows to.
	_label.set_anchors_preset(Control.PRESET_TOP_RIGHT)
	_label.grow_horizontal = Control.GROW_DIRECTION_BEGIN
	_label.offset_top = MARGIN
	_label.offset_right = -MARGIN
	_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	_label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_label.add_theme_font_size_override("font_size", FONT_SIZE)
	_label.add_theme_color_override("font_color", Color(0.85, 0.92, 0.88, 0.85))
	# A dark plate behind it: the game is a fighting game, and a light UI over a
	# light stage would otherwise be unreadable at exactly the wrong moment.
	_label.add_theme_color_override("font_outline_color", Color(0.02, 0.02, 0.03, 0.9))
	_label.add_theme_constant_override("outline_size", 4)
	canvas.add_child(_label)

	_update()


func _process(delta: float) -> void:
	_accumulate(delta)


## Averaged over a real interval rather than read from
## Engine.get_frames_per_second(), which reports the last frame and therefore
## flicks through digits that mean nothing. A tenth of a second is short enough to
## feel live and long enough to read.
func _accumulate(delta: float) -> void:
	_elapsed += delta
	_frames += 1
	if _elapsed < 0.1:
		return
	_elapsed = 0.0
	var fps := int(round(float(_frames) / 0.1))
	_frames = 0
	last_text = "FPS %d" % fps
	if _label != null:
		_label.text = last_text


## One shot, for the first paint and for a check that has no frames to wait for.
func _update() -> void:
	last_text = "FPS %d" % Engine.get_frames_per_second()
	if _label != null:
		_label.text = last_text


## The label's rectangle in the render area's coordinates. Exposed because "upper
## right" is a claim about geometry, and a claim about geometry should be checkable
## rather than eyeballed.
func rect() -> Rect2:
	if _label == null:
		return Rect2()
	return _label.get_global_rect()


## Attaches one to `host` if it is not already there, and gives it back. Static for
## the same reason Upscaler's attach is: the caller is a host that may already have
## one from a previous screen.
static func attach(host: Node) -> FpsCounter:
	if host == null or not host.is_inside_tree():
		return null
	var existing := host.get_node_or_null(NODE_NAME)
	if existing is FpsCounter:
		return existing
	var counter := FpsCounter.new()
	host.add_child(counter)
	return counter


static func set_shown(host: Node, shown: bool) -> void:
	var counter := attach(host) if shown else find(host)
	if counter != null:
		counter.visible = shown


static func find(host: Node) -> FpsCounter:
	if host == null:
		return null
	var node := host.get_node_or_null(NODE_NAME)
	return node if node is FpsCounter else null
