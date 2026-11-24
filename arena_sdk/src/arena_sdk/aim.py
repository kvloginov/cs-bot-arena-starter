"""Aiming and moving helpers: turn towards a point, walk towards a point, follow a nav path.

Angles follow the protocol: yaw 0 = +X, counter-clockwise, positive turn = left; pitch positive
= up. Positions are world units; a player position is the player's origin.
"""

import math

from arena_sdk.nav import NavMesh, Vec
from arena_sdk.protocol import Move, SelfState

EYE_HEIGHT = 17.0  # eyes above the origin when standing (CS 1.6 VEC_VIEW)
EYE_HEIGHT_DUCKED = 12.0  # when ducked (VEC_DUCK_VIEW)
STAND_HEIGHT = 36.0  # the origin above the floor when standing
STEP_HEIGHT = 18.0  # the highest step you walk up without jumping (sv_stepsize)


def wrap180(deg: float) -> float:
    """The same angle in (-180, 180]."""
    return 180.0 - (180.0 - deg) % 360.0


def eye(me: SelfState) -> Vec:
    """Where your eyes are: the origin plus 17 units standing, 12 ducked."""
    x, y, z = me.pos
    return (x, y, z + (EYE_HEIGHT_DUCKED if me.ducking else EYE_HEIGHT))


def angle_to(me: SelfState, pos: Vec) -> tuple[float, float]:
    """`(dyaw, dpitch)` that turn your current view onto `pos`, seen from your eyes; dyaw in
    (-180, 180], positive = left / up. Send them as `look`: the arena turns at most
    `max_turn_rate_dps / tick_hz` degrees per tick (36), so a big turn takes several ticks."""
    ex, ey, ez = eye(me)
    dx, dy, dz = pos[0] - ex, pos[1] - ey, pos[2] - ez
    yaw = math.degrees(math.atan2(dy, dx))
    pitch = math.degrees(math.atan2(dz, math.hypot(dx, dy)))
    return wrap180(yaw - me.yaw), pitch - me.pitch


def move_towards(me: SelfState, pos: Vec, yaw: float | None = None) -> Move:
    """The `move` that walks towards `pos` at full speed (height ignored) whichever way you
    look: the world direction split into forward and side for the view yaw.

    The arena turns first and then moves, so if you also send a `look` this tick, pass the yaw
    you will have after it: `me.yaw + dyaw`, with dyaw clamped to `Bot.turn_limit`."""
    dx, dy = pos[0] - me.pos[0], pos[1] - me.pos[1]
    dist = math.hypot(dx, dy)
    if dist < 1e-6:
        return Move()
    view = math.radians(me.yaw if yaw is None else yaw)
    forward = (dx * math.cos(view) + dy * math.sin(view)) / dist
    side = (dx * math.sin(view) - dy * math.cos(view)) / dist  # "right" points at yaw - 90°
    # min/max: rounding can give 1.0000000000000002, which `move` rejects
    return Move(forward=max(-1.0, min(1.0, forward)), side=max(-1.0, min(1.0, side)))


def _dist2d(a: Vec, b: Vec) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _dist_to_segment2d(p: Vec, a: Vec, b: Vec) -> float:
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    length2 = (bx - ax) ** 2 + (by - ay) ** 2
    t = 0.0 if length2 == 0 else ((p[0] - ax) * (bx - ax) + (p[1] - ay) * (by - ay)) / length2
    t = max(0.0, min(1.0, t))
    return math.hypot(p[0] - (ax + t * (bx - ax)), p[1] - (ay + t * (by - ay)))


class PathFollower:
    """Walks `nav.path` to `goal`. Call `next_point(me.pos)` every tick and move towards the
    point it returns (`move_towards`).

    It plans on the first call, and plans again from where you are whenever you are more than
    `off_path` units (horizontally) from the leg you should be walking, e.g. after a fight. A
    waypoint counts as reached within `reach` units horizontally, but not while it is more than
    `STEP_HEIGHT` above your feet: a ledge you have to jump onto. Waypoints are the floor at the
    area centres along the path, then the point of the last area closest to `goal`. Returns None
    once the goal is reached, or when there is no path to it.
    """

    def __init__(self, nav: NavMesh, goal: Vec, reach: float = 40.0, off_path: float = 150.0):
        self.nav, self.goal, self.reach, self.off_path = nav, goal, reach, off_path
        self.points: list[Vec] = []  # waypoints still ahead
        self.leg_start: Vec | None = None  # where the current leg began; None = not planned yet

    def next_point(self, pos: Vec) -> Vec | None:
        if self.leg_start is None or (
            self.points and _dist_to_segment2d(pos, self.leg_start, self.points[0]) > self.off_path
        ):
            self.plan(pos)
        while self.points and self._reached(pos, self.points[0]):
            self.leg_start = self.points.pop(0)
        return self.points[0] if self.points else None

    def plan(self, pos: Vec) -> None:
        areas = self.nav.path(pos, self.goal)
        self.leg_start = pos
        if areas is None:
            self.points = []
        else:  # the first area is the one we stand in: its centre may be behind us, skip it
            self.points = [a.closest_point(a.center) for a in areas[1:-1]]
            self.points.append(areas[-1].closest_point(self.goal))

    def _reached(self, pos: Vec, point: Vec) -> bool:
        feet = pos[2] - STAND_HEIGHT
        return _dist2d(pos, point) <= self.reach and point[2] - feet <= STEP_HEIGHT
