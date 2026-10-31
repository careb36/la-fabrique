import { describe, expect, it } from 'vitest';
import { DEMO_TASKS } from './demo/scenario';
import { Player } from './engine/player';
import { awaitingDecision, initialState, reduce, tokenAt } from './model';

const at = (p: Player, ms: number) => {
  p.tick(ms - p.elapsed);
  return tokenAt(p.state);
};

describe('tokenAt', () => {
  it('is nowhere before any task starts', () => {
    expect(tokenAt(new Player(DEMO_TASKS).state)).toBe('none');
  });

  it('follows the task from agent to agent, then lands at the result', () => {
    const p = new Player(DEMO_TASKS);
    p.launch('reset');
    expect(at(p, 1000)).toBe('Architect');
    expect(at(p, 6000)).toBe('Developer');
    expect(at(p, 15000)).toBe('Verifier');
    expect(at(p, 22000)).toBe('QA');
    expect(at(p, 28000)).toBe('result');
  });

  it('collects the Verifier seals on the way, three once delivered', () => {
    const p = new Player(DEMO_TASKS);
    p.launch('reset');
    p.tick(13500);
    expect(p.state.seals).toBe(0);
    p.tick(4000);
    expect(p.state.seals).toBe(1);
    p.tick(11000);
    expect(p.state.seals).toBe(3);
  });

  it('starts a rework with no seals', () => {
    const p = new Player(DEMO_TASKS);
    p.launch('reset');
    p.tick(28000);
    p.decide('reset', false);
    p.tick(2000);
    expect(tokenAt(p.state)).toBe('Developer');
    expect(p.state.seals).toBe(0);
  });
});

describe('the result panel keeps what waits for the person', () => {
  const delivery = (runId: string) => ({ runId, files: [], checks: [], risk: 'low' as const, riskReason: '' });
  const two = () => initialState([{ id: 'ci', title: 'CI' }, { id: 'csv', title: 'CSV' }]);

  it('another task delivering does not take the panel from a delivery that waits', () => {
    let s = reduce(two(), { type: 'delivery', taskId: 'ci', delivery: delivery('run-44') });
    s = reduce(s, { type: 'task_state', taskId: 'ci', state: 'waiting_for_person' });
    s = reduce(s, { type: 'delivery', taskId: 'csv', delivery: delivery('run-43') });
    expect(s.focus).toBe('ci');
    expect(awaitingDecision(s)?.id).toBe('ci');
  });

  it('a delivery that comes to wait after another took the panel gets it back', () => {
    let s = reduce(two(), { type: 'delivery', taskId: 'ci', delivery: delivery('run-44') });
    s = reduce(s, { type: 'delivery', taskId: 'csv', delivery: delivery('run-43') });
    expect(s.focus).toBe('csv');
    s = reduce(s, { type: 'task_state', taskId: 'ci', state: 'waiting_for_person' });
    expect(awaitingDecision(s)?.id).toBe('ci');
  });

  it('once decided, the panel moves to the next delivery that waits', () => {
    let s = two();
    for (const id of ['ci', 'csv']) {
      s = reduce(s, { type: 'delivery', taskId: id, delivery: delivery(id) });
      s = reduce(s, { type: 'task_state', taskId: id, state: 'waiting_for_person' });
    }
    expect(s.focus).toBe('ci');
    s = reduce(s, { type: 'decision', taskId: 'ci', approved: true, reason: '' });
    expect(awaitingDecision(s)?.id).toBe('csv');
  });
});
