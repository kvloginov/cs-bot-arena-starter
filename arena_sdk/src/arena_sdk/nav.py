"""Map navigation for bots: A* over the nav mesh and place names (stdlib only).

The arena sends the mesh as plain JSON (`NavMesh.to_json`, built from the zBot `.nav` file and
the map's place overlay); a bot rebuilds it with `NavMesh.from_json` and calls `path`,
`place_of` and `area_at`. Positions are world units `(x, y, z)`; a player position is the
player's origin, 36 units above the floor when standing.
"""

import heapq
import math
from dataclasses import dataclass, field

Vec = tuple[float, float, float]


@dataclass(frozen=True)
class Area:
    """One nav area: an axis-aligned rectangle in x/y with a height at each corner."""

    id: int
    flags: int  # 1 crouch, 2 jump, 4 precise, 8 no jump (ReGameDLL NAV_*)
    lo: Vec  # corner at (min x, min y) and its z
    hi: Vec  # corner at (max x, max y) and its z
    ne_z: float  # z at (max x, min y)
    sw_z: float  # z at (min x, max y)
    links: tuple[int, ...]  # areas one can move to from here (one-way drops included)

    @property
    def center(self) -> Vec:
        return tuple((a + b) / 2 for a, b in zip(self.lo, self.hi, strict=True))

    def contains_xy(self, x: float, y: float) -> bool:
        return self.lo[0] <= x <= self.hi[0] and self.lo[1] <= y <= self.hi[1]

    def z_at(self, x: float, y: float) -> float:
        """Floor height at (x, y), clamped to the area (ReGameDLL `CNavArea::GetZ`)."""
        dx, dy = self.hi[0] - self.lo[0], self.hi[1] - self.lo[1]
        if dx == 0 or dy == 0:
            return self.ne_z
        u = min(max((x - self.lo[0]) / dx, 0.0), 1.0)
        v = min(max((y - self.lo[1]) / dy, 0.0), 1.0)
        north = self.lo[2] + u * (self.ne_z - self.lo[2])
        south = self.sw_z + u * (self.hi[2] - self.sw_z)
        return north + v * (south - north)

    def closest_point(self, pos: Vec) -> Vec:
        x = min(max(pos[0], self.lo[0]), self.hi[0])
        y = min(max(pos[1], self.lo[1]), self.hi[1])
        return (x, y, self.z_at(x, y))


@dataclass(frozen=True)
class Zone:
    """A named place: a polygon in x/y and a z range for the position."""

    name: str
    z: tuple[float, float]
    polygon: tuple[tuple[float, float], ...]

    @classmethod
    def from_json(cls, d: dict) -> "Zone":
        return cls(d["name"], tuple(d["z"]), tuple(tuple(p) for p in d["polygon"]))

    def contains(self, pos: Vec) -> bool:
        x, y, z = pos
        if not self.z[0] <= z <= self.z[1]:
            return False
        inside = False
        pts = self.polygon
        for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1], strict=True):
            if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                inside = not inside
        return inside


@dataclass
class NavMesh:
    areas: dict[int, Area]
    zones: list[Zone] = field(default_factory=list)  # first match wins

    @classmethod
    def from_json(cls, d: dict) -> "NavMesh":
        """From `{"areas": [[id, flags, x0, y0, z0, x1, y1, z1, ne_z, sw_z, [links]]],
        "zones": [{"name", "z": [lo, hi], "polygon": [[x, y], ...]}]}`."""
        areas = {
            a[0]: Area(a[0], a[1], tuple(a[2:5]), tuple(a[5:8]), a[8], a[9], tuple(a[10]))
            for a in d["areas"]
        }
        return cls(areas, [Zone.from_json(z) for z in d.get("zones", [])])

    def to_json(self) -> dict:
        """The structure `from_json` reads; coordinates rounded to whole units."""
        return {
            "areas": [
                [a.id, a.flags, *(round(v) for v in (*a.lo, *a.hi, a.ne_z, a.sw_z)), list(a.links)]
                for a in self.areas.values()
            ],
            "zones": [
                {"name": z.name, "z": list(z.z), "polygon": [list(p) for p in z.polygon]}
                for z in self.zones
            ],
        }

    def place_of(self, pos: Vec) -> str | None:
        """Name of the first zone containing `pos`, else None."""
        return next((zone.name for zone in self.zones if zone.contains(pos)), None)

    # ponytail: linear scans over all areas (0.04 ms for de_dust2's 737); add a grid like
    # ReGameDLL's CNavAreaGrid if per-tick lookups for many bots get slow.
    def area_at(self, pos: Vec) -> Area | None:
        """The area under `pos`: the highest one at most 5 above and 120 below it (zBot's
        `GetNavArea`, so a player origin works)."""
        x, y, z = pos
        best, best_z = None, -math.inf
        for area in self.areas.values():
            if area.contains_xy(x, y):
                area_z = area.z_at(x, y)
                if z - 120 <= area_z <= z + 5 and area_z > best_z:
                    best, best_z = area, area_z
        return best

    def nearest_area(self, pos: Vec) -> Area:
        """`area_at(pos)`, else the area whose closest point is nearest to `pos`."""
        return self.area_at(pos) or min(
            self.areas.values(), key=lambda a: math.dist(pos, a.closest_point(pos))
        )

    # ponytail: waypoints are area centres; portal midpoints (ReGameDLL ComputePortal) would
    # give straighter paths if bots snag on corners.
    def path(self, from_pos: Vec, to_pos: Vec) -> list[Area] | None:
        """A* over area centres along the links, from the area nearest `from_pos` to the area
        nearest `to_pos`; None if the goal cannot be reached. Walk the areas' `center`s."""
        start, goal = self.nearest_area(from_pos), self.nearest_area(to_pos)
        goal_c = goal.center
        cost = {start.id: 0.0}
        came: dict[int, int | None] = {start.id: None}
        heap = [(0.0, start.id)]
        while heap:
            _, aid = heapq.heappop(heap)
            if aid == goal.id:
                ids = []
                while aid is not None:
                    ids.append(aid)
                    aid = came[aid]
                return [self.areas[i] for i in reversed(ids)]
            area = self.areas[aid]
            for nid in area.links:
                nxt = self.areas[nid]
                c = cost[aid] + math.dist(area.center, nxt.center)
                if c < cost.get(nid, math.inf):
                    cost[nid], came[nid] = c, aid
                    heapq.heappush(heap, (c + math.dist(nxt.center, goal_c), nid))
        return None
