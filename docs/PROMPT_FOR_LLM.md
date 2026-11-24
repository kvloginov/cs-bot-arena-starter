# Prompt for an LLM that writes a bot

Paste everything below the line into a chat with an LLM, then the full text of `docs/BOT_API.md`.
Attaching `bots/reference/bot.py` as well helps. To ask for another language, change the
"Language" paragraph.

---

You are writing a bot for the CS 1.6 Bot Arena. The arena runs real Counter-Strike 1.6 matches
between programs. Each program controls one player, sees only what a player would see and hear,
and acts through a small set of commands. The BOT_API.md text below is the complete interface.
Follow it exactly and do not assume anything it does not say.

## The task

Write a bot that plays one player in a 1v1 match on de_dust2 and wins as many rounds as it can.
As T it wins by planting the bomb and letting it explode, or by killing the enemy. As CT it wins
by killing the enemy, defusing the bomb, or running out the round time.

Language: Python 3.12 with the SDK (`arena_sdk`, BOT_API.md section 8), in one file `bot.py`
that ends with `run(MyBot())`. Use only the standard library, `pydantic` and `arena_sdk`.
(In another language: only its standard library, speaking the JSON protocol directly, BOT_API.md
section 9; say how to start it.)

## Hard rules

1. Answer `hello` with `ready` and every tick with exactly one action that carries `obs.tick`.
   The SDK's `run` does this for you; return None from `on_tick` to stand still.
2. stdout carries only protocol lines. Log to stderr (`self.log(...)` in the SDK).
3. Answer each tick within `deadline_ms` (200 ms of wall-clock time). Aim for under 20 ms: do
   set-up work in `on_hello` or `on_round_start`, plan paths once (the SDK's `PathFollower` plans
   only when needed), and never wait on anything.
4. Do not crash. A crash costs the rest of the round. Expect empty lists, `obs.bomb` null,
   `self.hello` and `self.map` None, and being dead (you still get ticks).
5. An action lasts one tick. To keep moving or keep a button held, send it every tick.
6. Use only the names listed in BOT_API.md: weapon entity names such as `glock18` and
   `mp5navy`, not buy-menu aliases.
7. The bot needs no files and no network; everything it may know comes in the messages.

## What makes the game hard

- You turn at most 36° per tick on each axis (`self.turn_limit`), so aiming takes several ticks.
  Fire only when the turn you still need fits in one tick.
- What you see is 150 ms old. Enemies are where they were then.
- `look` is applied before `move`. When you turn and walk in the same tick, compute the move with
  the yaw after the turn (`move_towards(me, point, yaw=turned)`).
- Pistols fire once per press: send `attack` on every other tick. Rifles are accurate in short
  bursts while standing still; running spoils your aim.
- Running faster than 150 units/s makes footsteps the enemy hears; `walk` and `duck` are silent.
- A gun you buy has no spare ammo: buy `primammo` (or `secammo` for a pistol) after it. A buy works
  only on a tick where `obs.self.can_buy` is true.
- Sounds give only a noisy direction (±10°) and a rough distance band.

## What a good first bot does

Build it in this order and keep each part simple and readable:

1. Answers every tick; returns None while dead.
2. Buys once per round, on the first tick where `can_buy` is true: armor on pistol rounds (1 and
   the first round of the second half); a rifle with ammo and armor when the money allows; saves
   otherwise.
3. Walks a nav path (`PathFollower`) to a bomb site, looking where it goes and keeping the view
   level.
4. When an enemy is visible: stops, aims (`rel_yaw`/`rel_pitch` or `angle_to`), switches to its
   best gun, and fires with trigger discipline once aimed.
5. As T: in the bomb site with the bomb, switches to `c4`, stands still and holds `attack` until
   the plant is done (3 s), then guards the bomb.
6. As CT: holds a bomb site, watching the way enemies come in. Once it has seen the planted bomb,
   walks to it, looks at it and holds `use`.
7. Turns towards sounds and towards `damaged_by` events for a second or two.
8. Reloads when the magazine is empty and nobody is in sight.

`bots/reference/bot.py` does all of this. Borrow ideas from it, but write your own bot and try to
beat it.

## Uploading to the platform

The platform takes the bot as a zip: the bot's files plus a `bot.yaml` at the top of the zip (or
in its one top folder) holding `cmd: [python, bot.py]`. It runs only Python (3.12.16 with
`arena_sdk`, `pydantic` and `numpy`) and Node (24.22.3,
`cmd: [node, bot.ts]`, types stripped: no `enum` or `namespace`, imports end in `.ts`; no
packages); nothing else can be installed.
Each bot gets 512 MiB of memory, 1 CPU, no network, and a read-only disk except `/tmp` (64 MiB).
A new upload first plays a 2-round check match against the Reference bot and may play only if it
answered `ready` in time, never crashed, never sent an invalid action and timed out on fewer than 10 % of
the ticks.

## What to return

1. The complete `bot.py`, ready to save as `bots/my_bot/bot.py` (for another language: every file
   and the `cmd` that starts it), and its `bot.yaml` for the platform.
2. A few lines on the strategy, and every assumption you made about the API that BOT_API.md does
   not state.

No pseudo-code and no parts left out.
