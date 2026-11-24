"""Bot protocol v1: every message between the arena and a bot (see docs/BOT_API.md).

These models are the single source of truth: schema/protocol.v1.json is generated from them.

Units: positions in GoldSrc units, angles in degrees, time in seconds unless a field says `_ms`.
Yaw: 0 = +X, counter-clockwise (towards +Y), in (-180, 180].
Pitch: positive = looking up, in [-89, 89]. The engine uses the opposite sign (down positive);
the arena converts at its boundary, bots never see engine pitch.
"""

import json
from typing import Annotated, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, ValidationError, ValidationInfo, field_validator

Team = Literal["T", "CT"]
Vec3 = tuple[float, float, float]

# Weapon entity names without the "weapon_" prefix (not buy-menu aliases: "glock18", not "glock").
WeaponName = Literal[
    "glock18", "usp", "p228", "deagle", "elite", "fiveseven",
    "m3", "xm1014",
    "mac10", "tmp", "mp5navy", "ump45", "p90",
    "galil", "famas", "ak47", "m4a1", "sg552", "aug", "scout", "awp", "sg550", "g3sg1",
    "m249",
    "knife", "hegrenade", "flashbang", "smokegrenade", "c4",
]  # fmt: skip
BuyItem = Literal[
    "glock18", "usp", "p228", "deagle", "elite", "fiveseven",
    "m3", "xm1014",
    "mac10", "tmp", "mp5navy", "ump45", "p90",
    "galil", "famas", "ak47", "m4a1", "sg552", "aug", "scout", "awp", "sg550", "g3sg1",
    "m249",
    "hegrenade", "flashbang", "smokegrenade",
    "vest", "vesthelm", "defuser", "nvgs", "shield", "primammo", "secammo",
]  # fmt: skip
Button = Literal["attack", "attack2", "jump", "duck", "walk", "reload", "use"]
SoundKind = Literal[
    "step", "jump", "land", "shot", "reload", "bomb_plant", "bomb_defuse", "grenade_explode",
    "bomb_beep",
]  # fmt: skip

_WEAPONS = frozenset(get_args(WeaponName))
_ALLOWED = {"buttons": frozenset(get_args(Button)), "buy": frozenset(get_args(BuyItem))}
MAX_LINE = 64 * 1024  # longest accepted action line
MAX_WARNINGS = 20  # per action, plus one "… N more"


class _ToBot(BaseModel):
    """Sent by the arena: every field is always present, unknown fields are ignored."""

    model_config = ConfigDict(
        use_attribute_docstrings=True,
        json_schema_mode_override="serialization",
        json_schema_serialization_defaults_required=True,
    )


class _FromBot(BaseModel):
    """Sent by the bot: fields may be omitted; unknown fields, NaN/Infinity and values of the
    wrong type (no coercion: "1" or true is not a number) are rejected."""

    model_config = ConfigDict(
        use_attribute_docstrings=True,
        json_schema_mode_override="validation",
        extra="forbid",
        allow_inf_nan=False,
        strict=True,
    )


class Rules(_ToBot):
    """Arena rules for this match (sent in `hello.config`). Defaults are the arena defaults."""

    tick_hz: int = Field(20, gt=0)
    """Observations per second of game time (20 = one tick every 50 ms)."""
    deadline_ms: int = 200
    """Wall-clock time a bot has to answer a tick."""
    fov_deg: float = 90
    """Horizontal field of view, degrees."""
    fov_vertical_deg: float = 74
    """Vertical field of view, degrees (90 horizontal on a 4:3 screen is about 74 vertical)."""
    vision_delay_ms: int = 150
    """Enemies are seen as they were this long ago."""
    sound_dir_noise_deg: float = 10
    """Sound direction error: uniform in [-noise, +noise] degrees."""
    max_turn_rate_dps: float = 720
    """Turn limit, degrees per second, applied to yaw and pitch separately."""
    teammates_visible: bool = True
    """Teammates' positions are sent like the radar in CS."""
    step_speed: float = 150
    """Footsteps only above this speed, jumps at this speed or faster, units/s (CS 1.6)."""
    step_radius: float = 1100
    """Hearing radius of a footstep or a jump, units."""
    land_radius: float = 1100
    """Hearing radius of a landing, units."""
    reload_radius: float = 1100
    """Hearing radius of a reload, units."""
    shot_radius: float = 2000
    """Hearing radius of an unsilenced shot, units."""
    silenced_shot_radius: float = 1000
    """Hearing radius of a shot from a silenced M4A1/USP or the TMP, units."""
    bomb_plant_radius: float = 1100
    """Hearing radius of the start of a bomb plant, units."""
    bomb_defuse_radius: float = 1100
    """Hearing radius of the start of a defuse, units."""
    grenade_explode_radius: float = 99999
    """Hearing radius of a grenade detonation, units (the whole map)."""
    sound_near_max: float = 500
    """Sounds up to this distance are "near", units."""
    sound_mid_max: float = 1500
    """Sounds up to this distance (and beyond near) are "mid"; farther ones are "far", units."""


