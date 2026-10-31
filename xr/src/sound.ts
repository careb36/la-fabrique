/**
 * The room's sounds: short synthesized tones, no audio files. Each comes
 * from where it happens, so a person hears which agent finished without
 * looking: the agents' tones from their lights on the wall, the delivery's
 * from the result panel.
 *
 * `cueFor` is pure (an event in, a cue out); `Sound` plays cues with Web
 * Audio, each through a panner at the cue's place.
 */

import type { Role, RoomEvent } from './model';

export type CueKind = 'start' | 'done' | 'seal' | 'waiting' | 'approve' | 'reject' | 'error' | 'sprint';

export interface SoundCue {
  kind: CueKind;
  /** The agent it comes from; none for the delivery and the sprint. */
  role?: Role;
}

/** Each agent's own note, Hz: a person learns who is who by ear. */
export const ROLE_NOTE: Record<Role, number> = {
  Architect: 440,
  Developer: 330,
  QA: 523.25,
  Verifier: 659.25,
  ScrumMaster: 392,
};

/** The sound an event makes, if any. */
export function cueFor(event: RoomEvent): SoundCue | undefined {
  switch (event.type) {
    case 'agent_start':
      return { kind: 'start', role: event.role };
    case 'agent_complete':
      return { kind: event.role === 'Verifier' ? 'seal' : 'done', role: event.role };
    case 'status':
    case 'message':
      if (event.role === 'Verifier') return { kind: 'seal', role: 'Verifier' };
      if (event.role === 'ScrumMaster' && /^Sprint \d+ closed/.test(event.message)) return { kind: 'sprint', role: 'ScrumMaster' };
      return undefined;
    case 'error':
      return event.role === 'System' ? { kind: 'error' } : { kind: 'error', role: event.role };
    case 'task_state':
      return event.state === 'waiting_for_person' ? { kind: 'waiting' } : undefined;
    case 'decision':
      return { kind: event.approved ? 'approve' : 'reject' };
    case 'delivery':
      return undefined;
  }
}

/** Notes of each cue as [frequency ratio to the base, start s, length s]. */
const SHAPES: Record<CueKind, [number, number, number][]> = {
  start: [[1, 0, 0.09]],
  done: [
    [1, 0, 0.1],
    [1.5, 0.09, 0.16],
  ],
  seal: [[2, 0, 0.12]],
  waiting: [
    [1, 0, 0.35],
    [1.25, 0.18, 0.4],
  ],
  approve: [
    [1, 0, 0.3],
    [1.25, 0.07, 0.3],
    [1.5, 0.14, 0.4],
  ],
  reject: [
    [1.2, 0, 0.16],
    [0.9, 0.15, 0.26],
  ],
  error: [[0.5, 0, 0.25]],
  sprint: [
    [1, 0, 0.14],
    [1.25, 0.12, 0.14],
    [1.5, 0.24, 0.14],
    [2, 0.36, 0.35],
  ],
};

/** The base note of cues that are not an agent's: the delivery and the sprint. */
const ROOM_NOTE = 523.25;

export interface At {
  x: number;
  y: number;
  z: number;
}

/**
 * Plays cues through Web Audio. Created silent; `unlock` (from a person's
 * gesture, as browsers require) starts the audio context.
 */
export class Sound {
  muted = false;
  private ctx?: AudioContext;
  private out?: GainNode;

  /** Start the audio context; call from a click, a pinch or entering XR. */
  unlock(): void {
    if (this.ctx) {
      void this.ctx.resume();
      return;
    }
    const Ctor = (globalThis as unknown as { AudioContext?: typeof AudioContext }).AudioContext;
    if (!Ctor) return;
    this.ctx = new Ctor();
    this.out = this.ctx.createGain();
    this.out.gain.value = 0.25;
    this.out.connect(this.ctx.destination);
  }

  /** Where the listener's head is and which way it faces. */
  listen(at: At, forward: At, up: At): void {
    const l = this.ctx?.listener;
    if (!l) return;
    if (l.positionX) {
      l.positionX.value = at.x;
      l.positionY.value = at.y;
      l.positionZ.value = at.z;
      l.forwardX.value = forward.x;
      l.forwardY.value = forward.y;
      l.forwardZ.value = forward.z;
      l.upX.value = up.x;
      l.upY.value = up.y;
      l.upZ.value = up.z;
    } else {
      l.setPosition(at.x, at.y, at.z);
      l.setOrientation(forward.x, forward.y, forward.z, up.x, up.y, up.z);
    }
  }

  /** Play a cue from a place in the room. */
  play(cue: SoundCue, at: At): void {
    const ctx = this.ctx;
    if (!ctx || !this.out || this.muted || ctx.state !== 'running') return;
    const panner = ctx.createPanner();
    panner.panningModel = 'HRTF';
    panner.distanceModel = 'inverse';
    panner.refDistance = 0.5;
    panner.positionX.value = at.x;
    panner.positionY.value = at.y;
    panner.positionZ.value = at.z;
    panner.connect(this.out);
    const base = cue.role ? ROLE_NOTE[cue.role] : ROOM_NOTE;
    const now = ctx.currentTime;
    let end = now;
    for (const [ratio, start, length] of SHAPES[cue.kind]) {
      const osc = ctx.createOscillator();
      osc.type = cue.kind === 'error' ? 'triangle' : 'sine';
      osc.frequency.value = base * ratio;
      const env = ctx.createGain();
      const t0 = now + start;
      // A soft attack and a long tail: chimes, never beeps.
      env.gain.setValueAtTime(0, t0);
      env.gain.linearRampToValueAtTime(0.5, t0 + 0.012);
      env.gain.exponentialRampToValueAtTime(0.001, t0 + length);
      osc.connect(env).connect(panner);
      osc.start(t0);
      osc.stop(t0 + length + 0.02);
      end = Math.max(end, t0 + length + 0.05);
    }
    setTimeout(() => panner.disconnect(), (end - now) * 1000 + 50);
  }
}
