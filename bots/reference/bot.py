"""Reference bot for the CS 1.6 Bot Arena: a worked example of the SDK, not a strong player.

What it does, every round:
  T:    buy, walk the nav path to bomb site A, plant, hold the site, and walk back towards its
        spawn in time to be out of the blast when the bomb goes off.
  CT:   buy, walk to bomb site B and hold the way in; defuse a planted bomb it has seen. A bomb
        it has not seen it looks for at the site the beeps come from; before the first beep at
        the nearest site, then at the other one.
  Both: shoot the nearest visible enemy (turning is limited, so aiming takes a few ticks), look
        towards sounds and hits for a moment, reload when the magazine is empty and nobody is in
        sight, jump onto the nav mesh's jump areas on the way (ducking in the air), jump when
        stuck on a corner and hold where it is if that does not help. A plant or defuse, once
        started, goes on until it is done or the bot is hit. Without a map (an unreadable
        `hello`) it stands where it is and fights.

Run it with `python bot.py`: it talks to the arena over stdin/stdout (the SDK's `run`) and logs
what it decides to stderr. Rules are checked top to bottom in `on_tick`; the first that applies
decides the tick.
"""

import math

from arena_sdk import (
    Action,
    Bot,
    Look,
    Move,
    Observation,
    PathFollower,
    RoundStart,
    SelfState,
    VisibleEnemy,
    angle_to,
    move_towards,
    run,
    wrap180,
)

SITE = {"T": "A", "CT": "B"}  # where each side goes; fixed, so rounds are repeatable. The CT holds
# the other site, so a round shows the whole bomb cycle: plant, the T leaving, the search, defuse.
# Ammo is about what filling the reserve costs; the game sells as many boxes as the money allows.
PRICE = {
    "ak47": 2500, "galil": 2000, "m4a1": 3100, "famas": 2250,
    "vest": 650, "vesthelm": 1000, "defuser": 200, "primammo": 180, "secammo": 100,
}  # fmt: skip
PRIMAMMO = {"ak47": 240}  # the AK's 7.62 costs $80 a box, the other rifles' 5.56 $60
RIFLES = {"T": ("ak47", "galil"), "CT": ("m4a1", "famas")}  # best first
RIFLE_MONEY = 2700  # below this we save instead of buying a rifle
DEFUSER_MONEY = 3500  # a CT this rich also buys a defuse kit (defuse in 5 s instead of 10)
# Trigger patterns, one entry per tick while on target. Pistols fire once per press, so they need
# a released tick between shots; rifles fire short bursts so the recoil settles in between.
PISTOL_TRIGGER = (True, False)
RIFLE_TRIGGER = (True, True, True, False, False)
ALERT_S = 1.5  # how long we keep looking towards a sound or a hit, game seconds
DEFUSE_RANGE = 40  # horizontal distance to the bomb at which `use` reaches it
KNIFE_RANGE = 48  # the knife's reach: with no gun left, an enemy farther away is no fight
PROGRESS = 50  # walking, we count as getting somewhere once this far from where we were
STUCK_TICKS = 10  # this long without getting anywhere means a corner caught us: jump
GIVE_UP_TICKS = 60  # this long and the route cannot be walked from here: hold where we are
JUMP_AREA = 2  # nav area flag: getting onto this area takes a jump (a ledge)
JUMP_RANGE = 60  # jump this close (horizontally) to a route point in a jump area
# The blast (500 damage, 1750 u radius) reaches ~2800 u of route back from site A: 11-13 s at
# 250 or 221 u/s (knife or AK), so a T leaves its planted bomb this long before it goes off.
LEAVE_S = 12
BEEP_DISTANCE = {"near": 250, "mid": 1000, "far": 2500}  # a guess at how far a beep comes from


