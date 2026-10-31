import { describe, expect, it } from 'vitest';
import { DEMO_TASKS } from './demo/scenario';
import { Player } from './engine/player';
import { tokenAt } from './model';

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
