"""CS 1.6 Bot Arena SDK for bot authors.

    from arena_sdk import Action, Bot, run

    class MyBot(Bot):
        def on_tick(self, obs):
            return Action(move={"forward": 1.0})

    run(MyBot())

`Bot` and `run` (`arena_sdk.bot`) do the stdin/stdout protocol; `angle_to`, `move_towards` and
`PathFollower` (`arena_sdk.aim`) aim and walk; `self.map` (`GameMap`, a `NavMesh` from
`arena_sdk.nav`) has `path`, `place_of` and the bomb sites; the message models are in
`arena_sdk.protocol`.
"""

from arena_sdk.aim import PathFollower, angle_to, eye, move_towards, wrap180
from arena_sdk.bot import Bot, GameMap, run
from arena_sdk.nav import NavMesh
from arena_sdk.protocol import (
    Action,
    Hello,
    Look,
    MatchEnd,
    Move,
    Observation,
    RoundEnd,
    RoundStart,
    SelfState,
    VisibleEnemy,
)

__all__ = [
    "Action",
    "Bot",
    "GameMap",
    "Hello",
    "Look",
    "MatchEnd",
    "Move",
    "NavMesh",
    "Observation",
    "PathFollower",
    "RoundEnd",
    "RoundStart",
    "SelfState",
    "VisibleEnemy",
    "angle_to",
    "eye",
    "move_towards",
    "run",
    "wrap180",
]
