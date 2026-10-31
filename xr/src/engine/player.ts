/**
 * Plays the demo's scripts on a clock the person controls.
 *
 * The clock only moves in `tick`, so pausing is not dropping frames: a paused
 * player ignores time, and resuming continues exactly where it stopped. The
 * room's state is rebuilt from the events emitted so far, never edited, so a
 * restart is the initial state again.
 */

import type { Cue, DemoTask } from '../demo/scenario';
import { initialState, reduce, type RoomEvent, type RoomState } from '../model';

interface Pending {
  at: number;
  event: RoomEvent;
}

export class Player {
  private clock = 0;
  private queue: Pending[] = [];
  private emitted: RoomEvent[] = [];
  private _state: RoomState;
  private _paused = false;
  /** Launched tasks, so a second pinch before the first frame does nothing. */
  private launched = new Set<string>();

  constructor(private readonly tasks: DemoTask[]) {
    this._state = initialState(tasks);
  }

  get state(): RoomState {
    return this._state;
  }

  get paused(): boolean {
    return this._paused;
  }

  /** Milliseconds of demo time elapsed, paused time excluded. */
  get elapsed(): number {
    return this.clock;
  }

  /** True while any task has events still to come. */
  get busy(): boolean {
    return this.queue.length > 0;
  }

  /** Launch a task. A task that already ran, or is running, is not launched twice. */
  launch(taskId: string): boolean {
    const task = this.tasks.find((t) => t.id === taskId);
    if (!task || this.launched.has(taskId)) return false;
    this.launched.add(taskId);
    this.schedule(task.script);
    return true;
  }

  /**
   * Record a person's decision on the delivery waiting for one. A rejection
   * sends the task back, and its rework plays out.
   */
  decide(taskId: string, approved: boolean, reason = ''): boolean {
    const task = this.tasks.find((t) => t.id === taskId);
    if (!task || this._state.tasks[taskId].state !== 'waiting_for_person') return false;
    this.emit({ type: 'decision', taskId, approved, reason });
    if (!approved && task.rework) this.schedule(task.rework);
    return true;
  }

  /**
   * Apply an event from outside the scripts (live mode). While paused it
   * waits, and comes in on resume like everything else.
   */
  ingest(event: RoomEvent): void {
    if (this._paused) this.queue.push({ at: this.clock, event });
    else this.emit(event);
  }

  pause(): void {
    this._paused = true;
  }

  resume(): void {
    this._paused = false;
  }

  restart(): void {
    this.clock = 0;
    this.queue = [];
    this.emitted = [];
    this.launched.clear();
    this._state = initialState(this.tasks);
  }

  /** Advance the clock by `dtMs` and emit what came due. Returns how many events. */
  tick(dtMs: number): number {
    if (this._paused || dtMs <= 0) return 0;
    this.clock += dtMs;
    let count = 0;
    while (this.queue.length > 0 && this.queue[0].at <= this.clock) {
      this.emit(this.queue.shift()!.event);
      count += 1;
    }
    return count;
  }

  /** Every event emitted so far, oldest first. */
  history(): readonly RoomEvent[] {
    return this.emitted;
  }

  private schedule(cues: Cue[]): void {
    const base = this.clock;
    this.queue.push(...cues.map((c) => ({ at: base + c.at, event: c.event })));
    // Stable: cues at the same time keep their script order.
    this.queue.sort((a, b) => a.at - b.at);
  }

  private emit(event: RoomEvent): void {
    this.emitted.push(event);
    this._state = reduce(this._state, event);
  }
}
