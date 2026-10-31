/**
 * How fast the room draws, measured in the room itself: frames per second
 * over the last couple of seconds, the slowest frames, and what each frame
 * costs the GPU (draw calls, triangles). Shown on the Room panel with
 * `?perf`, so anyone running it on a headset can read it there.
 *
 * Pure: frame durations in, numbers out.
 */

/** Frames kept: about two seconds at 72 or 90 Hz. */
const WINDOW = 180;

export interface FrameReport {
  fps: number;
  /** The 95th percentile frame time, milliseconds: the stutter a person feels. */
  p95Ms: number;
  /** Share of frames slower than the target, 0..1. */
  slow: number;
}

export class FrameStats {
  private frames: number[] = [];

  constructor(private readonly targetFps = 72) {}

  /** Record one frame's duration, in seconds as the render loop reports it. */
  add(deltaS: number): void {
    if (!(deltaS > 0) || deltaS > 1) return; // a paused tab is not a slow frame
    this.frames.push(deltaS * 1000);
    if (this.frames.length > WINDOW) this.frames.shift();
  }

  report(): FrameReport | undefined {
    const n = this.frames.length;
    if (n < 10) return undefined;
    const total = this.frames.reduce((a, b) => a + b, 0);
    const sorted = [...this.frames].sort((a, b) => a - b);
    const budget = 1000 / this.targetFps;
    return {
      fps: (n * 1000) / total,
      p95Ms: sorted[Math.min(n - 1, Math.floor(n * 0.95))],
      slow: this.frames.filter((f) => f > budget * 1.1).length / n,
    };
  }
}

/** What the room may cost per frame; far under what a Quest 3 draws at 72 Hz. */
export const RENDER_BUDGET = { drawCalls: 200, triangles: 150_000 };

/** One line for the Room panel. */
export function perfLine(r: FrameReport | undefined, calls: number, triangles: number): string {
  const cost = `${calls} draw calls, ${Math.round(triangles / 1000)}k triangles`;
  if (!r) return `Measuring... ${cost}`;
  return `${Math.round(r.fps)} fps, p95 ${r.p95Ms.toFixed(1)} ms, ${Math.round(r.slow * 100)}% slow. ${cost}`;
}
