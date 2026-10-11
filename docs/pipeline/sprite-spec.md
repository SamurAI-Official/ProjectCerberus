# Sprite & frame spec (openfight)

Everything here was read out of the vendored engine at `vendor/openfight`, not
assumed. Where the engine and the upstream `data/` disagree, that is called out.

## 1. Source PNGs

| Property | Value | Source of truth |
|---|---|---|
| Frame canvas | **64 x 128 px** | `data/ryu/idle00.png` header (`struct` read) |
| Colour type | **8-bit, colortype 2 = RGB, no alpha channel** | same |
| Transparent key | **black `#000000`** | `SdlGlRenderBackend::createMask()` |
| Naming | `<animation>NN.png`, zero-based, 2 digits: `idle00.png` … `idle05.png` | `data/ryu/` inventory (143 frames) |
| Location | flat, one directory per fighter: `data/<fighter>/` | `yaml.cpp` frame parsing |
| Per-fighter volume | **~29 animation states / ~143 frames** for the stock Ryu | `data/ryu/*.png | wc -l` |

### The key colour is black, not magenta

`data/notes` says magenta is involved, but it is an *input* colour that the
import step replaces:

```
convert *.pcx -fill black -opaque '#fa00fa'        # magenta -> black
mogrify -format png *.pcx                           # pcx -> png
convert *.png -background black -gravity center \
        -extent 64x128 output.png                   # pad on black to 64x128
```

`createMask()` is what actually decides transparency, and it treats **black or
zero-alpha** as transparent:

```cpp
if (alpha == 0 || (red == 0 && green == 0 && blue == 0))
    setPixel(..., transparent_mask /*white*/);
else
    setPixel(..., opaque_mask /*black*/);
```

Consequence for our art: **do not ship magenta.** Every frame is padded onto a
black canvas and black is the key. Any near-black pixel in the character art is
also a key, so characters should not use pure black for line work — use
`#010101` or a dark tint instead. (This is a real constraint on the art spec.)

## 2. How the SDL backend composites (the intended look)

`drawSprite()` is a two-pass blend, which is why the stock art is drawn on black:

1. mask pass — bind the black/white silhouette with
   `glBlendFunc(GL_DST_COLOR, GL_ZERO)`, i.e. **multiply**: destination is
   zeroed exactly where the character is opaque.
2. sprite pass — bind the sprite with `glBlendFunc(GL_ONE, GL_ONE)`, i.e.
   **additive**: the sprite's own RGB is added back.

So the character is composited *additively* and its black background is a
no-op (`dest + 0`). That is why the stock characters read slightly glowy against
dark backgrounds. This is a design decision worth preserving deliberately or
replacing deliberately — not something to discover later by accident.

## 3. Transparency on the Godot backend — how it actually works

This was initially misread from the source and then checked against a render.
Recording the correction, because the wrong version of this note would have sent
the art pipeline chasing a bug that does not exist.

`GodotRenderBackend::loadTexture()` opens with what looks like a stubbed-out
parameter:

```cpp
unsigned int GodotRenderBackend::loadTexture(const std::string &file_name, bool mipmap, bool masking) {
    (void)mipmap;
    (void)masking;          // <-- looks disabled ...
    ...
    if (masking) {          // ... but the block below is fully implemented
        image->convert(Image::FORMAT_RGBA8);
        for (row) for (column) {
            Color pixel = image->get_pixel(column, row);
            if (pixel.r == 0 && pixel.g == 0 && pixel.b == 0) pixel.a = 0.0f;
            else                                               pixel.a = 1.0f;
            image->set_pixel(column, row, pixel);
        }
        texture = ImageTexture::create_from_image(image);
    }
```

The `(void)masking;` casts are redundant, not a disable. So the key **is**
applied — to the *mask* texture. And `Animation::addFrame()` calls
`texture_manager->addMask()` and `sprite->setMask()` for every frame, so
`has_mask` is permanently true and `drawSprite()` always takes this branch:

