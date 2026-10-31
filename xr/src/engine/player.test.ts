import { describe, expect, it } from 'vitest';
import { DEMO_TASKS } from '../demo/scenario';
import { awaitingDecision } from '../model';
import { Player } from './player';

const end = (taskId: string, part: 'script' | 'rework' = 'script') =>
  Math.max(...DEMO_TASKS.find((t) => t.id === taskId)![part]!.map((c) => c.at));

describe('Player', () => {
  it('starts with every task queued and every agent idle', () => {
    const p = new Player(DEMO_TASKS);
    expect(Object.values(p.state.tasks).every((t) => t.state === 'queued')).toBe(true);
    expect(Object.values(p.state.agents).every((a) => a.state === 'idle')).toBe(true);
  });

  it('plays a high-risk task until it waits for a person', () => {
    const p = new Player(DEMO_TASKS);
    p.launch('reset');
    p.tick(5000);
    expect(p.state.agents.Architect.state).toBe('done');
    p.tick(end('reset'));
    expect(p.state.tasks.reset.state).toBe('waiting_for_person');
    expect(awaitingDecision(p.state)?.delivery?.risk).toBe('high');
  });

  it('ignores time while paused and continues where it stopped', () => {
    const p = new Player(DEMO_TASKS);
    p.launch('reset');
    p.tick(1000);
    p.pause();
    expect(p.tick(60_000)).toBe(0);
    expect(p.elapsed).toBe(1000);
    p.resume();
    p.tick(end('reset'));
    expect(p.state.tasks.reset.state).toBe('waiting_for_person');
  });

  it('closes a task when a person approves it', () => {
    const p = new Player(DEMO_TASKS);
    p.launch('reset');
    p.tick(end('reset'));
    expect(p.decide('reset', true)).toBe(true);
    expect(p.state.tasks.reset.state).toBe('done');
    expect(p.state.tasks.reset.decision).toEqual({ approved: true, reason: '' });
    expect(awaitingDecision(p.state)).toBeUndefined();
  });

  it('plays the rework when a person sends it back, then asks again', () => {
    const p = new Player(DEMO_TASKS);
    p.launch('reset');
    p.tick(end('reset'));
    p.decide('reset', false, 'add a reused-token test');
    expect(p.state.tasks.reset.state).toBe('sent_back');
    p.tick(end('reset', 'rework'));
    expect(p.state.tasks.reset.state).toBe('waiting_for_person');
    expect(p.state.tasks.reset.delivery?.runId).toBe('run-42');
  });

  it('refuses a decision on a task that is not waiting for one', () => {
    const p = new Player(DEMO_TASKS);
    expect(p.decide('reset', true)).toBe(false);
    p.launch('csv');
    p.tick(end('csv'));
    expect(p.state.tasks.csv.state).toBe('done');
    expect(p.decide('csv', true)).toBe(false);
  });

  it('launches a task once', () => {
    const p = new Player(DEMO_TASKS);
    expect(p.launch('ci')).toBe(true);
    expect(p.launch('ci')).toBe(false);
    expect(p.launch('nope')).toBe(false);
  });

  it('restarts to the initial state', () => {
    const p = new Player(DEMO_TASKS);
    p.launch('ci');
    p.tick(end('ci'));
    p.restart();
    expect(p.state.tasks.ci.state).toBe('queued');
    expect(p.history()).toHaveLength(0);
    expect(p.busy).toBe(false);
  });

  it('runs the whole demo in under ten minutes', () => {
    const p = new Player(DEMO_TASKS);
    for (const t of DEMO_TASKS) p.launch(t.id);
    let ms = 0;
    while (p.busy && ms < 600_000) {
      p.tick(500);
      ms += 500;
    }
    expect(ms).toBeLessThan(600_000);
    expect(p.state.tasks.csv.state).toBe('done');
  });

  it('applies live events at once, and holds them while paused', () => {
    const p = new Player([{ id: 'live', title: 'Sprint 7', summary: '', script: [] }]);
    const event = { type: 'agent_start', role: 'Developer', agent: 'Dev', message: 'Writing', taskId: 'live' } as const;
    p.ingest(event);
    expect(p.state.agents.Developer.state).toBe('working');
    p.pause();
    p.ingest({ ...event, type: 'agent_complete', message: 'Delivered' });
    expect(p.state.agents.Developer.state).toBe('working');
    p.resume();
    p.tick(16);
    expect(p.state.agents.Developer.state).toBe('done');
  });
});
