"""Bot runner: subclass `Bot`, override the handlers you need, call `run(MyBot())`.

`run` reads the arena's messages from stdin (one JSON object per line), calls the handlers and
writes the answers to stdout: `ready` after `hello`, and exactly one `action` per `tick` with the
tick number filled in. stdout carries only protocol lines; log with `Bot.log` or `print` (both go
to stderr while `run` runs).
"""

import json
import sys
import traceback
from dataclasses import dataclass, field
from time import monotonic

from pydantic import ValidationError

from arena_sdk.nav import NavMesh, Vec
from arena_sdk.protocol import (
    Action,
    Hello,
    MapInfo,
    MatchEnd,
    Observation,
    RoundEnd,
    RoundStart,
    Rules,
    Tick,
    parse_action,
)


@dataclass
class GameMap(NavMesh):
    """`hello.map` for bots: the nav mesh (`path`, `place_of`, `area_at`, `nearest_area`) plus
    the map's name, bomb sites `{"A": (min, max)}`, buy zones and spawns per side."""

    name: str = ""
    bombsites: dict[str, tuple[Vec, Vec]] = field(default_factory=dict)
    buyzones: dict[str, list[tuple[Vec, Vec]]] = field(default_factory=dict)
    spawns: dict[str, list[Vec]] = field(default_factory=dict)

    @classmethod
    def from_info(cls, info: MapInfo) -> "GameMap":
        mesh = NavMesh.from_json(info.nav.model_dump())
        return cls(mesh.areas, mesh.zones, info.name, info.bombsites, info.buyzones, info.spawns)

    def bombsite_center(self, letter: str) -> Vec:
        lo, hi = self.bombsites[letter]
        return tuple((a + b) / 2 for a, b in zip(lo, hi, strict=True))


class Bot:
    """Base class for a bot. Every handler is optional; the defaults do nothing.

    `run` sets `self.hello` (the whole `hello` message) and `self.map` (a `GameMap`) before it
    calls `on_hello`, and `self.tick` (the tick being answered) before each `on_tick`. If the
    `hello` cannot be read, both stay None, `on_hello` is not called and `ready` is sent anyway.
    """

    hello: Hello | None = None
    map: GameMap | None = None
    tick: int = 0

    def on_hello(self, hello: Hello) -> None:
        """The match starts. `ready` is sent when this returns (the arena waits 10 s)."""

    def on_round_start(self, msg: RoundStart) -> None:
        """A round starts (freeze time); `msg.side` is your side in it."""

    def on_tick(self, obs: Observation) -> Action | dict | None:
        """Your action for this tick: an `Action`, a dict shaped like the action JSON, or None
        to stand still. `tick` is filled in for you. Answer within `hello.config.deadline_ms`.

        Return a dict to have unknown names reported by the arena (`obs.warnings`); building
        `Action(...)` with an unknown name raises in your code (logged, empty action). A dict the
        arena will reject is logged and sent as it is, so the arena counts it as invalid; only a
        value that cannot be written as JSON becomes an empty action."""
        return None

    def on_round_end(self, msg: RoundEnd) -> None:
        """A round ended."""

    def on_match_end(self, msg: MatchEnd) -> None:
        """The match ended; stdin closes next."""

    @property
    def turn_limit(self) -> float:
        """The most the arena turns you per tick, degrees per axis: larger `look` values are
        clamped to it (`max_turn_rate_dps / tick_hz`, 36 by default)."""
        config = self.hello.config if self.hello else Rules()
        return config.max_turn_rate_dps / config.tick_hz

    def log(self, *parts: object) -> None:
        """One line to stderr, prefixed with the current tick."""
        _log(self.tick, *parts)


def _log(tick: object, *parts: object) -> None:
    """The SDK's own log line; it never goes through `Bot.log`, which a bot may replace."""
    print(f"[{tick}]", *parts, file=sys.stderr, flush=True)


_errors: dict[tuple, list[float]] = {}  # error key -> [repeats so far, time of the last line]