```cpp
Ref<Texture2D> godot_texture = has_mask ? getTexture(mask) : getTexture(texture);
```

Net result: the keyed image is what gets drawn, and fighters composite
correctly. Verified rather than assumed — `tools/verify/m0_render.tscn` renders
a match and a pure-black census of the output frame finds **2.21%** pure-black
pixels, all of them inside the background art (`x >= 560`). There are no sprite
padding rectangles.

### Three real differences from the SDL build, all worth knowing

1. **Blend mode.** SDL composites with a two-pass multiply + `GL_ONE, GL_ONE`
   additive, so characters glow slightly against dark backgrounds. Godot uses
   ordinary alpha blending on a `draw_texture_rect`. The same art will *not*
   look identical across the two backends — expect the Godot build to read
   flatter.
2. **Alpha is hard-keyed.** The loop forces `alpha` to 0 or 1, so it discards any
   partial transparency in the source art. Do not rely on semi-transparent
   sprite pixels for effects such as illusions or afterimages; use the
   per-character `alpha:` YAML field instead (which is how `data/collision`'s
   `alpha: 0.7` works).
3. **The sprite texture is never drawn.** `decal`/`texture` is uploaded and
   then unused. Palette-swap work should therefore build on the mask path
   (`drawSprite`'s `color` modulate is already threaded through), not on the
   sprite path.

**No patch is needed for M0 rendering.**


## 4. Per-frame YAML

Each state in `<fighter>.yml` is an `animation:` entry whose `frame:` list maps
1:1 onto the numbered PNGs. Frame fields, as parsed by `yaml.cpp`:

| Field | Meaning |
|---|---|
| `path` | PNG path, resolved as `res://<path>` (`ResourceLoader` with a `res://` fallback) |
| `width`, `height` | **logical draw size**, not the 64x128 canvas — e.g. `20 x 40` |
| `delay` | frames held; `nextFrame()` advances when `delay < current_delay`, so `delay: 10` = 11 ticks |
| `move.x_vel`, `move.y_vel` | per-frame physics, applied by `MoveAction` |
| `defense` | hurtbox list, `{x_pos,y_pos,width,height}`, drawn blue |
| `offense` | hitbox list, `{x_pos,y_pos,width,height}`, drawn red |
| `collision` | hit payload: `{path, opponent: HIT_L\|HIT_M\|HIT_H, x_pos, y_pos, index}` — the trigger name handed to the opponent's state machine |

`collision.opponent` is the whole hit/block system: `CollisionAction::doAction`
calls `opponent->updateState(to_opponent, true)`, and **the defender's own
`action:` table decides the outcome** (`HIT_M` → `block_high` while holding back,
`hurt_mid` otherwise). That is why one attack value produces both a block and a
hit. Damage has to be attached in that same call — which is where the M1 health
patch hooks in.

## 5. Godot import settings

The `.import` files are committed (they carry the settings). Read the real one
at `data/ryu/idle00.png.import` rather than trusting a summary. What it actually
contains, and what matters:

* `compress/mode=0` — Lossless. BC/VRAM compression (`compress/channel_pack`,
  `compress/hdr_compression`) would smear the black key into the art and produce
  halos around every sprite. Do not change this.
* `process/fix_alpha_border=true` — the committed value. It is a no-op on this
  art because colortype 2 has no alpha channel at all; the engine supplies
  transparency at runtime from the black key, not from the file.
* `mipmaps/generate=false` — correct as-is. The sprite is drawn at an integer
  scale (`OpenFightNode` is `scale = Vector2(4, 4)` inside a `canvas_items`
  stretch), so mipmaps could only soften it.
* There is **no filtering setting in the `.import`**. Filtering is decided by
  the CanvasItem/project default, so crisp pixel art is a *project* setting:
  `rendering/textures/canvas_textures/default_texture_filter=0` (Nearest).
  Set it when the art is final; with the stock Ryu it makes the pixel art sharp
  rather than bilinear-smeared.

