import { describe, expect, it } from 'vitest';

import { DEMO_TASKS } from './demo/scenario';
import { cueFor, ROLE_NOTE } from './sound';

describe('cueFor', () => {
  it('gives each agent its own sound when it starts and finishes', () => {
    expect(cueFor({ type: 'agent_start', role: 'QA', agent: 'Quinn', message: '', taskId: 't' })).toEqual({ kind: 'start', role: 'QA' });
    expect(cueFor({ type: 'agent_complete', role: 'Developer', agent: 'Dev', message: '', taskId: 't' })).toEqual({ kind: 'done', role: 'Developer' });
  });

  it('rings a seal for each of the Verifier observations', () => {
    expect(cueFor({ type: 'status', role: 'Verifier', agent: 'Verifier', message: 'files_written: verified', taskId: 't' })).toEqual({
      kind: 'seal',
      role: 'Verifier',
    });
    expect(cueFor({ type: 'agent_complete', role: 'Verifier', agent: 'Verifier', message: 'tests_run', taskId: 't' })?.kind).toBe('seal');
  });

  it('calls the person when a delivery waits, and answers the decision', () => {
    expect(cueFor({ type: 'task_state', taskId: 't', state: 'waiting_for_person' })).toEqual({ kind: 'waiting' });
    expect(cueFor({ type: 'task_state', taskId: 't', state: 'in_review' })).toBeUndefined();
    expect(cueFor({ type: 'decision', taskId: 't', approved: true, reason: '' })).toEqual({ kind: 'approve' });
    expect(cueFor({ type: 'decision', taskId: 't', approved: false, reason: '' })).toEqual({ kind: 'reject' });
  });

  it('marks the close of a sprint, and keeps other chatter silent', () => {
    expect(
      cueFor({ type: 'message', role: 'ScrumMaster', agent: 'Sam', message: 'Sprint 2 closed: 0 rework on 3 tasks.', taskId: 't' }),
    ).toEqual({ kind: 'sprint', role: 'ScrumMaster' });
    expect(cueFor({ type: 'status', role: 'Developer', agent: 'Dev', message: 'Declared 2 files', taskId: 't' })).toBeUndefined();
    expect(cueFor({ type: 'status', role: 'System', agent: 'Risk tier', message: 'held', taskId: 't' })).toBeUndefined();
  });

  it('the agents are told apart by ear: five different notes', () => {
    expect(new Set(Object.values(ROLE_NOTE)).size).toBe(5);
  });

  it('a whole demo task is not a wall of sound: at most one cue a second on average', () => {
    const reset = DEMO_TASKS[0];
    const cues = reset.script.filter((c) => cueFor(c.event)).length;
    const seconds = reset.script[reset.script.length - 1].at / 1000;
    expect(cues / seconds).toBeLessThanOrEqual(1);
  });
});
