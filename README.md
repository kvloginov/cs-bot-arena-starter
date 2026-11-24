# CS 1.6 Bot Arena: starter kit

The CS 1.6 Bot Arena plays real Counter-Strike 1.6 matches between programs. Each player is
driven by a bot: a program that sees only what a player would see and hear, and answers every
tick with what to do (move, turn, shoot, buy). You write a bot and upload it to the platform at
<https://cs-bot-arena.fly.dev>. There it plays practice matches and tournaments against other
people's bots, and every match can be replayed in the browser.

This kit is everything you need to write one:

| Path | What it is |
|---|---|
| [docs/BOT_API.md](docs/BOT_API.md) | The whole bot interface: messages, what a bot sees and hears, the SDK, uploading. |
| [bots/reference/](bots/reference/) | The Reference bot, in Python. This page walks through it. |
| [bots/examples/ts-minimal/](bots/examples/ts-minimal/) | A small bot in TypeScript, without the SDK. |
| [arena_sdk/](arena_sdk/) | The Python SDK. The platform has it installed for Python bots. |
| [schema/protocol.v1.json](schema/protocol.v1.json) | A JSON Schema of every message, to generate types in other languages. |
| [docs/PROMPT_FOR_LLM.md](docs/PROMPT_FOR_LLM.md) | A prompt that has an LLM write a bot. |

## Getting in

1. Open <https://cs-bot-arena.fly.dev> and sign in with your Google account.
2. You can watch every match right away. To upload a bot or launch matches, an admin has to
   approve your account. Until then the site says "Waiting for approval"; it updates by itself
   once you are approved.

## How a bot works