class ReferenceBot(Bot):
    side: str | None = None  # None until the first round starts

    def on_round_start(self, msg: RoundStart) -> None:
        self.side = msg.side
        self.enemy_side = "CT" if msg.side == "T" else "T"
        self.site = SITE[msg.side]
        self.go(self.map.bombsite_center(self.site) if self.map else None, f"site {self.site}")
        self.holding = self.map is None  # True: stay where we are (no map, or stuck for good)
        self.bought = False
        self.alert = None  # (world yaw, until game time): a sound or hit to look towards
        self.bomb = None  # where we saw the planted bomb
        self.trigger = 0  # ticks on target so far, an index into the trigger pattern
        self.busy = False  # holding the button of a plant or defuse: let go and it starts over
        self.in_jump = False  # our jump is still in the air
        self.carried, self.planted_at = False, None  # T: had the bomb; game time our plant ended
        self.search, self.searched = None, set()  # CT: the site we look for the bomb at, and done
        self.beep_guess = None  # CT: (x, y) where the last beep came from, roughly
        self.doing = ""
        score = f"{msg.score.own}:{msg.score.enemy}"
        self.log(f"round {msg.number} as {msg.side} ({score}), heading for site {self.site}")

    def on_tick(self, obs: Observation) -> Action | None:
        me = obs.self
        if not me.alive or self.side is None:
            return None  # a dead player's actions are ignored, but every tick needs an answer
        self.notice(obs)
        self.next_goal(obs)
        enemy = min(obs.visible_enemies, key=lambda e: e.distance, default=None)
        if enemy is not None and best_gun(me) == "knife" and enemy.distance > KNIFE_RANGE:
            enemy = None  # no gun with ammo left: out of the knife's reach it is no fight
        can_plant = self.side == "T" and me.has_c4 and me.in_bomb_site
        near_bomb = self.bomb is not None and dist2d(me.pos, self.bomb) <= DEFUSE_RANGE
        can_defuse = self.side == "CT" and near_bomb
        # Letting go of a plant or defuse starts it over: once started, only a hit stops it.
        keep_on = self.busy and not any(e.kind == "damaged_by" for e in obs.events)
        self.busy = False
        if can_plant and (keep_on or enemy is None):
            action = self.plant(me)
        elif can_defuse and (keep_on or enemy is None):
            action = self.defuse(me)
        elif enemy is not None:
            action = self.fight(me, enemy)
        else:
            action = self.walk_or_hold(obs)
        if enemy is None:
            self.trigger = 0  # the next enemy starts a fresh burst
        action.buy = self.shopping_list(obs)
        return action

    # --- what we know ---------------------------------------------------------------------

    def notice(self, obs: Observation) -> None:
        """Remember the bomb if we see it planted; turn towards sounds and hits for a while."""
        if obs.bomb and obs.bomb.state == "planted" and self.bomb is None:
            self.bomb = obs.bomb.pos
            self.log(f"bomb seen at {self.place(self.bomb) or fmt(self.bomb)}")
            if self.side == "CT":  # go there, even if we had given up our route
                self.go(self.bomb, "the bomb")
        # A bomb beep says nothing new after the plant, unless we are a CT still looking for the
        # bomb and it is near: then it shows where to look.
        looking = self.side == "CT" and self.bomb is None
        sounds = [
            s
            for s in obs.sounds
            if s.kind != "bomb_beep" or (looking and s.distance_band == "near")
        ]
        if sounds:
            nearest = min(sounds, key=lambda s: ("near", "mid", "far").index(s.distance_band))
            self.set_alert(obs, nearest.yaw, f"heard {nearest.kind} ({nearest.distance_band})")
        for event in obs.events:
            if event.kind == "damaged_by":  # being hit beats any sound
                self.set_alert(obs, event.yaw, "hit")

    def set_alert(self, obs: Observation, yaw: float, why: str) -> None:
        if self.alert is None or self.alert[1] < obs.time:
            self.log(f"{why}: looking at yaw {yaw:.0f}")
        self.alert = (yaw, obs.time + ALERT_S)

    def place(self, pos) -> str | None:
        return self.map.place_of(pos) if self.map else None

    def next_goal(self, obs: Observation) -> None:
        """A T leaves its planted bomb in time; a CT looks for a planted bomb it has not seen."""
        me = obs.self
        if self.map is None:
            return
        if self.side == "T":
            self.carried = self.carried or me.has_c4
            planted = self.carried and not me.has_c4 and obs.round.bomb_planted
            if planted and self.planted_at is None:
                self.planted_at = obs.time  # our plant has just finished
            blow = None if self.planted_at is None else self.planted_at + self.hello.match.c4_timer
            if blow is not None and obs.time >= blow - LEAVE_S and self.goal != "spawn":
                self.log(f"the bomb goes off in {LEAVE_S} s: back to spawn")
                self.go(self.map.spawns["T"][0], "spawn")
        elif obs.round.bomb_planted and self.bomb is None:
            beep = next((s for s in obs.sounds if s.kind == "bomb_beep"), None)
            if beep:  # that way, about as far as its band says
                d, yaw = BEEP_DISTANCE[beep.distance_band], math.radians(beep.yaw)
                self.beep_guess = (me.pos[0] + d * math.cos(yaw), me.pos[1] + d * math.sin(yaw))
            if self.search and (self.holding or self.route.next_point(me.pos) is None):
                self.searched.add(self.search)  # there (or cannot get there), and no bomb in sight
            if self.beep_guess:  # a beep says more than where we have looked: the site nearest it
                left, near = list(self.map.bombsites), self.beep_guess
            elif self.search is None or self.search in self.searched:  # the nearest one not seen
                left = [s for s in self.map.bombsites if s not in self.searched]
                if not left:  # looked everywhere: start over
                    self.searched.clear()
                    left = list(self.map.bombsites)
                near = me.pos
            else:
                return  # on our way there
            site = min(left, key=lambda s: dist2d(self.map.bombsite_center(s), near))
            if site != self.search:
                self.log(f"bomb planted, not seen: looking at site {site}")
                self.search = self.site = site
                self.go(self.map.bombsite_center(site), f"site {site}")

    # --- what we do -----------------------------------------------------------------------

    def fight(self, me: SelfState, enemy: VisibleEnemy) -> Action:
        """Stand still (moving ruins accuracy), aim at the upper body, fire when on target."""
        self.say(f"fight {enemy.id} at {enemy.distance:.0f} u")
        # Halfway between origin and head: a bigger target than the head. `angle_to` works for
        # any point; for the head itself `enemy.rel_yaw` / `rel_pitch` give the same angles.
        dyaw, dpitch = angle_to(me, midpoint(enemy.pos, enemy.head_pos))
        # `look` is applied before the shot, so if this tick's turn fits in the limit, the
        # sight is on the target when the trigger is pulled.
        on_target = abs(dyaw) <= self.turn_limit and abs(dpitch) <= self.turn_limit
        # A gun being drawn cannot fire yet (and with the c4 in hand, attack would plant).
        weapon = self.switch_to(me, best_gun(me))
        fire = on_target and weapon is None and self.pull_trigger(me)
        return Action(
            look=Look(dyaw=dyaw, dpitch=dpitch),
            buttons=["attack"] if fire else [],
            weapon=weapon,
        )

    def pull_trigger(self, me: SelfState) -> bool:
        pattern = PISTOL_TRIGGER if active_slot(me) == 2 else RIFLE_TRIGGER
        fire = pattern[self.trigger % len(pattern)]
        self.trigger += 1
        return fire

    def plant(self, me: SelfState) -> Action:
        """Bomb in hand, stand still and hold attack for the 3 s plant (letting go cancels it)."""
        self.say("planting")
        if me.active_weapon != "c4":
            return Action(weapon="c4")
        self.busy = True
        return Action(buttons=["attack"])

    def defuse(self, me: SelfState) -> Action:
        """Next to the bomb: look at it and hold `use` (10 s, 5 s with a kit)."""
        self.say("defusing")
        self.busy = True
        dyaw, dpitch = angle_to(me, self.bomb)
        return Action(look=Look(dyaw=dyaw, dpitch=dpitch), buttons=["use"])

    def go(self, pos, goal: str) -> None:
        """Walk the nav route to `pos` from now on (straight there without a map); `goal` names
        it in the log."""
        self.route = PathFollower(self.map, pos) if self.map and pos else None
        self.goal, self.holding, self.watch = goal, False, None  # watch: found on arrival
        self.anchor, self.stuck = None, 0  # where we last got somewhere, and ticks since

    def walk_or_hold(self, obs: Observation) -> Action:
        """Follow the route; once there, or stuck for good, watch the way enemies come in."""
        me = obs.self
        point = None
        if not self.holding:
            point = self.route.next_point(me.pos) if self.route else None
            if point is None and self.side == "CT" and self.bomb:
                point = self.bomb  # the bomb can lie just off the nav mesh: walk the last bit
        # Pushing on without getting anywhere: a jump now and then gets us over a corner; if that
        # does not help either, the route cannot be walked from here.
        pushing = point is not None and obs.round.phase != "freeze"
        if not pushing or self.anchor is None or dist2d(me.pos, self.anchor) > PROGRESS:
            self.anchor, self.stuck = me.pos, 0
        else:
            self.stuck += 1
        if self.stuck >= GIVE_UP_TICKS:
            self.log(f"stuck at {fmt(me.pos)}: holding here")
            self.holding, point = True, None
        if point is not None:
            self.say(f"walk to {self.goal}, now in {self.place(me.pos) or 'an unnamed place'}")
            look_yaw = yaw_to(me, point)  # look where we go
        else:
            self.say("hold here" if self.holding else f"hold {self.goal}")
            if self.watch is None and self.map:
                self.watch = self.entrance(me)
            look_yaw = yaw_to(me, self.watch) if self.watch else me.yaw
        if self.alert and obs.time <= self.alert[1]:
            look_yaw = self.alert[0]  # check the noise; the move keeps us on the route meanwhile
        dyaw = wrap180(look_yaw - me.yaw)
        # The arena turns first, then moves: aim the move with the view we will have by then.
        turned = me.yaw + max(-self.turn_limit, min(self.turn_limit, dyaw))
        move = Move() if point is None else move_towards(me, point, yaw=turned)
        buttons = []
        clip = active_clip(me)
        if clip is not None and clip[0] == 0 and clip[1] > 0:
            buttons.append("reload")  # nobody in sight: a safe moment
        if not me.on_ground and self.in_jump:
            buttons.append("duck")  # in the air this pulls the feet up 18 u: the jump clears more
        elif point is not None and me.on_ground and not self.in_jump:  # let go between jumps
            stuck = self.stuck and self.stuck % STUCK_TICKS == 0
            if stuck or self.jump_area(me, point):
                buttons.append("jump")
        self.in_jump = "jump" in buttons or (self.in_jump and not me.on_ground)
        return Action(
            move=move,
            look=Look(dyaw=dyaw, dpitch=-me.pitch),  # and level the view
            buttons=buttons,
            weapon=self.switch_to(me, best_gun(me)),
        )

    def jump_area(self, me: SelfState, point) -> bool:
        """Whether the route point ahead is close and lies in a jump area."""
        if self.map is None or dist2d(me.pos, point) > JUMP_RANGE:
            return False
        area = self.map.area_at(point)
        return area is not None and bool(area.flags & JUMP_AREA)

    def entrance(self, me: SelfState):
        """Where enemies come in: the first point of the nav path to their spawn that is
        outside our bomb site."""
        spawn = self.map.spawns[self.enemy_side][0]
        lo, hi = self.map.bombsites[self.site]
        for area in self.map.path(me.pos, spawn) or []:
            x, y, _ = area.center
            if not (lo[0] <= x <= hi[0] and lo[1] <= y <= hi[1]):
                return area.center
        return spawn

    def shopping_list(self, obs: Observation) -> list[str]:
        """Once a round, on the first tick we may buy: armor on a pistol round; a rifle and
        armor (a CT also a defuse kit) when we can afford them; otherwise save. Ammo with every
        gun: a bought gun comes with one magazine, so its ammo is bought right after it, and
        both guns are topped up every round."""
        me = obs.self
        if self.bought or not me.can_buy or self.hello is None:
            return []  # without `hello` we do not know which rounds are pistol rounds
        self.bought = True
        half = self.hello.match.max_rounds // 2
        rifle = next((w.name for w in me.weapons if w.slot == 1), None)
        wish = []
        if obs.round.number in (1, half + 1):  # pistol rounds: everyone starts with $800
            wish = ["vest"]
        elif me.money >= RIFLE_MONEY or rifle:
            if rifle is None:  # the best rifle that still leaves money for its ammo and a vest
                cost = {r: PRICE[r] + ammo_price(r) + PRICE["vest"] for r in RIFLES[self.side]}
                fits = [r for r in RIFLES[self.side] if cost[r] <= me.money]
                rifle = fits[0] if fits else RIFLES[self.side][-1]
                wish.append(rifle)
            wish.append("primammo")
            if me.armor < 100:
                wish.append("vesthelm")
            if self.side == "CT" and me.money >= DEFUSER_MONEY and not me.has_defuser:
                wish.append("defuser")
        wish.append("secammo")
        price = PRICE | {"primammo": ammo_price(rifle)}
        items, money = [], me.money
        for item in wish:  # in order while the money lasts; vesthelm falls back to a vest
            if item == "vesthelm" and price[item] > money:
                item = "vest"
            if price[item] <= money or (item.endswith("ammo") and money > 0):  # ammo: what we can
                items.append(item)
                money -= min(price[item], money)
        if items:
            self.log(f"buy {items} with ${me.money}")
        return items

    # --- small helpers --------------------------------------------------------------------

    def switch_to(self, me: SelfState, weapon: str | None) -> str | None:
        """The `weapon` field: only when it changes something."""
        return weapon if weapon and weapon != me.active_weapon else None

    def say(self, doing: str) -> None:
        """Log what we are doing when it changes (not every tick)."""
        if doing != self.doing:
            self.doing = doing
            self.log(doing)