def _log_error(tick: object, what: str) -> None:
    """In an `except` block: `what` and the traceback the first time an error (its type and
    the places in its traceback) occurs, then at most one "same error again (N)" line a second
    for it."""
    exc = sys.exception()
    places = tuple((f.filename, f.lineno) for f in traceback.extract_tb(exc.__traceback__))
    now, seen = monotonic(), _errors.get((type(exc), places))
    if seen is None:
        _errors[type(exc), places] = [0, now]
        _log(tick, what)
        traceback.print_exc()
        return
    seen[0] += 1
    if now - seen[1] >= 1:
        seen[1] = now
        _log(tick, f"{what}: same error again ({seen[0]})")


_MESSAGES = {
    "hello": Hello,
    "round_start": RoundStart,
    "tick": Tick,
    "round_end": RoundEnd,
    "match_end": MatchEnd,
}
READY = json.dumps({"type": "ready"})


def run(bot: Bot, stdin=None, stdout=None) -> None:
    """Play one match: read messages until stdin closes, answer on stdout.

    While it runs, `sys.stdout` points at stderr, so a stray `print()` in your code lands in the
    log and cannot break the protocol; the answers go to the real stdout."""
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    _errors.clear()
    saved, sys.stdout = sys.stdout, sys.stderr
    try:
        for line in stdin:
            if line.strip():
                answer = handle(bot, line)
                if answer is not None:
                    stdout.write(answer + "\n")
                    stdout.flush()
    finally:
        sys.stdout = saved


def handle(bot: Bot, line: str) -> str | None:
    """The answer line to one message from the arena, or None if it needs no answer.

    Never raises: a failing handler is logged with its traceback and a tick still gets an
    (empty) action, so the arena never waits out the deadline because of a bug; an unreadable
    `hello` still gets `ready`.
    """
    try:
        raw = json.loads(line)
        msg = _MESSAGES[raw["type"]].model_validate(raw)
    except Exception:
        _log_error(bot.tick, f"cannot read message {line[:120]!r}")
        return _unreadable_answer(line)

    if isinstance(msg, Hello):
        try:
            bot.hello = msg
            bot.map = GameMap.from_info(msg.map)
            bot.on_hello(msg)
        except Exception:
            _log_error(bot.tick, "on_hello failed, answering ready anyway")
        return READY

    if isinstance(msg, Tick):
        bot.tick = msg.obs.tick
        try:
            return _action_line(bot.on_tick(msg.obs), msg.obs.tick)
        except Exception:
            _log_error(msg.obs.tick, "on_tick failed, standing still this tick")
            return json.dumps({"type": "action", "tick": msg.obs.tick})

    handler = {
        RoundStart: bot.on_round_start,
        RoundEnd: bot.on_round_end,
        MatchEnd: bot.on_match_end,
    }[type(msg)]
    try:
        handler(msg)
    except Exception:
        _log_error(bot.tick, f"{handler.__name__} failed")
    return None


def _action_line(result: Action | dict | None, tick: int) -> str:
    """The action as given, with `tick` set, after checking it the way the arena will
    (`parse_action`). Unknown names and anything the arena will reject are logged and still
    sent, so the arena reports them (`obs.warnings`, the replay, the `invalid` count) as
    for any bot. Raises only if the result cannot be written as an action line."""
    if result is None:
        data = {}
    elif isinstance(result, Action):
        data = result.model_dump(mode="json", exclude_defaults=True)
    elif isinstance(result, dict):
        data = result
    else:
        raise TypeError(f"on_tick returned {type(result).__name__}; expected Action, dict, None")
    line = json.dumps({"type": "action", **data, "tick": tick})
    try:
        _, warnings = parse_action(line)
    except ValidationError as e:
        why = "; ".join(f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors())
        _log(tick, "action rejected by the arena:", why)
        return line
    for warning in warnings:
        _log(tick, "action:", warning)
    return line


def _unreadable_answer(line: str) -> str | None:
    """The answer to a message that cannot be read: `ready` for a hello, an empty action for a
    tick whose number can be found, else None."""
    try:
        raw = json.loads(line)
        if raw.get("type") == "hello":
            return READY
        tick = raw["obs"]["tick"] if raw.get("type") == "tick" else None
        return json.dumps({"type": "action", "tick": tick}) if type(tick) is int else None
    except Exception:
        return None
