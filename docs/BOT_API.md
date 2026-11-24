# CS 1.6 Bot Arena: bot API (protocol v1)

A bot is a program that controls one player in a real Counter-Strike 1.6 match. It sees only what
a player would see and hear, and it acts through a small set of commands. Any language works:
the bot talks JSON over stdin and stdout. Python bots can use the SDK (`arena_sdk`,
[section 8](#8-python-sdk-arena_sdk)), which does the protocol and has map and aiming helpers.

This page is the whole interface. The worked example is `bots/reference/bot.py` (Python, SDK);
`bots/examples/ts-minimal/` shows a bot in another language.

## 1. How a bot runs

- **One process per player.** On the platform the arena starts it with the `cmd` of its
  `bot.yaml`, run as written in a sandbox with its own Python or Node
  ([section 11](#11-uploading-to-the-platform)).
- **stdin:** one JSON message per line from the arena. **stdout:** one JSON message per line from
  the bot, UTF-8; flush after every line. **stderr:** your log
  ([Your log](#your-log)).
- Answer `hello` with `ready`, and every `tick` with exactly one `action` line. Send nothing in
  reply to `round_start`, `round_end` or `match_end`. Before `ready`, lines that are not `ready`
  are ignored. After that, any line that is not a valid action is taken as your answer to the
  current tick and rejected, so never print anything else to stdout.
- **Start.** The arena starts every bot when the first round of the match begins, sends `hello`
  and waits up to 10 s of wall-clock time for `ready`; the game waits too. Do slow set-up, such as
  reading the nav mesh, before you answer. A bot that has not answered after 10 s gets ticks
  anyway. A `ready` sent after those 10 s is read as your answer to a tick and rejected
  (`invalid`).
- **Deadline.** The arena sends a tick to every bot, then waits until each has answered or
  `deadline_ms` of wall-clock time (200 by default) has passed, and only then lets the game run
  the next tick. A fast bot lets the match run faster than real time; a slow bot slows the whole
  match.
- **Answers are matched by `tick`.** An action for another tick is dropped (it was late). An
  action without `tick` answers the tick the arena is waiting for, so a late answer without
  `tick` is applied to the next tick. Always echo `tick`.
- **Status of each answer**, as recorded in the replay:

  | Status | Meaning | What happens |
  |---|---|---|
  | `ok` | A valid action arrived in time. | It is applied. |
  | `timeout` | No answer by the deadline. | You stand still this tick; a warning in the next `obs.warnings`. |
  | `invalid` | The line was rejected (see [How an action is checked](#how-an-action-is-checked)). | You stand still this tick; a warning in the next `obs.warnings`. |
  | `error` | Your process is not running. | You stand still until it is restarted. |

  "Stand still" means no move, no turn and no buttons.
- **Crashes and restarts.** If your process exits or closes stdout, it is counted as a crash. At
  the start of the next round the arena runs `cmd` again, sends `hello` (with your side in that
  round), waits for `ready` and then sends `round_start`. Nothing carries over from the old
  process. A bot that cannot be started at the match start stops the match before it begins; one
  that cannot be restarted is tried again at the next round.
- Read stdin promptly. If more than 1 MiB of messages waits unread, the arena kills the bot and
  restarts it at the next round, as after a crash.
- While dead you still get ticks and must answer; your actions are ignored, `visible_enemies`,
  `bomb` and `sounds` are empty, and `teammates` is still sent.
- **End.** After `match_end` stdin closes. Exit within 2 s, or the process is killed. If the
  match is aborted (for example the game server goes away), stdin closes without `match_end`.

## 2. Message sequence

```text
arena → bot   {"type": "hello", "protocol": 1, "player_id": "p1", "side": "T", "map": {...}, "match": {...}, "config": {...}}
bot → arena   {"type": "ready"}
arena → bot   {"type": "round_start", "number": 1, "side": "T", "score": {"own": 0, "enemy": 0}}
arena → bot   {"type": "tick", "obs": {"tick": 1, ...}}     (tick_hz times per second of game time)
bot → arena   {"type": "action", "tick": 1, ...}            (one per tick)
              ... more ticks ...
arena → bot   {"type": "round_end", "number": 1, "winner": "CT", "reason": "t_eliminated", "score": {"own": 0, "enemy": 1}}
              ... ticks continue (phase "over") until the next round_start ...
arena → bot   {"type": "match_end", "result": "loss", "score": {"own": 7, "enemy": 16}}
              (stdin closes)
```

Messages from the arena always contain every field listed below. Ignore fields you do not know,
so that new fields can be added.

## 3. Conventions

- **Positions** are GoldSrc units (a player is 32 wide and 72 tall standing, 36 ducked), Z up.
  A player's `pos` is the origin, the centre of the player's box, 36 units above the floor when
  standing. Your eyes are 17 units above `pos` standing, 12 when ducked.
- **Yaw** is degrees, 0 = +X, increasing counter-clockwise (towards +Y), in (-180, 180].
  A positive yaw change turns left. To turn towards a world yaw `y`, send `dyaw = y - self.yaw`
  wrapped to ±180. In JavaScript `%` keeps the sign, so use `((d % 360) + 540) % 360 - 180`; in
  C use `fmod` and in Go `math.Mod` in the same formula.
- **Pitch** is degrees, **positive = looking up**, in [-89, 89]. The game engine itself uses the
  opposite sign (down positive); the arena converts, bots only see up-positive pitch.
- **Time** is game time in seconds; fields ending in `_ms` are milliseconds. `deadline_ms` is
  wall-clock time; every other `_ms` field is game time. The match can run faster than real time,
  so use these values, not your own clock.
- **Ticks:** the arena sends a tick `tick_hz` times per second of game time (20 by default, one
  tick = 50 ms). `tick` is 1 on the first tick of the first round and counts up for the whole
  match.
- **Distances** are straight-line, in units.

## 4. Messages

### hello (arena → bot)

| Field | Type | Meaning |
|---|---|---|
| `type` | `"hello"` | |
| `protocol` | `1` | Protocol version. |
| `player_id` | string | Your id; other players' ids appear in `visible_enemies`, `teammates` and `events`. |
| `side` | `"T"` \| `"CT"` | Your side now. Sides switch at half time: see `round_start.side`. |
| `map` | object | Static map data, see [Map data](#map-data-hellomap). |
| `match` | object | The match settings (rounds, times, money), see [section 6](#6-settings). |
| `config` | object | The rules of what you see and hear, see [section 6](#6-settings). |

An example (the lists in `map` are shortened; de_dust2 has 20 spawns per side and 737 nav areas):

```json
{
  "type": "hello", "protocol": 1, "player_id": "p1", "side": "T",
  "map": {
    "name": "de_dust2",
    "bombsites": {"A": [[1024, 2304, 96], [1280, 2624, 192]], "B": [[-1728, 2496, 0], [-1344, 2880, 96]]},
    "buyzones": {"T": [[[-1088, -960, 0], [-384, -576, 288]]], "CT": [[[-192, 1984, -128], [592, 2560, -32]]]},
    "spawns": {"T": [[-832, -704, 176], [-832, -800, 176]], "CT": [[448, 2464, -88], [352, 2464, -88]]},
    "nav": {
      "areas": [
        [1, 0, -1775, -875, 128, -1250, -350, 128, 128, 128, [40, 65]],
        [40, 0, -1250, -875, 128, -1025, -650, 128, 128, 128, [1, 65]]
      ],
      "zones": [
        {"name": "TSpawn", "z": [-60, 320], "polygon": [[-2350, -1060], [560, -1060], [560, -440], [-1240, -440], [-1240, -150], [-2350, -150]]}
      ]
    }
  },
  "match": {
    "max_rounds": 30, "overtime": {"enabled": true, "max_rounds": 6, "start_money": 10000},
    "freeze_time": 3, "buy_time": 15, "round_time": 115, "c4_timer": 35, "start_money": 800
  },
  "config": {
    "tick_hz": 20, "deadline_ms": 200, "fov_deg": 90, "fov_vertical_deg": 74, "vision_delay_ms": 150,
    "sound_dir_noise_deg": 10, "max_turn_rate_dps": 720, "teammates_visible": true, "step_speed": 150,
    "step_radius": 1100, "land_radius": 1100, "reload_radius": 1100, "shot_radius": 2000,
    "silenced_shot_radius": 1000, "bomb_plant_radius": 1100, "bomb_defuse_radius": 1100,
    "grenade_explode_radius": 99999, "sound_near_max": 500, "sound_mid_max": 1500
  }
}
```

#### Map data (`hello.map`)

Everything a player knows about the map before the match, sent once. Boxes are
`[[min x, min y, min z], [max x, max y, max z]]`.

| Field | Type | Meaning |
|---|---|---|
| `name` | string | The map, e.g. `"de_dust2"`. |
| `bombsites` | `{"A": box, "B": box}` | The two bomb sites. |
| `buyzones` | `{"T": [box, ...], "CT": [box, ...]}` | Buy zones of each side. |
| `spawns` | `{"T": [[x, y, z], ...], "CT": [...]}` | Spawn points of each side. |
| `nav` | object | The navigation mesh: `areas` and `zones`, below. |

`nav.areas` is a list of walkable areas, each
`[id, flags, x0, y0, z0, x1, y1, z1, ne_z, sw_z, links]`:

- a rectangle from (x0, y0) to (x1, y1), with x0 ≤ x1 and y0 ≤ y1;
- the floor height at each corner: `z0` at (x0, y0), `z1` at (x1, y1), `ne_z` at (x1, y0),
  `sw_z` at (x0, y1);
- `flags`, bits: 1 crouch here, 2 jump here, 4 precise movement, 8 do not jump;
- `links`: ids of the areas you can move to from this one. Links are one way: an area you can
  drop into but not climb out of is linked only from above.

To walk somewhere, find a path of areas along the links and walk from centre to centre. The
mesh was generated by the game's own bots, so it covers where a player can walk. Values are whole
units.

`nav.zones` names places: `{"name", "z": [lo, hi], "polygon": [[x, y], ...]}`. A position is in a
zone if its (x, y) is inside the polygon and its z is within [lo, hi]; the first zone that
contains a position names it, and some parts of the map have no name. For a player, test `pos`.
de_dust2's zones: `TSpawn`, `CTSpawn`, `ShortA`, `BombsiteA`, `LongA`, `Mid`, `LowerTunnel`,
`UpperTunnel`, `BombsiteB`, `CTMid`. A map without a zone file has no zones.

### ready (bot → arena)

`{"type": "ready"}`. `type` is required; no other fields are allowed.

### round_start (arena → bot)

| Field | Type | Meaning |
|---|---|---|
| `number` | int | Round number, starting at 1. |
| `side` | `"T"` \| `"CT"` | Your side in this round. |
| `score` | object | `own` and `enemy`: rounds won so far. |

### tick (arena → bot)

`{"type": "tick", "obs": {...}}`. Answer with one `action`. An example:

```json
{
  "type": "tick",
  "obs": {
    "tick": 412,
    "time": 61.25,
    "round": {"number": 2, "phase": "live", "time_left": 98.4, "score": {"own": 1, "enemy": 0}, "side": "T", "bomb_planted": false},
    "self": {
      "pos": [-420.5, 1210.0, 36.0], "vel": [0.0, 221.0, 0.0], "yaw": 88.2, "pitch": -1.5,
      "hp": 74, "armor": 92, "helmet": false, "money": 950,
      "alive": true, "on_ground": true, "ducking": false,
      "in_buy_zone": false, "in_bomb_site": null, "has_c4": true, "has_defuser": false,
      "weapons": [
        {"name": "ak47", "slot": 1, "clip": 23, "reserve": 60},
        {"name": "glock18", "slot": 2, "clip": 20, "reserve": 40},
        {"name": "knife", "slot": 3, "clip": null, "reserve": 0},
        {"name": "c4", "slot": 5, "clip": null, "reserve": 1}
      ],
      "active_weapon": "ak47",
      "can_buy": false
    },
    "visible_enemies": [
      {"id": "p2", "pos": [-380.0, 1820.0, 36.0], "head_pos": [-380.0, 1820.0, 53.0], "rel_yaw": -2.0, "rel_pitch": 1.5, "distance": 611.3, "weapon": "m4a1", "ducking": false}
    ],
    "bomb": null,
    "teammates": [],
    "sounds": [{"kind": "shot", "yaw": 85.3, "distance_band": "mid", "age_ms": 0}],
    "events": [{"kind": "damaged_by", "yaw": 86.2}, {"kind": "hit", "id": "p2", "damage": 27}],
    "warnings": ["weapon: you have no awp"]
  }
}
```

The observation:

| Field | Type | Meaning |
|---|---|---|
| `tick` | int | Tick number; echo it in `action.tick`. |
| `time` | float | Game time, seconds. |
| `round` | object | See below. |
| `self` | object | Your player, exact and current. See below. |
| `visible_enemies` | list | Enemies you can see, as they were `vision_delay_ms` ago. |
| `bomb` | object \| null | The dropped or planted bomb when you see it (same rules as enemies): `pos` [x, y, z] and `state` `"dropped"` or `"planted"`. `null` otherwise; a carried bomb is never reported. |
| `teammates` | list | `{id, pos, alive}` of each teammate, current, like the radar, when `config.teammates_visible`. Empty in 1v1. |
| `sounds` | list | Sounds you heard since the previous tick. |
| `events` | list | What happened to you since the previous tick. |
| `warnings` | list of strings | Problems with your previous answer, see [Warnings](#warnings). |

`obs.round`:

| Field | Type | Meaning |
|---|---|---|
| `number` | int | Round number, starting at 1. |
| `phase` | `"freeze"` \| `"live"` \| `"bomb_planted"` \| `"over"` | Freeze time, the round, after the plant, after the round ended (until the next `round_start`). |
| `time_left` | float \| null | Seconds left in this phase; `null` while the bomb is planted (CS 1.6 hides the timer). |
| `score` | object | `own`, `enemy`. |
| `side` | `"T"` \| `"CT"` | Your side in this round. |
| `bomb_planted` | bool | Whether the bomb is planted. Where is not said: look for `obs.bomb`, listen for `bomb_beep`. |

`obs.self`:

| Field | Type | Meaning |
|---|---|---|
| `pos` | [x, y, z] | Your origin, units. |
| `vel` | [x, y, z] | Velocity, units/s. |
| `yaw`, `pitch` | float | Your view, degrees (pitch up positive). |
| `hp`, `armor` | int | 0–100. |
| `helmet` | bool | |
| `money` | int | Dollars. |
| `alive`, `on_ground`, `ducking` | bool | |
| `in_buy_zone` | bool | |
| `in_bomb_site` | `"A"` \| `"B"` \| null | The bomb site whose box in `hello.map.bombsites` holds your origin in x and y, with z at most 36 units below or above the box; else null. |
| `has_c4`, `has_defuser` | bool | |
| `weapons` | list | `{name, slot, clip, reserve}`: `slot` 1 primary, 2 pistol, 3 knife, 4 grenades, 5 bomb; `clip` rounds in the magazine, `null` for the knife, grenades and the bomb; `reserve` spare rounds, or how many grenades of that kind you carry. |
| `active_weapon` | weapon name \| null | |
| `can_buy` | bool | Whether a buy works on this tick, see [Buying](#buying). |

`obs.visible_enemies[]`:

| Field | Type | Meaning |
|---|---|---|
| `id` | string | Player id. |
| `pos` | [x, y, z] | Origin, as it was `vision_delay_ms` ago. |
| `head_pos` | [x, y, z] | Head, as it was `vision_delay_ms` ago. |
| `rel_yaw` | float | Yaw from your **current** eyes to `head_pos`, relative to your **current** view, in (-180, 180]; positive = to your left. Send it as `look.dyaw` to turn towards the head. |
| `rel_pitch` | float | The same for pitch; positive = above your view. |
| `distance` | float | From your current eyes to `head_pos`, units. |
| `weapon` | weapon name \| null | The weapon in their hands. |
| `ducking` | bool | |

Enemy health is never sent.

`obs.sounds[]`:

| Field | Type | Meaning |
|---|---|---|
| `kind` | string | `step`, `jump`, `land`, `shot`, `reload`, `bomb_plant`, `bomb_defuse`, `grenade_explode`, `bomb_beep`. |
| `yaw` | float | World yaw from you to the source in (-180, 180], in steps of 0.1°, with an error of up to `sound_dir_noise_deg`. |
| `distance_band` | `"near"` \| `"mid"` \| `"far"` | Up to `sound_near_max`, up to `sound_mid_max`, beyond. |
| `age_ms` | int | How long ago the sound was made (0 except for bomb beeps, which have their own times). |

`obs.events[]`, each with a `kind`:

| `kind` | Fields | Meaning |
|---|---|---|
| `damaged_by` | `yaw` | You lost health this tick. `yaw` is the world yaw from you to the player who shot you, or, if nobody shot you this tick, to the grenade or bomb explosion that hurt you. Damage with neither (a fall, a knife) gives no event. |
| `hit` | `id`, `damage` | You hit player `id` for `damage` hit points. |
| `killed` | `id` | You killed player `id`. |

### action (bot → arena)

```json
{
  "type": "action",
  "tick": 1234,
  "move": {"forward": 1.0, "side": 0.0},
  "look": {"dyaw": 12.5, "dpitch": -3.0},
  "buttons": ["attack", "duck"],
  "weapon": "ak47",
  "buy": ["ak47", "primammo", "vesthelm"]
}
```

Every field may be omitted; `{}` stands still for one tick.

| Field | Type | Meaning |
|---|---|---|
| `type` | `"action"` | May be omitted. |
| `tick` | int \| null | The tick you are answering. |
| `move.forward` | float in [-1, 1] | Forward (+) or back (-) relative to your view. Default 0. See [Moving](#moving). |
| `move.side` | float in [-1, 1] | Right (+) or left (-). Default 0. |
| `look.dyaw` | float | Turn left (+) or right (-), degrees (at most 36° per tick, so a large turn takes several ticks; see [Turning](#turning)). Default 0. |
| `look.dpitch` | float | Turn up (+) or down (-), degrees, with the same limit. Default 0. |
| `buttons` | list | Buttons held during this tick: `attack`, `attack2`, `jump`, `duck`, `walk`, `reload`, `use`. |
| `weapon` | weapon name \| 1–5 \| null | Switch to a weapon you carry, by name or by slot. |
| `buy` | list | Items to buy, in order, see [Buying](#buying). |

Each action lasts one tick. To keep a button held or keep moving, send it every tick. An empty or
missing action stands still with all buttons released. Each `buy` list is tried once, on the tick
you send it. `look` is applied first; `move` and any shot in the same action use the view after
the turn.

#### How an action is checked

- An unknown name in `buttons`, `buy` or `weapon` (or a weapon slot outside 1–5) is dropped and
  reported in the next `obs.warnings`, e.g. `buy: unknown "АК-47" ignored`; the rest of the action
  still applies. At most 20 such warnings are reported per action, then one `… N more`; a name
  longer than 40 characters is cut.
- Anything else invalid rejects the whole action (status `invalid`), and you stand still for that
  tick: invalid JSON, a value of the wrong type (numbers sent as strings or true/false included),
  `move` outside [-1, 1], NaN or Infinity, an unknown field, a wrong `type`, a line over 64 KiB.
  Unknown fields inside `move` and `look` count too.
- Whole numbers are fine where a float is expected (`"dyaw": 5`), but not the other way round
  (`"tick": 7.0` is rejected).

#### Warnings

`obs.warnings` lists what went wrong with your previous answer, as plain sentences for your log.
The texts may change; do not parse them. Examples:

- `tick 57: no answer within 200 ms`
- `tick 57: action rejected (move.forward: Input should be less than or equal to 1)`
- `buy: unknown "АК-47" ignored`
- `buy: ignored, obs.self.can_buy was false (…)`
- `buy: ak47 failed (money, side or limit)`
- `weapon: you have no awp`, `weapon: nothing in slot 4`

### round_end (arena → bot)

| Field | Type | Meaning |
|---|---|---|
| `number` | int | The round that ended. |
| `winner` | `"T"` \| `"CT"` \| null | `null` for a draw. |
| `reason` | string | `bomb_exploded`, `bomb_defused`, `t_eliminated`, `ct_eliminated`, `time_expired`, `draw`. |
| `score` | object | `own`, `enemy` after this round. |

### match_end (arena → bot)

| Field | Type | Meaning |
|---|---|---|
| `result` | `"win"` \| `"loss"` \| `"draw"` | From your point of view. |
| `score` | object | `own`, `enemy`: final rounds won. |

## 5. What you see and hear

### Vision

- **Field of view** is what is on your screen: a 4:3 view `fov_deg` wide and `fov_vertical_deg`
  high (90° × 74°). A point is inside it if it is in front of you and, measured along your view's
  axes, its sideways offset is at most tan(`fov_deg` / 2) times its depth and its vertical offset
  at most tan(`fov_vertical_deg` / 2) times its depth.
- **Line of sight:** the game server traces from your eyes to four points of each enemy (head,
  chest, pelvis, feet) and to the bomb. Walls and solid brushes block a trace; players do not.
  The head point is the enemy's eyes (origin + 17 standing, + 12 ducked), the chest is halfway
  between eyes and origin, the pelvis is the origin, the feet are 2 units above the bottom of the
  box. `head_pos` is the head point.
- An enemy is **visible** if at least one point is inside the field of view and its trace is open.
  The dropped or planted bomb is seen by the same rule for its position and reported in
  `obs.bomb`; a carried bomb is not.
- **Vision delay:** the picture is the newest snapshot at least `vision_delay_ms` old (rounded up
  to whole ticks). For the first ticks of a round, before such a snapshot exists, you see no
  enemies. An enemy killed in the last 150 ms is still reported. Whether you see an enemy is
  decided on the world as it was then, with your own position and view as they were then; the
  enemy's position, weapon and pose are also from then. Only `rel_yaw`, `rel_pitch` and
  `distance` are measured from your current eyes and view. So after a fast turn, enemies in the
  new direction appear 150 ms later, and an enemy who just left your view is still reported for
  150 ms.
- Smoke and flashbangs do not affect what you are sent yet.

### Hearing

Sounds are heard through walls, within each sound's radius (straight-line distance from your
origin to the source). Each heard sound gets a direction error drawn uniformly from
[-`sound_dir_noise_deg`, +`sound_dir_noise_deg`] by a random generator seeded with the match
seed, the tick and your id (so it does not depend on other players), and only a rough distance
band. Sounds are not delayed: they are from the current tick (`age_ms` is 0, except for bomb
beeps). `sounds[].yaw` is a world yaw in (-180, 180].

You do not hear your own steps, jumps, landings, shots, reloads, plants or defuses. You hear every
grenade explosion and every bomb beep within its radius, your own included, and your teammates'
sounds; a sound does not say who made it.

| Kind | Made when | Radius (units) |
|---|---|---|
| `step` | Every 0.3 s of game time (on a clock shared by all players) while a player is on the ground and moving faster than `step_speed` (150 units/s). Only the speed counts: walking and ducking are always slower, so they are silent, as in CS 1.6. | `step_radius` 1100 |
| `jump` | A player jumps while moving at `step_speed` or faster. A standing jump is silent. | `step_radius` 1100 |
| `land` | A player lands after falling faster than 290 units/s (CS 1.6's threshold, about 53 units of drop), measured on the last tick in the air. Stairs and small drops are silent. | `land_radius` 1100 |
| `shot` | A player's magazine went down with the same weapon in hand (one sound per tick). | `shot_radius` 2000; `silenced_shot_radius` 1000 for the M4A1 or USP with a silencer and for the TMP |
| `reload` | A player starts reloading. | `reload_radius` 1100 |
| `bomb_plant` | A player starts planting. | `bomb_plant_radius` 1100 |
| `bomb_defuse` | A player starts defusing. | `bomb_defuse_radius` 1100 |
| `grenade_explode` | Any grenade detonates (HE, flash or smoke). | `grenade_explode_radius` 99999 (whole map) |
| `bomb_beep` | The planted bomb beeps: 0.5 s after the plant, then every 1.4 s until it explodes. | Grows in five stages: 667, 1000, 1250, 2000, 5000 |

The beep starts at radius 667 at the plant and gets louder four times: after ⌊c4_timer / 4⌋ s,
then after intervals each 0.9 times the one before (35 s timer: 1000 at +8 s, 1250 at +15.2 s,
2000 at +21.7 s, 5000 at +27.5 s). The bomb timer is `hello.match.c4_timer`. The arena reports
each beep you can hear, not the stage.

Radii follow ReGameDLL's bot hearing; plant and defuse radii and the distance bands are the
arena's own.

### Turning

`look.dyaw` and `look.dpitch` are each clamped to `max_turn_rate_dps / tick_hz` degrees per tick
(720 / 20 = 36°): a request to turn 180° turns 36°. Pitch stays within ±89°.

## 6. Settings

### Match settings (`hello.match`)

| Field | Default | Meaning |
|---|---|---|
| `max_rounds` | 30 | Rounds in regulation time. Sides switch after `max_rounds // 2` rounds (at least 1). The first team to win `max_rounds // 2 + 1` rounds wins the match; otherwise it ends after `max_rounds` rounds, and a tie is a draw. |
| `overtime` | | `enabled`, `max_rounds`, `start_money`: sent as configured, but overtime is not played yet; a tie is a draw. |
| `freeze_time` | 3 | Freeze time at the start of each round, seconds. |
| `buy_time` | 15 | Buy time, seconds, counted from the end of freeze time: you can buy during freeze and for `buy_time` s after it. |
| `round_time` | 115 | Round time, seconds. |
| `c4_timer` | 35 | Seconds from the plant to the explosion. |
| `start_money` | 800 | Money at the start of the match and of the second half, dollars. |

### Arena rules (`hello.config`)

| Field | Default | Meaning |
|---|---|---|
| `tick_hz` | 20 | Observations per second of game time (one tick = 50 ms). |
| `deadline_ms` | 200 | Wall-clock time to answer a tick. |
| `fov_deg` | 90 | Horizontal field of view, degrees. |
| `fov_vertical_deg` | 74 | Vertical field of view, degrees (90 horizontal on a 4:3 screen is about 74 vertical). |
| `vision_delay_ms` | 150 | Age of everything you see. |
| `sound_dir_noise_deg` | 10 | Maximum direction error of a sound, degrees. |
| `max_turn_rate_dps` | 720 | Turn limit, degrees per second, per axis. |
| `teammates_visible` | true | Teammates' positions are sent in `obs.teammates`. |
| `step_speed` | 150 | Footsteps only above this speed, units/s; jumps at this speed or faster. |
| `step_radius` | 1100 | Hearing radius of a footstep or a jump. |
| `land_radius` | 1100 | Hearing radius of a landing. |
| `reload_radius` | 1100 | Hearing radius of a reload. |
| `shot_radius` | 2000 | Hearing radius of an unsilenced shot. |
| `silenced_shot_radius` | 1000 | Hearing radius of a silenced shot (M4A1/USP with silencer, TMP). |
| `bomb_plant_radius` | 1100 | Hearing radius of the start of a plant. |
| `bomb_defuse_radius` | 1100 | Hearing radius of the start of a defuse. |
| `grenade_explode_radius` | 99999 | Hearing radius of a grenade detonation. |
| `sound_near_max` | 500 | Sounds up to this distance are `near`. |
| `sound_mid_max` | 1500 | Sounds up to this distance are `mid`; farther ones are `far`. |

The game itself is normal CS 1.6: physics, recoil, economy and the bomb.

## 7. Names and game mechanics

Weapon names are the game's weapon entity names without the `weapon_` prefix, not buy-menu
aliases: `glock18` (not `glock`), `mp5navy` (not `mp5`), `elite`, `fiveseven`, `hegrenade`,
`flashbang`, `smokegrenade`.

| Slot | Weapons |
|---|---|
| 1 | `m3`, `xm1014`, `mac10`, `tmp`, `mp5navy`, `ump45`, `p90`, `galil`, `famas`, `ak47`, `m4a1`, `sg552`, `aug`, `scout`, `awp`, `sg550`, `g3sg1`, `m249` |
| 2 | `glock18`, `usp`, `p228`, `deagle`, `elite`, `fiveseven` |
| 3 | `knife` |
| 4 | `hegrenade`, `flashbang`, `smokegrenade` |
| 5 | `c4` |

Buy items: every weapon above except `knife` and `c4`, plus `vest`, `vesthelm` (vest and
helmet), `defuser`, `nvgs`, `shield`, `primammo` (primary ammo), `secammo` (pistol ammo). Which
side may buy what is the game's normal rule (for example `ak47` for T, `m4a1` for CT).

Buttons: `attack`, `attack2` (secondary fire, scope, silencer), `jump`, `duck`, `walk` (quiet
movement), `reload`, `use` (defuse, doors).

### Buying

- Buy only on a tick where `obs.self.can_buy` is true: in your side's buy zone during buy time.
  It is also false for the first ticks after you spawn, while you are still falling to the
  floor. A `buy` sent while it is false is ignored with a warning; send it again later.
- Items are bought in the order you list them, while the money lasts. A buy the game refuses (not
  enough money, the other side's weapon, already full) gives the warning
  `buy: ak47 failed (money, side or limit)`. A failed `primammo` or `secammo` gives no warning.
- Prices are CS 1.6's, e.g. glock18 400, usp 500, deagle 650, mp5navy 1500, galil 2000, famas
  2250, ak47 2500, m4a1 3100, awp 4750, hegrenade 300, flashbang 200, vest 650, vesthelm 1000,
  defuser 200.
- **A gun you buy comes with a full magazine and none of its own spare rounds.** Buy ammo for it
  with `primammo` (primary) or `secammo` (pistol), listed after the gun. `weapons[].reserve` is
  your stock of that gun's ammo type, shared by guns of the same calibre (for example `glock18`
  and `mp5navy`), so it can be above 0 right after a buy.
- At most 8 commands run per tick: the `buy` items plus one for a `weapon` switch. The rest of
  the list is ignored with a warning.
- Money follows the game's rules: `start_money` at the start of the match and of the second half,
  then rewards for kills and for winning or losing rounds. You keep what you survive with; after a
  death you start the next round with the knife and the default pistol (`glock18` for T, `usp`
  for CT).

### Moving

- `move` is a direction relative to your view and a fraction of full speed. The arena asks the
  game for 400 × L units/s, where L is the length of (`forward`, `side`), at most 1. The game
  caps it at the active weapon's top speed (250 units/s with the knife or a pistol, less with
  most rifles). `forward: 1, side: 1` runs diagonally at full speed, not faster.
- With `walk` held the request is 130 × L units/s, below `step_speed`, so you make no footsteps.
  While ducked (`duck`) you move at a third of your standing speed (83 units/s with the knife or
  a pistol), so that is silent too.
- During `freeze` you cannot move, but you can turn and buy.
- Moving and jumping make your shots less accurate, as in CS 1.6.

### Fighting and the bomb

- Pistols fire once per press: release `attack` for a tick between shots. Automatic weapons fire
  while `attack` is held; short bursts keep the recoil down.
- `reload` starts a reload.
- Grenades: hold `attack`, then release to throw.
- To plant: stand on the ground inside a bomb site (`in_bomb_site` is not null) with `c4` in hand
  and hold `attack` for 3 s. Letting go cancels the plant.
- To defuse: look at the bomb from close by and hold `use` for 10 s (5 s with a defuser).

## 8. Python SDK (`arena_sdk`)

The SDK runs the protocol for you and adds map and aiming helpers. A bot that the arena starts
with `python` already has it. To use it elsewhere (Python 3.12 or newer), install it from the
repository root: `pip install ./arena_sdk` or `uv pip install ./arena_sdk`. It needs only
`pydantic`.

A small but complete bot: it walks to bomb site A and shoots any enemy it sees.

```python
from arena_sdk import Action, Bot, Look, PathFollower, angle_to, move_towards, run


class MyBot(Bot):
    def on_round_start(self, msg):
        self.route = PathFollower(self.map, self.map.bombsite_center("A"))

    def on_tick(self, obs):
        me = obs.self
        if not me.alive:
            return None  # dead: the action is ignored, but every tick needs an answer
        if obs.visible_enemies:
            enemy = min(obs.visible_enemies, key=lambda e: e.distance)
            limit = self.turn_limit  # degrees the arena turns us this tick, at most
            aimed = abs(enemy.rel_yaw) <= limit and abs(enemy.rel_pitch) <= limit
            fire = aimed and obs.tick % 2 == 0  # pistols need a released tick between shots
            look = Look(dyaw=enemy.rel_yaw, dpitch=enemy.rel_pitch)
            return Action(look=look, buttons=["attack"] if fire else [])
        point = self.route.next_point(me.pos)
        if point is None:
            return None  # arrived
        dyaw, _ = angle_to(me, point)
        # The arena turns first and then moves: aim the move with the view after the turn.
        turned = me.yaw + max(-self.turn_limit, min(self.turn_limit, dyaw))
        move = move_towards(me, point, yaw=turned)
        return Action(look=Look(dyaw=dyaw, dpitch=-me.pitch), move=move)  # and level the view


if __name__ == "__main__":
    run(MyBot())
```

### Bot and run

Subclass `Bot`, override the handlers you need, and call `run(MyBot())`. `run` reads the arena's
messages until stdin closes:

- `hello`: sets `self.hello` (the `Hello` message) and `self.map` (a `GameMap`), calls
  `on_hello(hello)`, then sends `ready`, even if `on_hello` raises. If the `hello` is JSON but
  does not fit the SDK's models, `ready` is still sent, `on_hello` is not called, and `self.hello`
  and `self.map` stay None (`self.turn_limit` then uses the default rules). A line that is not
  JSON gets no answer.
- `round_start`, `round_end`, `match_end`: call `on_round_start(msg)`, `on_round_end(msg)`,
  `on_match_end(msg)`.
- `tick`: sets `self.tick`, calls `on_tick(obs)` and sends what it returns with `tick` filled in:
  an `Action`, a dict shaped like the action JSON, or None to stand still.
- An exception in a handler is logged to stderr with its traceback (an error that repeats at the
  same place is logged with its traceback once, then as at most one `same error again (N)` line
  per second), and a tick still gets an empty action: a bug costs a tick, not the match.
- Before sending, the SDK checks the action the way the arena does and logs what the arena will
  warn about or reject. It sends the action as given, so the arena reports it too
  (`obs.warnings`, status `invalid`). Building `Action(...)` with an unknown name raises in your
  code (logged; the tick gets an empty action); return a dict instead to have unknown names
  dropped and reported by the arena.
- Inside `run`, `print()` writes to stderr, so a stray print cannot break the protocol. Use
  `self.log(...)` for one log line with the tick number.
- `self.turn_limit` is the most the arena turns you per tick, degrees per axis
  (`max_turn_rate_dps / tick_hz`, 36 by default).

The message classes (`Hello`, `RoundStart`, `Observation`, `Action`, `Move`, `Look`, `RoundEnd`,
`MatchEnd`, ...) are pydantic models in `arena_sdk.protocol`, with the field names of this page:
`obs.self.pos`, `obs.visible_enemies[0].rel_yaw`, `self.hello.config.deadline_ms`.

### The map: `self.map`

A `GameMap` holds `hello.map` with the nav mesh ready to use:

- `name`, `bombsites` (`{"A": (min, max), "B": (min, max)}`), `buyzones`, `spawns`, as in
  `hello.map`.
- `bombsite_center(letter)`: the centre of a bomb site's box, `(x, y, z)`.
- `place_of(pos)`: the zone name at a position (`"LongA"`), or None.
- `path(from_pos, to_pos)`: the areas to walk through, from the area nearest `from_pos` to the
  area nearest `to_pos` (A* over the area centres along the links), or None if there is no way
  there.
- `area_at(pos)`: the area under a position (the highest one at most 5 units above and 120 below
  it, so a player's `pos` works), or None. `nearest_area(pos)` falls back to the closest area.
- Each area has `id`, `flags`, `links`, `lo` and `hi` (its two corners with their height),
  `center`, `z_at(x, y)` (floor height) and `closest_point(pos)`.

### Aiming and walking

- `angle_to(me, pos)`: the `(dyaw, dpitch)` that turn your view onto `pos`, seen from your eyes.
  Send them as `look`; the arena turns at most `turn_limit` per tick, so a big turn takes several
  ticks. `me` is `obs.self`.
- `move_towards(me, pos, yaw=None)`: the `Move` that walks towards `pos` at full speed whichever
  way you look. If you also turn this tick, pass the yaw you will have after the turn
  (`me.yaw + dyaw`, with dyaw clamped to `turn_limit`), or you walk up to 36° off course.
- `PathFollower(nav, goal, reach=40, off_path=150)`: walks `nav.path` to `goal`. Call
  `next_point(me.pos)` every tick and move towards the point it returns; it returns None at the
  goal or when there is no path. It plans again from where you are when you are more than
  `off_path` units from the leg you should be walking, for example after a fight. Once it has
  returned None it stays None, even if you are pushed away; make a new `PathFollower` to walk
  again. A waypoint more than 18 units above your feet (a ledge) counts as reached only once you
  are up there; jump, and duck while in the air, to climb onto it.
- `wrap180(deg)`: the same angle in (-180, 180]. `eye(me)`: where your eyes are.

### The Reference bot

`bots/reference/bot.py` is the worked example. Every round it buys by its money (armor on pistol
rounds, a rifle and armor when it can afford them). The T walks to bomb site A, plants, and leaves
for its spawn 12 s before the bomb goes off; the CT holds the way into site B and, once the bomb is
planted, defuses it, looking for a bomb it has not seen at the site the beeps come from. Both fight
with the turn limit and trigger discipline in mind, turn towards sounds and hits, jump onto the
nav mesh's jump areas and reload when safe. It is meant to show the API, not to be strong. Read it
before you write your own.

## 9. Other languages

- `schema/protocol.v1.json` (JSON Schema 2020-12) describes every message. Its root is a union of
  all messages told apart by `type`; generate types for your language from it. An empty action `{}` is valid; the schema's
  union matches it to `action`.
- `bots/examples/ts-minimal/` is a TypeScript bot with no packages: `node bot.ts` (Node 24 or
  newer runs TypeScript directly). It runs at the nearest enemy it sees, else towards the enemy
  spawn, and shoots when aimed.
  `protocol.ts` holds hand-written types for the fields it uses.
- A minimal bot needs nothing but JSON. In Python with only the standard library:

```python
import json
import sys

for line in sys.stdin:
    msg = json.loads(line)
    if msg["type"] == "hello":
        print(json.dumps({"type": "ready"}), flush=True)
    elif msg["type"] == "tick":
        obs = msg["obs"]
        action = {"tick": obs["tick"], "move": {"forward": 1.0}}
        if obs["visible_enemies"]:
            enemy = obs["visible_enemies"][0]
            action["look"] = {"dyaw": enemy["rel_yaw"], "dpitch": enemy["rel_pitch"]}
            # Pistols fire once per press: fire on alternate ticks.
            action["buttons"] = ["attack"] if obs["tick"] % 2 else []
        elif obs["sounds"]:
            dyaw = (obs["sounds"][-1]["yaw"] - obs["self"]["yaw"] + 180) % 360 - 180
            action["look"] = {"dyaw": dyaw}
        print(json.dumps(action), flush=True)
```

## 10. Trying a bot

On the platform, every upload first plays a check match ([The check match](#the-check-match)).
Once it is Ready, **New match** plays it against the Reference bot or any other Ready bot. A
match's page shows the 2D replay; click a player there to see what its bot was sent and what it
answered on each tick.

## 11. Uploading to the platform

On the platform (a web site) people upload bots and play them against each other. You upload
your bot as a zip on the **My bot** page. Uploading needs an admin's approval of your account.
Every upload is a new version of your one bot.

### The zip

- `bot.yaml` sits at the top of the zip, or the whole zip is one folder with `bot.yaml` in it
  (that folder is then left out, so a zip of your bot's folder works). Entries under `__MACOSX/`
  are ignored.
- `bot.yaml`:

  ```yaml
  cmd: [python, bot.py]   # required; run in the folder of bot.yaml
  title: My bot           # optional, as are description and language
  ```

  The first word of `cmd` picks the runtime: `python` or `python3` for Python, `node` for Node.
  `title`, `description` and `language` are accepted but not shown; your bot's name is set on
  My bot (at first it is your name). Any other key is refused.
- The upload is refused, with a sentence that says why, when:
  - the zip is over 10 MB, over 50 MB unpacked, or has more than 2000 entries, or is not a zip;
  - `bot.yaml` is missing (not at the top, and not in the one top folder), over 64 KB, not YAML,
    has no `cmd` or an unknown key, or `cmd` starts with another program;
  - an entry is a link or a device, a path is absolute or has `.`, `..`, an empty folder name,
    `:` or `\`, two files differ only in the case of their names, or a file has the name of a
    folder.
- At most 20 uploads per person in any 24 hours.

### Runtimes

`cmd` runs exactly as written, in a Docker container, in `/bot` (your zip, unpacked):

| `cmd` starts with | What is installed |
|---|---|
| `python`, `python3` | Python 3.12.16, `arena_sdk` (section 8), `pydantic` 2.14.4, `numpy` 2.5.4 |
| `node` | Node 24.22.3, no packages; it runs `.ts` files directly by stripping the types, so only erasable TypeScript works (no `enum`, no `namespace`, no parameter properties) and imports name the `.ts` file (`from "./protocol.ts"`) |

Nothing else can be installed: the zip is all you bring, and bots have no network. Your own
modules in the zip work as usual.

### Limits

Each start of your bot is a new container with:

- 512 MiB of memory, no swap. A bot that needs more is killed (exit code 137) and counted as a
  crash.
- 1 CPU.
- At most 128 processes (threads count too).
- No network.
- Everything read-only, `/bot` included, except `/tmp`: 64 MiB, empty at every start.
- User 65534 (nobody), no capabilities.

The protocol, the deadlines and the 10 s for `ready` are the same as in section 1.

### Your log

stderr is your log. Per match, the first 10 MiB of it are kept, then a line
`[arena] log truncated at 10 MiB`; the rest is dropped. After the match the platform gets the
last 2 MB of it. Only you and the admins can read your logs (the **Log** link of a version on My
bot, and the bot log links on a match's page) and your zips. Replays are open to everyone signed
in.

### The check match

Every new version first plays a check match: a 1v1 on de_dust2 over 2 rounds, your version as
T against the latest Reference bot (`bots/reference/bot.py`) as CT, sides switched after round
1, not in real time. Its status is **Checking** until the match ends. It becomes **Ready** if
the match completed and your bot:

- answered its first `hello` with `ready` in time;
- never crashed, never had the status `error` and never sent an `invalid` answer (warnings are
  fine);
- timed out on fewer than 10 % of the match's ticks.

Otherwise it is **Broken**, with a note naming the first rule it failed (`no ready (...)`,
`crashes 1`, `invalid 3`, `timeouts 600 of 5000 ticks`, ...) or why the match did not complete.
Only Ready versions can play; fix the bot and upload again. The check's replay and your log are
linked from the version on My bot.

### Versions

- Versions are numbered v1, v2, ... and never change; a match plays the versions it was launched
  with.
- **Version for tournaments** on My bot: a Ready version you choose, else your latest Ready one.
  When an admin creates a tournament, each participant's version is fixed for the whole
  tournament; later uploads do not change it.

## 12. Open points

- Whether the bomb's beep stage (how close it is to exploding) should be reported.
- Smoke, flashbangs and overtime are not modelled yet.
