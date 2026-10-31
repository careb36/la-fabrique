import { describe, expect, it } from 'vitest';

import { guideStep } from './guide';
import { initialState, reduce } from './model';

const start = () => initialState([{ id: 'a', title: 'A' }, { id: 'b', title: 'B' }]);

describe('guideStep', () => {
  it('starts by showing how to launch', () => {
    expect(guideStep(start(), false)).toBe('launch');
  });

  it('asks to look at an agent while they work, until the person has', () => {
    const s = reduce(start(), { type: 'task_state', taskId: 'a', state: 'in_progress' });
    expect(guideStep(s, false)).toBe('look');
    expect(guideStep(s, true)).toBe('none');
  });

  it('shows how to decide when a delivery waits, looked or not', () => {
    const s = reduce(start(), { type: 'task_state', taskId: 'a', state: 'waiting_for_person' });
    const focused = { ...s, focus: 'a' };
    expect(guideStep(focused, true)).toBe('decide');
  });

  it('is gone once the person has decided', () => {
    let s = reduce(start(), { type: 'task_state', taskId: 'a', state: 'waiting_for_person' });
    s = reduce({ ...s, focus: 'a' }, { type: 'decision', taskId: 'a', approved: false, reason: '' });
    expect(guideStep(s, false)).toBe('none');
  });
});