class Overtime(_ToBot):
    enabled: bool = True
    """Whether a tie after `max_rounds` is played on in overtimes."""
    max_rounds: int = 6
    """Rounds in each overtime."""
    start_money: int = 10000
    """Money at the start of each overtime, dollars."""


class MatchSettings(_ToBot):
    """Public match settings (sent in `hello.match`). Defaults are the arena defaults."""

    max_rounds: int = 30
    """Rounds in regulation time; sides switch after half of them (MR15 = 30)."""
    overtime: Overtime = Overtime()
    freeze_time: int = 3
    """Freeze time at the start of each round, seconds."""
    buy_time: int = 15
    """Buy time, seconds."""
    round_time: int = 115
    """Round time, seconds."""
    c4_timer: int = 35
    """Seconds from the plant to the explosion."""
    start_money: int = 800
    """Money at the start of the match and of the second half, dollars."""


class NavZone(_ToBot):
    """A named place: a polygon in x/y and a z range."""

    name: str
    """E.g. "BombsiteA", "Mid", "LongA"."""
    z: tuple[float, float]
    polygon: list[tuple[float, float]]


class NavData(_ToBot):
    """The map's navigation mesh. `arena_sdk.nav.NavMesh.from_json(hello.map.nav)` gives
    `path`, `place_of` and `area_at`."""

    areas: list[tuple[int, int, float, float, float, float, float, float, float, float, list[int]]]
    """`[id, flags, x0, y0, z0, x1, y1, z1, ne_z, sw_z, [ids of areas you can walk to]]`: a
    rectangle from (x0, y0) to (x1, y1) with the floor height at each corner: z0 at (x0, y0),
    z1 at (x1, y1), ne_z at (x1, y0), sw_z at (x0, y1). Flags: 1 crouch, 2 jump, 4 precise,
    8 no jump."""
    zones: list[NavZone]
    """Named places; the first zone that contains a point names it."""


class MapInfo(_ToBot):
    """Static map information."""

    name: str
    """Map name, e.g. "de_dust2"."""
    bombsites: dict[Literal["A", "B"], tuple[Vec3, Vec3]]
    """Bomb site areas by letter, as `[min corner, max corner]` boxes."""
    buyzones: dict[Team, list[tuple[Vec3, Vec3]]]
    """Buy zone boxes per side, `[min corner, max corner]`."""
    spawns: dict[Team, list[Vec3]]
    """Spawn points per side (player origins)."""
    nav: NavData


class Hello(_ToBot):
    """First message of a match. Answer with `ready`."""

    type: Literal["hello"] = "hello"
    protocol: Literal[1] = 1
    """Protocol version."""
    player_id: str
    """Your id; other players' ids appear in `visible_enemies`, `teammates` and `events`."""
    side: Team
    """Your side now (a bot restarted mid-match gets the current side). Sides change at half
    time: see `round_start.side`."""
    map: MapInfo
    match: MatchSettings
    config: Rules


class Ready(_FromBot):
    """The bot's answer to `hello`."""

    type: Literal["ready"]


class Score(_ToBot):
    """Rounds won, from your point of view."""

    own: int
    enemy: int


class RoundStart(_ToBot):
    """A new round begins (freeze time)."""

    type: Literal["round_start"] = "round_start"
    number: int
    """Round number, starting at 1."""
    side: Team
    """Your side in this round."""
    score: Score