def ammo_price(rifle: str | None) -> int:
    """What filling the rifle's reserve costs."""
    return PRIMAMMO.get(rifle, PRICE["primammo"])


def best_gun(me: SelfState) -> str:
    """The rifle if we have one with ammo, else the pistol, else the knife."""
    guns = [w for w in me.weapons if w.slot in (1, 2) and (w.clip or w.reserve)]
    return min(guns, key=lambda w: w.slot).name if guns else "knife"


def active_slot(me: SelfState) -> int | None:
    return next((w.slot for w in me.weapons if w.name == me.active_weapon), None)


def active_clip(me: SelfState) -> tuple[int, int] | None:
    """(clip, reserve) of the weapon in hand; None for the knife, grenades and the bomb."""
    w = next((w for w in me.weapons if w.name == me.active_weapon), None)
    return None if w is None or w.clip is None else (w.clip, w.reserve)


def yaw_to(me: SelfState, pos) -> float:
    return math.degrees(math.atan2(pos[1] - me.pos[1], pos[0] - me.pos[0]))


def dist2d(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def midpoint(a, b):
    return tuple((x + y) / 2 for x, y in zip(a, b, strict=True))


def fmt(pos) -> str:
    return "(" + ", ".join(f"{v:.0f}" for v in pos) + ")"


if __name__ == "__main__":
    run(ReferenceBot())
