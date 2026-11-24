// The messages this bot uses, written by hand from schema/protocol.v1.json.
// Fields it does not read are left out; unknown fields are ignored on purpose.
export type Side = "T" | "CT";
export type Vec3 = [number, number, number];

export interface Hello {
  type: "hello";
  player_id: string;
  side: Side;
  map: { spawns: Record<Side, Vec3[]> };
}
export interface RoundStart {
  type: "round_start";
  number: number;
  side: Side;
}
export interface VisibleEnemy {
  id: string;
  distance: number;
  rel_yaw: number; // degrees from the current view to the head, + = left
  rel_pitch: number; // + = up
}
export interface Tick {
  type: "tick";
  obs: {
    tick: number;
    self: { pos: Vec3; yaw: number; alive: boolean };
    visible_enemies: VisibleEnemy[];
  };
}
export type Incoming = Hello | RoundStart | Tick | { type: "round_end" | "match_end" };

export interface Action {
  type: "action";
  tick: number;
  move: { forward: number; side: number };
  look: { dyaw: number; dpitch: number };
  buttons: string[];
}
