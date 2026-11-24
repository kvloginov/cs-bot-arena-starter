// Minimal CS 1.6 Bot Arena bot in TypeScript. Run: node bot.ts (Node 24+, no packages).
// Runs at the nearest visible enemy, else to the enemy spawn, and shoots when aimed.
import { createInterface } from "node:readline";
import type { Action, Side, Tick, Vec3, VisibleEnemy } from "./protocol.ts";
import type { Incoming } from "./protocol.ts";

const MAX_TURN = 36; // degrees per tick: max_turn_rate_dps 720 / tick_hz 20
const AIM = 3; // fire when the enemy is within this many degrees of the crosshair

const wrap180 = (d: number) => ((((d + 180) % 360) + 360) % 360) - 180;
const clamp = (v: number, lim: number) => Math.max(-lim, Math.min(lim, v));

let side: Side = "T";
let spawns: Record<Side, Vec3[]> = { T: [], CT: [] };
let fired = false; // fired last tick: pistols need a released tick between shots

function onTick({ obs }: Tick): Action {
  const me = obs.self;
  const action: Action = {
    type: "action",
    tick: obs.tick,
    move: { forward: 0, side: 0 },
    look: { dyaw: 0, dpitch: 0 },
    buttons: [],
  };
  if (!me.alive) return action; // dead players still answer every tick

  let enemy: VisibleEnemy | null = null;
  for (const e of obs.visible_enemies) if (!enemy || e.distance < enemy.distance) enemy = e;

  let dyaw = 0;
  if (enemy) {
    dyaw = enemy.rel_yaw;
    action.look.dpitch = clamp(enemy.rel_pitch, MAX_TURN);
  } else {
    const goal = spawns[side === "T" ? "CT" : "T"][0]; // head for the enemy spawn
    if (goal) {
      const want = (Math.atan2(goal[1] - me.pos[1], goal[0] - me.pos[0]) * 180) / Math.PI;
      dyaw = wrap180(want - me.yaw);
    }
  }
  action.look.dyaw = clamp(dyaw, MAX_TURN);
  action.move.forward = 1; // `look` is applied before `move`: we walk the turned direction

  const aimed = enemy && Math.abs(enemy.rel_yaw) < AIM && Math.abs(enemy.rel_pitch) < AIM;
  if (aimed && !fired) action.buttons.push("attack");
  fired = action.buttons.length > 0;
  return action;
}

for await (const line of createInterface({ input: process.stdin })) {
  if (!line.trim()) continue;
  const msg: Incoming = JSON.parse(line);
  if (msg.type === "hello") {
    side = msg.side;
    spawns = msg.map.spawns;
    console.error(`hello ${msg.player_id} as ${side}`); // stdout is for protocol lines only
    console.log(JSON.stringify({ type: "ready" }));
  } else if (msg.type === "round_start") {
    side = msg.side;
  } else if (msg.type === "tick") {
    console.log(JSON.stringify(onTick(msg)));
  }
}
