/**
 * The agents as presences in the room, and the task as an object in it.
 *
 * Each agent is a small light above its panel, in its own color: still while
 * it waits, breathing while it works, a green flash when it finishes, red on
 * an error. The task is a glowing block that travels to whichever agent has
 * it in hand and then down to the person's result panel, carrying the
 * Verifier's confirmations as green seals that orbit it.
 *
 * Unlit materials and a handful of meshes: cheap enough for 60 fps on Quest.
 */

import { UIKit, UIKitDocument } from '@iwsdk/core';
import {
  AdditiveBlending,
  BoxGeometry,
  Group,
  Mesh,
  MeshBasicMaterial,
  SphereGeometry,
  TorusGeometry,
  Vector3,
} from 'three';

import { MAX_SEALS, type AgentState, type Role } from '../model';
import { COLORS, panel, text } from './kit';

export const ROLE_COLOR: Record<Role, number> = {
  Architect: 0x7dd3fc,
  Developer: 0xff6a45,
  QA: 0xc084fc,
  Verifier: 0xa3e635,
  ScrumMaster: 0xfbbf24,
};

const STATE_COLOR: Partial<Record<AgentState, number>> = { done: 0xa3e635, error: 0xf87171 };

const sphere = new SphereGeometry(1, 20, 14);

function glow(color: number, opacity: number): MeshBasicMaterial {
  return new MeshBasicMaterial({ color, transparent: true, opacity, blending: AdditiveBlending, depthWrite: false });
}

export interface Presence {
  group: Group;
  update(state: AgentState, time: number, changedAt: number): void;
}

/** One agent's light: a core, a halo, and a ring that turns while it works. */
export function presence(role: Role): Presence {
  const group = new Group();
  // The light floats on a pivot of its own, so placing the group never
  // fights the floating.
  const pivot = new Group();
  group.add(pivot);
  const core = new Mesh(sphere, new MeshBasicMaterial({ color: ROLE_COLOR[role] }));
  core.scale.setScalar(0.014);
  const halo = new Mesh(sphere, glow(ROLE_COLOR[role], 0.25));
  halo.scale.setScalar(0.03);
  const ring = new Mesh(new TorusGeometry(0.024, 0.0015, 8, 40), glow(ROLE_COLOR[role], 0.8));
  ring.rotation.x = Math.PI / 2;
  pivot.add(core, halo, ring);
  return {
    group,
    update(state, time, changedAt) {
      const working = state === 'working';
      // Breathing while it works; settled otherwise.
      const breath = working ? 1 + 0.25 * Math.sin(time * 4) : 1;
      halo.scale.setScalar(0.03 * breath);
      (halo.material as MeshBasicMaterial).opacity = working ? 0.45 : 0.18;
      ring.visible = working;
      ring.rotation.z = time * 2.5;
      pivot.position.y = Math.sin(time * 1.3 + ROLE_COLOR[role]) * 0.004;
      // A finish or an error flashes for a second, then the agent's own color.
      const flash = STATE_COLOR[state];
      const recent = time - changedAt < 1;
      (core.material as MeshBasicMaterial).color.setHex(flash && recent ? flash : ROLE_COLOR[role]);
    },
  };
}

export interface Token {
  group: Group;
  /**
   * Glide toward `target` (world space) and show `seals` confirmations.
   * While a hand `held` it, it stays where the hand put it.
   */
  update(target: Vector3 | undefined, seals: number, dt: number, time: number, held?: boolean): void;
}

/** The task in the room: a small glowing block, with the Verifier's seals. */
export function token(): Token {
  const group = new Group();
  const block = new Mesh(new BoxGeometry(0.026, 0.026, 0.026), new MeshBasicMaterial({ color: 0xfff1e8 }));
  const halo = new Mesh(sphere, glow(0xff6a45, 0.35));
  halo.scale.setScalar(0.03);
  const seals = Array.from({ length: MAX_SEALS }, () => {
    const seal = new Mesh(sphere, new MeshBasicMaterial({ color: 0xa3e635 }));
    seal.scale.setScalar(0.0055);
    group.add(seal);
    return seal;
  });
  // A hand aims at something larger than the block itself: an invisible
  // sphere, so a pinch from across the desk still catches it.
  const hit = new Mesh(sphere, new MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false }));
  hit.scale.setScalar(0.05);
  group.add(block, halo, hit);
  group.visible = false;
  return {
    group,
    update(target, sealCount, dt, time, held = false) {
      if (!target) {
        group.visible = false;
        return;
      }
      if (!group.visible) {
        // Appears where it first goes, rather than flying in from the origin.
        group.position.copy(target);
        group.visible = true;
      }
      // Ease toward the agent that holds it: fast, then settling. Released
      // anywhere but a drop zone, it glides back the same way.
      if (!held) group.position.lerp(target, 1 - Math.exp(-dt * 3.5));
      (halo.material as MeshBasicMaterial).opacity = held ? 0.6 : 0.35;
      block.rotation.set(time * 0.7, time, 0);
      seals.forEach((seal, i) => {
        seal.visible = i < sealCount;
        const a = time * 1.6 + (i * Math.PI * 2) / MAX_SEALS;
        seal.position.set(Math.cos(a) * 0.034, Math.sin(a * 0.5) * 0.008, Math.sin(a) * 0.034);
      });
    },
  };
}

export interface DropZone {
  group: Group;
  /** Show or hide it; `near` lights it up while the delivery is over it. */
  update(shown: boolean, near: boolean, time: number): void;
}

/**
 * Where the delivery is dropped to decide: a ring in the decision's color,
 * facing the person, with its name under it.
 */
export function dropZone(label: string, color: number): DropZone {
  const group = new Group();
  const ring = new Mesh(new TorusGeometry(0.045, 0.004, 8, 48), glow(color, 0.85));
  const disc = new Mesh(sphere, glow(color, 0.12));
  disc.scale.set(0.042, 0.042, 0.004);
  const tag = panel(0.11, undefined, 'bottom');
  tag.setProperties({ padding: 0.8, alignItems: 'center', backgroundColor: COLORS.panel });
  tag.add(text(label, 1.6, COLORS.text, true));
  const doc = new UIKitDocument(tag as UIKit.Container);
  // Above the ring, clear of the result panel's title below it.
  doc.position.set(0, 0.075, 0);
  group.add(ring, disc, doc);
  group.visible = false;
  return {
    group,
    update(shown, near, time) {
      group.visible = shown;
      if (!shown) return;
      const pulse = near ? 1.25 : 1 + 0.05 * Math.sin(time * 3);
      ring.scale.setScalar(pulse);
      (disc.material as MeshBasicMaterial).opacity = near ? 0.35 : 0.12;
    },
  };
}
