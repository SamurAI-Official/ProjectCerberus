# openfight patch series

`vendor/openfight` is a pinned submodule and is **never hand-edited as a matter
of record**. Every change to the engine lives in a numbered patch file here.

Pinned commit: see `PINNED_COMMIT`
(https://github.com/nonameentername/openfight @ `3828952`)

```sh
./patches/openfight/apply.sh            # apply
./patches/openfight/apply.sh --check    # verify, change nothing
```

`apply.sh` is idempotent — it detects an already-applied patch with
`git apply --reverse --check` and skips it.

After applying, `git status` in the project root will show
`vendor/openfight (modified content)`. That is expected and intentional: the
patches are applied in place because `tools/build/build_openfight.sh` builds
from `vendor/openfight` directly. The submodule's recorded commit never changes,
so the patch file — not the dirty worktree — is the source of truth.


## Why patch instead of fork

1. The build is reproducible from "pinned commit + this series", and an upstream
   rebase is a rebase rather than archaeology.
2. openfight is **LGPL-3.0**. We dynamic-link it through the GDExtension and
   publish the modified source as these patches, which satisfies the
   relinking/source obligations without putting our game code under the LGPL.
3. It keeps the diff reviewable. `0001` is 11 files and 660 lines; a fork would
   make that a branch to go and find.

## 0001-health-rounds-and-signals.patch

The engine had no way to run a match. Verified before writing anything:

* `Player` has **no health field at all** — `grep -n health src/libopenfight/`
  returns nothing.
* `OpenFightNode::_bind_methods()` bound four settable strings and two methods,
  and **zero signals** — so GDScript could not observe hits, damage or a winner.
* `GameContext` had no round concept; `update()` even discarded its `delta_ms`
  with `(void)delta_ms;`.
* openfight's own `ROADMAP.md` lists "Health tracking for players" and "Support
  for multiple rounds" as unchecked.

### What the patch adds

| File | Change |
|---|---|
| `matchEvents.h` *(new)* | `MatchEvent` / `MatchEventType` — the seam between engine and host |
| `player.{h,cpp}` | `health`/`max_health`, `takeDamage`, `isKO`, `getCurrentState`, a match listener, and `resetForRound()` |
| `yaml.cpp` | optional `character.health` key (defaults to 100, so existing YAML is untouched), and capture of the spawn transform |
| `actions.cpp` | damage resolution + `HIT` event emission in `CollisionAction::doAction()` |
| `gameContext.{h,cpp}` | best-of-three rounds, a round clock, a KO beat, and the event queue |
| `playerAgent.{h,cpp}` | `getPlayer()` made `const` so the const accessors compile |
| `openFightNode.{h,cpp}` | 9 bound methods and 4 signals |

### Where damage is applied, and why there

`CollisionAction::doAction()` is the single point where a blow lands. It already
called `opponent->updateState(to_opponent, true)` and already knew whether that
succeeded (`opponent_updated`), so it is the only place with both the attacker
and the resolution result in hand:

```cpp
if (to_opponent.size() > 0)
    opponent_updated = opponent->updateState(to_opponent, true);

if (!opponent_updated)
    return;                        // <- nothing landed; no damage, no event
```

**Blocking is a state name, not a flag.** openfight's data maps one attack
trigger to either `block_*` or `hurt_*` depending on what the defender was
doing, and `updateState()` reports success for both. So the block test is the
prefix of the resulting state:

```cpp
bool stateIsBlock(const string &state) { return state.rfind("block", 0) == 0; }
```

### Damage table

The triggers the shipped data actually uses are not only `HIT_*` —
`grep -rhoE 'opponent: [A-Z_]+' data/` returns `HIT_H`, `HIT_M`, `HIT_L`,
`KNOCK_DOWN` and `THROWN`. All five are covered. An unrecognised trigger falls
back to the medium value rather than dealing zero, because a silently harmless
attack is much harder to notice than a wrong number.

| Trigger | Damage | Blocked (chip) |
|---|---|---|
| `HIT_L` | 4 | 1 |
| `HIT_M` | 7 | 1 |
| `HIT_H` | 11 | 1 |
| `KNOCK_DOWN` | 10 | 1 |
| `THROWN` | 9 | 1 |

### Round flow, verified

`tools/verify/m1_match.tscn` plays a real match headless and asserts on the
signals. Observed on a passing run:

```
round 1 started (p1=100 p2=100 hp)
first hit: attacker=0 defender=1 damage=11 blocked=false strength=HIT_H state=hurt_high -> p2 health=89
round ended: winner=0 time_over=false wins=(1,0) health=(100,0)
round 2 started (p1=100 p2=100 hp)
round ended: winner=0 time_over=false wins=(2,0) health=(100,0)
match ended: winner=0 after 20 hits
PASS: hits, damage, round rotation and match end all behaved
```

20 hits × 11 damage = 220 total, which is 200 to KO two rounds plus 20 overkill —
internally consistent. The attacker finishes at 100 because it was the only
fighter acting.

### Deliberate choices worth knowing

* **Time over is a health comparison**, equal health is a draw. There is no
  sudden death; that is a design decision, not an oversight.
* **A double KO credits nobody** a round win, so both fighters keep their count.
* **During the KO beat** (`ROUND_END_DELAY_MS`, 2.5s) the fighters keep
  animating so the knockdown plays out, but receive zeroed input. That is the
  gap an announcer needs.
* **`ROUND_TIME_MS` is 99000** because `GAME_TIME_UPDATE_FREQ` is 10ms, i.e. the
  simulation runs at 100Hz, so 99,000ms is 99 seconds of game time.
* **Attacker identity is not `inverted`.** `PlayerBridge` flips `inverted`
  whenever the fighters cross over each other, so it cannot identify a player.
  An explicit `player_number` was added for that.

### Event delivery

`OpenFightNode::emitMatchEvents()` drains the queue **once per process frame,
after the fixed-step loop**, so a frame that stepped several 10ms ticks still
reports every hit. It iterates a **copy** of the batch, because emitting a
signal runs GDScript synchronously and a handler is very likely to call
`reset_match()` or `start_round()` — which would mutate the vector mid-iteration.
