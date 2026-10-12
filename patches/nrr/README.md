# NRR patch series

NRR is built from a pinned upstream commit into a throwaway work directory and is **never
hand-edited as a matter of record**. Every change this project needs in it lives in a numbered
patch file here.

Pinned commit: see `PINNED_COMMIT`
(https://github.com/SamurAI-Official/NRR @ `198dba7`)

```sh
./patches/nrr/apply.sh                     # apply to the build work directory
./patches/nrr/apply.sh --check             # verify, change nothing
./patches/nrr/apply.sh /some/other/nrr     # an explicit checkout
```

`tools/build_nrr_macos.sh` runs this at its step 3, after checking out the pinned revision and
before configuring. `apply.sh` is idempotent, using the same first-patch-forward /
last-patch-reverse test as `patches/openfight/apply.sh` — and for the same reason, recorded there:
a per-patch test is wrong as soon as two patches share a file.

The checkout is not a submodule, unlike `vendor/openfight`. What this project vendors is NRR's
*Godot-side addon* (`addons/nrr`: the GDScript wrapper, the descriptor, the shaders), because the
native library is per-platform build output and upstream's own README asks that it not be
committed. So the source is a build input that the build script fetches, and the series is applied
to it in place. The wrapper and the library must agree; as of this pin
`engine_plugins/godot/NRR.gd`, `nrr_post_process.gd` and `plugin.cfg` are byte-identical to the
vendored copies, which is what makes building a newer library against the vendored addon safe.

## Why this pin

The pin is a recent `main` commit plus everything below. It is not `main` itself because a pin that
moves without a measurement is not a pin, and because the build's step-3 guard has to refuse the
revision that does not compile: `4779165` calls `compute_history_trust_mask_from_textures()` and
`warp_input_history_to_nchw()`, defined nowhere in the tree, and uses
`TemporalAccumulator::phase_aligned_source()` and `PhaseAlignedFrame::input_render`, which
`runtime/nrr_temporal.h` does not declare. That state is still refused rather than discovered 200
lines into a compile.

## 0001-clang-default-arguments.patch

`TemporalAccumulator::apply()` in `runtime/nrr_temporal.h` declared two parameters with defaults
that default-construct *nested* structs:

```cpp
const PhaseAlignedFrame& phase = PhaseAlignedFrame(),
const DepthProvider& depth = DepthProvider());
```

A default argument is read in the class body, where those nested types are still incomplete, so
clang refuses it — verbatim from the build log, once per default member initializer involved:

```
runtime/nrr_temporal.h:654:12: error: default member initializer for 'eligible' needed within
definition of enclosing class 'TemporalAccumulator' outside of member functions
runtime/nrr_temporal.h:618:12: error: default member initializer for 'pixels' needed within
definition of enclosing class 'TemporalAccumulator' outside of member functions
```

MSVC permits it, which is why it survived upstream. The patch drops both defaults and adds a
5-argument and a 6-argument overload whose bodies are *member functions*, where the types are
complete, and which build the defaults and forward. Behaviour is unchanged in the built path:
both call sites in the tree (`runtime/backend_cpu.cpp`, `runtime/accel_kernel.cpp`) already pass
all seven arguments.

## 0002-godot-plugin-godot4.patch

`engine_plugins/godot/nrr_plugin.gd` is pure GDScript, so this one is broken for everyone rather
than only for a machine without a built library. Two Godot 3 leftovers:

1. `add_tool_menu_item()` returned an item id in Godot 3 and returns void in Godot 4, so assigning
   it to an int is a parse error and the plugin cannot load at all.
2. `"%s" % [...]` binds tighter than the `+` that joins the format string to its other half, so
   four arguments were fed to a one-placeholder string ("not all arguments converted").

## 0003-macos-onnxruntime-arm.patch

**This is the one that mattered**, and the symptom it fixes was misdiagnosed for a while, so the
diagnosis is worth recording in full.

`CMakeLists.txt` recognised ONNX Runtime in exactly two layouts: Android's
`lib/<abi>/libonnxruntime.so`, and Windows' `lib/onnxruntime.lib` — the MSVC import library. The
official macOS/Linux release tarball has neither name: it unpacks to `include/` plus
`lib/libonnxruntime.dylib` (and `lib/libonnxruntime.<ver>.dylib`, install name
`@rpath/libonnxruntime.1.dylib`). So on a Mac neither arm matched, `NRR_HAVE_ONNXRUNTIME` stayed
`OFF`, and the configure log said it plainly:

```
-- ONNX Runtime: not found (placeholder inference path)
```

The runtime then builds its *placeholder* inference path, which does not fail; it renders. That path
hardcodes `input_shapes_ = {{1,3,512,512},{1,1,512,512},{1,2,512,512}}` in `onnx_runtime.cpp`
(`4`), so `concrete_input_shape()` sees a static 512x512, every other frame size is refused with
`conflicts with the model's static input shape`, and 512x512 "succeeds" in ~1.9 ms without an
`OrtSession` in sight. That is the whole of the "the binding only accepts 512x512" behaviour this
project measured and wrote down as an old revision.

With the arm added, the same build reports real inference and the model's real metadata:

```
-- ONNX Runtime: .../onnxruntime-osx-arm64-1.30.0 (real inference, CPU EP only)
inputs: color [1,3,-1,-1]  jitter [1,2,-1,-1]  scale [1,1,-1,-1]
```

## 0004-godot-read-back-output-texture.patch

The second half of the same misdiagnosis, and it only becomes visible once a real session is linked.

`nrr_render()` writes the frame it produced into `output.color`, and the runtime *replaces* that
pointer with its own texture — one sized to the **model's output grid**, which is the model's ratio
(`runtime/backend_cpu.cpp`: `out_w/out_h` come from the model's output tensor through
`nchw_to_rgb8`). The Godot binding ignored that: it allocated a texture at the *input* size, passed
it in, and then downloaded from *its own* texture and returned an image at the input size. The
result was a frame that was correctly sized, correctly formatted, entirely zero — with
`get_last_error()` empty and `last_render_was_passthrough` false, so nothing pointed at it.

The patch reads the size, format and pixels back from what the runtime handed over. The format
matters as much as the size: the runtime's output texture is `RGB8`, so a buffer sized for RGBA8
asks `nrr_texture_download` for more bytes than the texture holds.

Measured after both patches, headless, macOS arm64, CPU provider, release build:

```
  64x48       -> 128x96       5.2 ms
  384x216     -> 768x432    200.1 ms
  768x432     -> 1536x864   834.4 ms   (the released 2x model)
 1024x576     -> 2048x1152 1439.8 ms
```

`tools/verify/nrr_output_check.gd` is what made the second bug visible: it pushes a checkerboard
with four differently-coloured edges through the pass and writes both frames, so a crop, a
same-size refinement, a resample, and an empty frame are four different pictures. It was the empty
frame.

## 0005-macos-coreml-execution-provider.patch

The Apple GPU, which was the one accelerator NRR itself could not reach. `apply_provider()` in
`runtime/onnx_runtime.cpp` offers `cpu`, `auto`/`cuda`, `tensorrt`, `directml` and a list of names it
names but does not implement; CoreML is in none of them, so on this machine the only provider NRR
could attach was the CPU — while ONNX Runtime's own `GetAvailableProviders()` listed
`CoreMLExecutionProvider` in the library the build had already linked.

Four parts, and the first is the one that makes the rest possible:

1. **`CMakeLists.txt`** — `NRR_HAVE_COREML_EP`, set from `include/coreml_provider_factory.h` in the
   macOS ONNX Runtime arm. The test is a header rather than a provider library because on Apple
   platforms CoreML is compiled *into* `libonnxruntime`; there is no `onnxruntime_providers_coreml.*`
   to look for the way the CUDA arm looks for `onnxruntime_providers_cuda.dll`. Configure now says
   so explicitly:

   ```
   -- ONNX Runtime: .../onnxruntime-osx-arm64-1.30.0 (real inference, CoreML EP available)
   ```

2. **`append_coreml_provider()`** — `OrtSessionOptionsAppendExecutionProvider_CoreML()` with
   `COREML_FLAG_CREATE_MLPROGRAM | COREML_FLAG_USE_CPU_AND_GPU`. The MLProgram representation is what
   the EP's own documentation recommends for anything newer than Core ML 5 and what a convolution
   stack needs to avoid falling back node by node. There is no driver probe to make and no vendor
   runtime to fail to load, so — unlike the CUDA arm — the return value of the attach is the whole
   measurement.

3. **`NRR_EXECUTION_PROVIDER=coreml`** — a new explicit request, and *not* a new member of `auto`.
   That is the point rather than an oversight: `auto` promises the best provider the package can
   offer, and on Apple silicon "best" turned out to be false. Measured on this machine, same build,
   same released 2x model, `tools/verify/nrr_probe.tscn`, both providers under the same load (an
   SDXL sampling run was in progress, so the absolute numbers are inflated; the comparison is not):

   ```
     size                     CPU         CoreML
     64x48     ->  128x96      10.4 ms     32.2 ms
     384x216   ->  768x432    303.7 ms    386.6 ms
     768x432   -> 1536x864   1033.6 ms   1217.4 ms   <- the 2x tier
    1024x576   -> 2048x1152 1797.1 ms   2296.3 ms
    1024x1024  -> 2048x2048 3010.9 ms   6934.3 ms
   ```

   ONNX Runtime's own log line says what the EP did with the graph — `number of partitions supported
   by CoreML: 3 ... number of nodes supported by CoreML: 44` of 52 — and `model_info` reports
   `"provider": "CoreMLExecutionProvider"`, so this is a real offload, not an attach that quietly did
   nothing. It is still slower everywhere the game cares: the 44 offloaded nodes are the convolutions,
   the 8 left on the CPU sit in the middle of the graph, and the probe measures the *first* call at
   each size in a fresh process, which includes Core ML's per-shape compilation. Whether a warmer,
   single-size loop reverses that is a measurement to make before anyone moves this into `auto`;
   until then the fast path is opt-in and the default is the provider that was measured.

4. **The accelerator caps** — `AccelEP::COREML`, `AccelCapabilities::supports_coreml` (measured from
   `GetAvailableProviders` like the others), `"Apple" -> COREML` in `accel_ep_for_vendor()`, and
   `CoreMLExecutionProvider -> AccelEP::COREML` in `apply_measured_provider()`. Without the last one
   a session that *ran* on CoreML reported `AccelEP::CPU`, because the mapping simply had no arm for
   the name — the caps would have gone on claiming the CPU while the GPU did the work. `COREML` is
   appended to the enum rather than slotted beside the other GPU providers because these enumerators
   are reported as numbers by the diagnostics, and inserting one in the middle renumbers everything
   after it.

Built and verified on this machine: the series applies cleanly to a pristine `198dba7` checkout
(`apply.sh` → `series complete`), configure reports the CoreML EP, the library builds and installs,
and the probe renders every size through it with `err=''` and non-empty output.

## Training the 2.5x model ourselves

The upscaler the game ships is upstream's release model; our own is trained at `--ratio 2.5`, and
the whole training path lives in the pinned checkout (`tools/train_nrr.py`,
`tools/gen_training_pairs.py`), so it is reproducible from the pin plus this series:

```bash
bash tools/build_nrr_macos.sh build/nrr-work     # clone at the pin, apply the series
cd build/nrr-work/nrr
python3 tools/gen_training_pairs.py --out models/training-data/v1 --count 32 --size 768 --ratio 2.5
~/ComfyUI/venv/bin/python tools/train_nrr.py --data models/training-data/v1 \
    --out models/nrr_upscaler_25x_ours.onnx --ratio 2.5 --size 768 --inputs= --epochs 60
```

Three things measured on this machine, each of which changes what the command has to say:

  * **`--inputs=color` is not a value it has.** `--inputs` lists the inputs *besides* colour,
    which is always first (`requested = ["color"] + args.inputs.split(",")`), so passing `color`
    there asks for it twice. Colour-only training is `--inputs=`, and the run prints
    `inputs: color` either way.
  * **`--device auto` means the CPU here.** The script's choices are `auto|cpu|cuda`, and `auto`
    resolves to CUDA when the torch build has it. The interpreter with our torch -- ComfyUI's
    venv, 2.14.1 -- has none, and MPS is not one of the choices, so the run prints `device: cpu
    (torch 2.14.1 has no CUDA support; cuda build is None)`. It trains (an 88,590-parameter model
    stepped loss fine), but it is not using the GPU this machine has.
  * **The pairs are square.** `--size 768 --ratio 2.5` generates 768x768 against a 1920x1920
    target; `768x432 -> 1920x1080` is the generator's own docstring example, not its `--size`
    shape. The 16:9 case the game wants is the *lighter* one, so a first real run should use
    `--size 512` (1280x1280) while the data path is still being shaken out.

Generating 32 pairs at `--size 768` took 1:43 and 301 MB (135 MB at `--size 512`). Training at the
generator's default `--batch-size 2` with the trainer's default `--measure-batch 32`, though,
provokes swap faster than the system gives it back: on this 16 GB machine the volume sawtoothed
13 -> 7.4 GB free during the first epoch, at roughly 1 GB every two minutes. That is not a slow
run, it is a run that fills a volume while nobody is looking -- and two SDXL runs in this project
have already ended that way, with a reboot to get the disk back.

So the two batches were measured against each other, same data, same ratio, same size:

```
--batch-size 2 --measure-batch 32    epoch 1 in ~6 min   volume 10.0 -> 8.4 GB free   swap 7.0 GB
--batch-size 1 --measure-batch 8     epoch 1 in ~4 min   volume flat at 11 GB         swap 3.6 GB
```

The lean pair is the one to use, but **the pace of a full run is not yet established and the first
attempt was stopped because of that**. What is measured is the first epoch of each configuration:

```
--batch-size 2 --measure-batch 32    epoch 1 in ~6 min   volume 10.0 -> 8.4 GB free   swap 7.0 GB
--batch-size 1 --measure-batch 8     epoch 1 in ~4 min   volume flat at 11 GB         swap 3.6 GB
```

That is one epoch each, and epoch 1 is the cheapest one. A 60-epoch run of the lean pair was
started and abandoned after epoch 2 had run for **more than twelve minutes** against epoch 1's
three -- the log is `--flush`ed per line (the trainer's `log` is `print(..., flush=True)`), so that
is real time, not buffering, and it puts the whole run anywhere between four and twelve hours.
Worse, `train_nrr.py` contains no `torch.save`, no checkpoint and no resume: a run that is killed
at hour six produces nothing at all. So before any long run, measure two or three epochs with the
clock, on a machine that is otherwise idle, and decide what to do about checkpointing -- that is a
patch of its own, and it is not in this series.

```bash
~/ComfyUI/venv/bin/python tools/train_nrr.py --data models/training-data/v1_512 \
    --out nrr_upscaler_25x_ours.onnx --ratio 2.5 --size 512 --inputs= --epochs 60 \
    --batch-size 1 --measure-batch 8 --device auto --lazy
```

The bar it has to clear is upstream's own trained 2.5x model, committed under `models/ratio25/` at
this pin and recorded there as 58.37% under its ratio's baseline.