class RoundState(_ToBot):
    number: int
    """Round number, starting at 1."""
    phase: Literal["freeze", "live", "bomb_planted", "over"]
    time_left: float | None
    """Seconds left in this phase; null while the bomb is planted (CS 1.6 hides the timer)."""
    score: Score
    side: Team
    """Your side in this round."""
    bomb_planted: bool
    """Whether the bomb is planted. Where is not said: look for `obs.bomb`, listen for
    `bomb_beep`."""


class WeaponState(_ToBot):
    name: WeaponName
    slot: int
    """1 primary, 2 pistol, 3 knife, 4 grenades, 5 bomb."""
    clip: int | None
    """Rounds in the magazine; null for the knife, grenades and the bomb."""
    reserve: int
    """Spare rounds; for grenades, how many you carry."""


class SelfState(_ToBot):
    """Your own player, exact and current."""

    pos: Vec3
    """Player origin (centre of the hull), units."""
    vel: Vec3
    """Velocity, units/s."""
    yaw: float
    """View yaw, degrees."""
    pitch: float
    """View pitch, degrees, positive = up."""
    hp: int
    armor: int
    helmet: bool
    money: int
    alive: bool
    on_ground: bool
    ducking: bool
    in_buy_zone: bool
    in_bomb_site: Literal["A", "B"] | None
    has_c4: bool
    has_defuser: bool
    weapons: list[WeaponState]
    active_weapon: WeaponName | None
    can_buy: bool
    """In a buy zone during buy time."""


class VisibleEnemy(_ToBot):
    """An enemy you can see, as it was `vision_delay_ms` ago."""

    id: str
    pos: Vec3
    """Origin then, units."""
    head_pos: Vec3
    """Head then, units."""
    rel_yaw: float
    """Yaw from your current eyes to `head_pos`, relative to your current view; positive = left."""
    rel_pitch: float
    """Pitch from your current eyes to `head_pos`, relative to your current view; positive = up."""
    distance: float
    """From your current eyes to `head_pos`, units."""
    weapon: WeaponName | None
    ducking: bool


class VisibleBomb(_ToBot):
    """The bomb on the ground, if you can see it, as it was `vision_delay_ms` ago."""

    pos: Vec3
    """Bomb position, units."""
    state: Literal["dropped", "planted"]


class Teammate(_ToBot):
    id: str
    pos: Vec3
    alive: bool


class Sound(_ToBot):
    """A sound you heard since the previous tick (through walls too)."""

    kind: SoundKind
    yaw: float
    """World yaw from you to the source, in 0.1 degree steps, with noise of up to
    `sound_dir_noise_deg`."""
    distance_band: Literal["near", "mid", "far"]
    """Rough distance: see `sound_near_max` and `sound_mid_max`."""
    age_ms: int
    """How long ago the sound was made."""


class DamagedBy(_ToBot):
    """You were hit."""

    kind: Literal["damaged_by"] = "damaged_by"
    yaw: float
    """World yaw from you to the attacker."""


class Killed(_ToBot):
    """You killed a player."""

    kind: Literal["killed"] = "killed"
    id: str


class Hit(_ToBot):
    """You hit a player."""

    kind: Literal["hit"] = "hit"
    id: str
    damage: int


Event = Annotated[DamagedBy | Killed | Hit, Field(discriminator="kind")]


class Observation(_ToBot):
    tick: int
    """Tick number; echo it in `action.tick`."""
    time: float
    """Game time, seconds."""
    round: RoundState
    self: SelfState
    visible_enemies: list[VisibleEnemy]
    bomb: VisibleBomb | None
    """The dropped or planted bomb when you see it (same rules as enemies); null otherwise."""
    teammates: list[Teammate]
    sounds: list[Sound]
    events: list[Event]
    """What happened to you since the previous tick."""
    warnings: list[str]
    """Problems with your previous action, e.g. an unknown item in `buy`."""


class Tick(_ToBot):
    """One observation. Answer with exactly one `action` line."""

    type: Literal["tick"] = "tick"
    obs: Observation