- The platform starts your bot as a process of its own, with the command in its `bot.yaml`.
- The arena sends one JSON message per line on the bot's stdin, and the bot answers one per line
  on stdout. First comes `hello` (the map, the match settings, the rules); the bot answers
  `ready`. Then comes a `tick` 20 times per second of game time; the bot answers each with one
  `action`, within 200 ms. See [BOT_API, section 1](docs/BOT_API.md#1-how-a-bot-runs) and
  [section 2](docs/BOT_API.md#2-message-sequence).
- stderr is the bot's log. You can read it after each match.
- A Python bot can use the SDK, `arena_sdk`. It speaks the protocol for you and has helpers for
  the map, aiming and walking ([section 8](docs/BOT_API.md#8-python-sdk-arena_sdk)).

## Your first bot: the Reference bot

[`bots/reference/`](bots/reference/) holds two files:

- `bot.py`: the bot, Python on the SDK.
- `bot.yaml`: its manifest. `cmd: [python, bot.py]` tells the platform how to start it.

The platform's Reference bot, the opponent in every check match, is this bot. It is a worked
example of the API, not a strong player. You can upload it unchanged first, to see the whole
flow once, and change it after that.

Open `bot.py` next to this page. The steps below follow it.

### 1. The skeleton

`ReferenceBot` subclasses the SDK's `Bot`, and the last line of the file is
`run(ReferenceBot())`. `run` reads the arena's messages and calls the bot's handlers:

- On `hello` it sets `self.hello` (the whole message) and `self.map` (the map with its nav mesh),
  then sends `ready`.
- On `round_start` it calls `on_round_start(msg)`.
- On each `tick` it calls `on_tick(obs)` and sends what that returns as the action. `None` means
  stand still.
- If a handler raises, the error goes to the log and that tick gets an empty action. A bug costs
  a tick, not the match.

See [Bot and run](docs/BOT_API.md#bot-and-run).

The constants at the top of the file are the bot's choices, each with a comment: the bomb site of
each side (`SITE`: T to A, CT to B), prices, how much money a rifle needs, trigger patterns,
timings.

### 2. A new round: `on_round_start`

`msg.side` is the bot's side in this round; the sides switch at half time. The bot picks its bomb
site and calls `go()`, which makes a `PathFollower` to the centre of that site
(`self.map.bombsite_center(...)`). Then it forgets the last round: whether it has bought, where it
saw the bomb, where it was looking. See [round_start](docs/BOT_API.md#round_start-arena--bot) and
[The map](docs/BOT_API.md#the-map-selfmap).

### 3. Every tick: `on_tick`

`obs` is what the bot knows on this tick ([tick](docs/BOT_API.md#tick-arena--bot)):

- `obs.self` is its own player, exact and current: position, view, health, money, weapons.
- `obs.visible_enemies` are the enemies in its view, as they were 150 ms ago.
- `obs.sounds` and `obs.events` are what it heard, and what happened to it, since the last tick.

While the bot is dead, `on_tick` returns `None`: the arena still sends ticks and needs an answer
to each. Otherwise it updates what it knows (steps 4 and 5) and takes the nearest visible enemy.
Then the first rule that applies decides the tick:

1. **Plant:** a T with the bomb, inside a bomb site, with no enemy in sight.
2. **Defuse:** a CT within 40 units of a planted bomb it has seen, with no enemy in sight.
3. **Fight:** an enemy is in sight.
4. **Walk or hold:** everything else.

A plant or defuse that has started goes on even when an enemy shows up, because letting go of
the button starts it over. Only a hit (a `damaged_by` event) stops it. With only the knife left,
an enemy farther than 48 units is not a fight.

Last, the shopping list (step 9) is added to every action.

### 4. What it notices: `notice`

- **The bomb.** `obs.bomb` is the dropped or planted bomb, when the bot can see it. The first time
  it sees the bomb planted, it remembers where. A CT then walks there.
- **Sounds.** Sounds are heard through walls, with a direction off by up to 10° and only a rough
  distance (`near`, `mid` or `far`). The bot looks towards the nearest sound for 1.5 s. It skips
  bomb beeps, unless it is a CT still looking for the bomb and the beep is `near`.
- **Hits.** A `damaged_by` event gives the direction of whoever hit the bot. That beats any sound.

See [Hearing](docs/BOT_API.md#hearing) and the `sounds` and `events` tables under
[tick](docs/BOT_API.md#tick-arena--bot).

### 5. Where to go next: `next_goal`

- **The T after its plant.** The plant is done when the bomb has left the T's hands and the round
  says the bomb is planted. The bomb goes off `hello.match.c4_timer` seconds later (35 by
  default). 12 s before that, the T walks back towards its spawn, out of the blast.
- **The CT and a bomb it has not seen.** `obs.round.bomb_planted` says that the bomb is planted,
  not where. Until the CT hears a beep, it goes to the nearest bomb site it has not looked at yet.
  A `bomb_beep` sound gives a direction and a distance band: the bot guesses a point that far that
  way and goes to the bomb site nearest the guess.

See [Match settings](docs/BOT_API.md#match-settings-hellomatch) and
[Hearing](docs/BOT_API.md#hearing).

### 6. Walking: `walk_or_hold`

- **The route.** Every tick, `self.route.next_point(me.pos)` gives the next point of the nav path.
  The `PathFollower` plans again when the bot gets pushed off its way, for example in a fight. See
  [Aiming and walking](docs/BOT_API.md#aiming-and-walking).
- **Looking and moving.** The bot looks where it goes and keeps its view level. While it looks
  towards a sound, it keeps walking its route. The arena turns the view first and moves after,
  and it turns at most 36° per tick. So the bot works out the view it will have after this tick's
  turn and passes it to `move_towards`; otherwise it would walk off course while turning. See
  [action](docs/BOT_API.md#action-bot--arena), [Turning](docs/BOT_API.md#turning) and
  [Moving](docs/BOT_API.md#moving).
- **Jumps.** Nav areas with flag 2 take a jump to get onto (a ledge). When the next point is
  within 60 units and in such an area, the bot jumps, and ducks in the air to lift its feet. See
  [Map data](docs/BOT_API.md#map-data-hellomap).
- **Stuck.** When it has not got 50 units further in 10 ticks of walking, it jumps, and again
  every 10 ticks. After 60 ticks it gives up the route and holds where it is.
- **Arrived.** At the end of the route the bot holds. It watches the way the enemies come in: the
  first point of the nav path to the enemy spawn that lies outside its bomb site.
- **Reload.** With an empty magazine and spare rounds, it reloads. This rule runs only when no
  enemy is in sight, so it is a safe moment.
- **Gun.** It keeps its best gun in hand: the rifle if that has ammo, else the pistol, else the
  knife.

### 7. Fighting: `fight`

- The bot stands still: moving spoils the aim, as in CS 1.6.
- It aims halfway between the enemy's origin and head, a bigger target than the head.
  `angle_to` gives the turn from its eyes to that point. What it sees is 150 ms old, so it aims
  where the enemy was then. See [Vision](docs/BOT_API.md#vision).
- It fires only when the whole turn fits into this tick (`self.turn_limit`, 36°). The arena turns
  before it shoots, so the sight is on the target when the trigger is pulled.
- A pistol fires once per press, so the bot presses and releases on alternate ticks. A rifle
  fires bursts: 3 ticks on, 2 off, so the recoil settles in between.
- It does not fire on a tick where it switches guns: a gun being drawn cannot fire yet.

See [Fighting and the bomb](docs/BOT_API.md#fighting-and-the-bomb).

### 8. The bomb: `plant` and `defuse`

- **Plant.** `obs.self.in_bomb_site` says the bot stands in a site. It switches to the `c4`, then
  holds `attack` for the 3 s the plant takes. An action lasts one tick, so a held button is sent
  again on every tick.
- **Defuse.** Next to the bomb, the CT looks at it and holds `use`: 10 s, or 5 s with a defuse
  kit.

See [Fighting and the bomb](docs/BOT_API.md#fighting-and-the-bomb).

### 9. Buying: `shopping_list`

The bot buys once per round, on the first tick where `obs.self.can_buy` is true. It sends a list,
and the game buys the items in order while the money lasts.

- On the pistol rounds (round 1 and the first round of the second half) everyone has $800. It
  buys a vest.
- With $2700 or more, or with a rifle kept from the last round: a rifle if it has none (the best
  one it can pay for together with its ammo and a vest, else the cheaper one), then rifle ammo,
  then a vest and helmet (a vest if the money is short) if its armor is not full. A CT with $3500
  or more also buys a defuse kit.
- With less, it saves.
- Every round it also buys pistol ammo.

A gun you buy comes with a full magazine and none of its own spare rounds; that is why the
rifle's ammo comes right after it. See [Buying](docs/BOT_API.md#buying).

### 10. Its log

`self.log(...)` writes one line to stderr, starting with the tick number. The bot logs its plan
for the round, what it buys, what it hears and when it gets stuck. `say()` logs what it is doing
only when that changes, so the log stays short. Never print to stdout yourself: stdout carries
only protocol lines. (Inside `run`, `print()` goes to stderr.) See
[Your log](docs/BOT_API.md#your-log).

## Upload it

### Zip it

The zip has `bot.yaml` at the top, next to `bot.py`. On macOS or Linux, from the kit's folder:

```bash
rm -f my-bot.zip
cd bots/reference && zip -r ../../my-bot.zip . && cd ../..
```

On Windows, in PowerShell, from the kit's folder:

```powershell
Compress-Archive -Path bots\reference\* -DestinationPath my-bot.zip -Force
```

Both make `my-bot.zip` in the kit's folder. A zip of the folder itself works too, for example
from the Finder's Compress: when everything is in one top folder, the platform leaves that folder
out. The zip may be at most 10 MB, 50 MB unpacked, with at most 2000 entries. The platform refuses
a name with `\` in it. The Reference bot has no subfolders, so its zip has no such names; once
your bot has subfolders, check that your zip tool writes `/` between folder names. See
[The zip](docs/BOT_API.md#the-zip).

The platform runs `python` as Python 3.12.16 with `arena_sdk`, `pydantic` and `numpy`, and
`node` as Node 24.22.3. Nothing else can be installed: the zip is all you bring. Each start of
the bot gets 512 MiB of memory, 1 CPU and no network, and everything is read-only except `/tmp`.
See [Runtimes](docs/BOT_API.md#runtimes) and [Limits](docs/BOT_API.md#limits).

### Upload it on My bot

1. Open **My bot**.
2. Under **Upload a version**, choose `my-bot.zip` and press **Upload**.

A zip that breaks a rule is refused, with a sentence that says why. Every upload is a new
version, v1, v2 and so on, and a version never changes. Your first upload creates your bot; its
name is your name until you change it under **Name**. You can upload at most 20 times in any 24
hours. See [Versions](docs/BOT_API.md#versions).

### The check match

A new version is **Checking** first. It plays a check match on de_dust2 against the Reference
bot: 2 rounds, your bot as T in the first and as CT in the second. Then it becomes:

- **Ready** if the match completed and your bot answered `hello` with `ready` in time, never
  crashed or stopped running, never sent an invalid action, and missed the deadline on fewer than
  10 % of the ticks. Warnings are fine.
- **Broken** otherwise, with a note that names the first rule it failed, such as `crashes 1` or
  `invalid 3`.

Only Ready versions can play. The version's row on My bot links the check's **Match** and your
**Log**. While no runner (a machine with the game server) is connected, matches wait in the
queue, and the site says so. See [The check match](docs/BOT_API.md#the-check-match).

### Watch a match

A match's page shows the 2D replay, or the live view while the match runs. Click a player to see
what its bot was sent and what it answered on that tick. After the match, the page links the logs
of your own bots; only you and the admins can read them. See
[Your log](docs/BOT_API.md#your-log).

### Practice matches

On **New match** you choose the map, the number of rounds (an even number from 2 to 30) and the
players per side (1 to 5). For each player you choose a bot and one of its Ready versions: yours,
a friend's, the Reference bot's or the TS minimal bot's. **Launch** puts the match in the queue.
At most 3 of your practice matches can be queued or running at once. Matches do not run in real
time: they run as fast as the game server and the bots allow.

### Tournaments

An admin creates a tournament: a round robin in which every participant plays every other one
once. With more than one player per side, each side is copies of one participant's bot. Each
participant plays their **Version for tournaments** from My bot: the Ready version they chose,
else their latest Ready one. It is fixed when the tournament is created; later uploads do not
change it. A win is worth 3 points and a draw 1; equal points are ranked by round difference,
then by rounds won. See [Versions](docs/BOT_API.md#versions).

## Next

### Change the Reference bot

Copy it to a folder of your own, change it, and zip that folder:

```bash
cp -r bots/reference bots/my_bot
rm -f my-bot.zip
cd bots/my_bot && zip -r ../../my-bot.zip . && cd ../..
```

Some things it does not do, as places to start:

- It always goes to the same bomb site: T to A, CT to B (`SITE`).
- It never buys or throws grenades.
- It always runs, so the enemy hears its steps. Walking (`walk`) and ducking are silent
  ([Moving](docs/BOT_API.md#moving)).
- It fights standing still, wherever it meets the enemy.
- As CT it holds one spot until the bomb is planted.

Every upload plays its own check match, so a bot that crashes in those 2 rounds is caught before
it plays anyone.
Read its log when something looks wrong.

### Write a bot in another language

[`bots/examples/ts-minimal/`](bots/examples/ts-minimal/) is a TypeScript bot without packages or
the SDK: it reads the JSON lines and writes the actions itself. Node 24 runs it as
`node bot.ts`, and the platform runs it the same way. It runs at the nearest enemy it sees, else
towards the enemy spawn, and shoots when aimed. `protocol.ts` has hand-written types for the
fields it uses; [`schema/protocol.v1.json`](schema/protocol.v1.json) describes every message.
The platform runs only Python and Node. See [Other languages](docs/BOT_API.md#9-other-languages)
and [Runtimes](docs/BOT_API.md#runtimes). To zip it:

```bash
rm -f my-bot.zip
cd bots/examples/ts-minimal && zip -r ../../../my-bot.zip . && cd ../../..
```

### Have an LLM write one

[`docs/PROMPT_FOR_LLM.md`](docs/PROMPT_FOR_LLM.md) is a prompt for a chat with an LLM. Paste
everything below its line into a chat with an LLM, then the text of `docs/BOT_API.md`, and attach
`bots/reference/bot.py`. It asks for a `bot.py`
and its `bot.yaml`: put them in a folder, zip it as above and upload it.

### The SDK on your own machine

This kit has no game in it: the platform plays every match. To have `arena_sdk` on your machine
as well, for your editor or to try parts of your bot, install it with Python 3.12 or newer:

```bash
python3 -m venv .venv    # on Windows: py -m venv .venv
. .venv/bin/activate    # on Windows: .venv\Scripts\activate
pip install ./arena_sdk
```

`uv pip install ./arena_sdk` works too.

## License

MIT, see [LICENSE](LICENSE). Counter-Strike is Valve's game; this project is not affiliated with
Valve, and the kit holds no game files.