class Move(_FromBot):
    forward: float = Field(0.0, ge=-1, le=1)
    """Forward (+) / back (-), relative to the view; 1 = full speed of the active weapon."""
    side: float = Field(0.0, ge=-1, le=1)
    """Right (+) / left (-), relative to the view."""


class Look(_FromBot):
    dyaw: float = 0.0
    """Turn, degrees, positive = left; clamped to the turn limit."""
    dpitch: float = 0.0
    """Turn, degrees, positive = up; clamped to the turn limit, pitch stays within ±89."""


class Action(_FromBot):
    """The bot's answer to a tick. Every field may be omitted; `{}` does nothing."""

    type: Literal["action"] = "action"
    tick: int | None = None
    """The tick you are answering."""
    move: Move = Move()
    look: Look = Look()
    buttons: list[Button] = []
    """Buttons held during this tick."""
    weapon: WeaponName | Annotated[int, Field(ge=1, le=5)] | None = None
    """Switch to a weapon by name or by slot (1-5)."""
    buy: list[BuyItem] = []
    """Items to buy, in order; only in a buy zone during buy time."""

    @field_validator("buttons", "buy", mode="before")
    @classmethod
    def _drop_unknown_names(cls, value, info: ValidationInfo):
        warnings = _warnings(info)
        if warnings is None or not isinstance(value, list):
            return value
        allowed = _ALLOWED[info.field_name]
        kept = []
        for item in value:
            if isinstance(item, str) and item not in allowed:
                _report_unknown(warnings, info.field_name, item)
            else:
                kept.append(item)  # known, or of a wrong type that rejects the action
        return kept

    @field_validator("weapon", mode="before")
    @classmethod
    def _drop_unknown_weapon(cls, value, info: ValidationInfo):
        warnings = _warnings(info)
        unknown = (isinstance(value, str) and value not in _WEAPONS) or (
            type(value) is int and not 1 <= value <= 5
        )
        if warnings is None or not unknown:
            return value
        _report_unknown(warnings, "weapon", value)
        return None


class RoundEnd(_ToBot):
    type: Literal["round_end"] = "round_end"
    number: int
    """The round that ended."""
    winner: Team | None
    """Winning side; null for a draw."""
    reason: Literal[
        "bomb_exploded", "bomb_defused", "t_eliminated", "ct_eliminated", "time_expired", "draw"
    ]  # fmt: skip
    score: Score
    """Score after this round."""


class MatchEnd(_ToBot):
    """Last message of the match."""

    type: Literal["match_end"] = "match_end"
    result: Literal["win", "loss", "draw"]
    score: Score


Message = Annotated[
    Hello | Ready | RoundStart | Tick | Action | RoundEnd | MatchEnd, Field(discriminator="type")
]


def _warnings(info: ValidationInfo) -> list[str] | None:
    return info.context.get("warnings") if isinstance(info.context, dict) else None


def _report_unknown(warnings: list[str], field: str, value: str | int) -> None:
    if isinstance(value, str) and len(value) > 40:
        value = value[:40] + "…"
    warnings.append(f"{field}: unknown {json.dumps(value, ensure_ascii=False)} ignored")


def parse_action(line: str | bytes) -> tuple[Action, list[str]]:
    """Validate one action line from a bot.

    Unknown names in `buttons`, `buy` and `weapon` (and a weapon slot outside 1-5) are dropped
    and returned as warnings for the next `obs.warnings`: at most MAX_WARNINGS, then one
    "… N more". Anything else invalid raises `pydantic.ValidationError`, including a line
    longer than MAX_LINE (bytes; characters if `line` is a str — the arena passes bytes).
    Built in Python without this function, an unknown name is a validation error instead.
    """
    if len(line) > MAX_LINE:
        raise ValidationError.from_exception_data(
            "Action",
            [
                {
                    "type": "too_long",
                    "loc": (),
                    "input": line[:40],
                    "ctx": {
                        "field_type": "Line",
                        "max_length": MAX_LINE,
                        "actual_length": len(line),
                    },
                }
            ],
        )
    warnings: list[str] = []
    action = Action.model_validate_json(line, context={"warnings": warnings})
    if len(warnings) > MAX_WARNINGS:
        warnings[MAX_WARNINGS:] = [f"… {len(warnings) - MAX_WARNINGS} more"]
    return action, warnings
