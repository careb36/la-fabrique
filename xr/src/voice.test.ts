import { describe, expect, it } from 'vitest';

import { parseCommand } from './voice';

const tasks = [
  { id: 'reset', title: 'Password reset endpoint' },
  { id: 'csv', title: 'CSV export of a sprint' },
  { id: 'ci', title: 'Pin the CI runner and actions' },
];

describe('parseCommand', () => {
  it('reads decisions, in English and Spanish', () => {
    expect(parseCommand('Approve', tasks)).toEqual({ kind: 'approve' });
    expect(parseCommand('ship it', tasks)).toEqual({ kind: 'approve' });
    expect(parseCommand('send it back please', tasks)).toEqual({ kind: 'reject' });
    expect(parseCommand('Aprobar', tasks)).toEqual({ kind: 'approve' });
    expect(parseCommand('devolver', tasks)).toEqual({ kind: 'reject' });
  });

  it('reads the room controls', () => {
    expect(parseCommand('pause', tasks)).toEqual({ kind: 'pause' });
    expect(parseCommand('continue', tasks)).toEqual({ kind: 'resume' });
    expect(parseCommand('restart', tasks)).toEqual({ kind: 'restart' });
    expect(parseCommand('recenter', tasks)).toEqual({ kind: 'recenter' });
    expect(parseCommand('pausá', tasks)).toEqual({ kind: 'pause' });
  });

  it('launches a task by a word of its title or its place', () => {
    expect(parseCommand('launch the CSV export', tasks)).toEqual({ kind: 'launch', taskId: 'csv' });
    expect(parseCommand('start password reset', tasks)).toEqual({ kind: 'launch', taskId: 'reset' });
    expect(parseCommand('launch the third one', tasks)).toEqual({ kind: 'launch', taskId: 'ci' });
    expect(parseCommand('lanzar la primera', tasks)).toEqual({ kind: 'launch', taskId: 'reset' });
  });

  it('does nothing on a launch that names no task, or on chatter', () => {
    expect(parseCommand('launch', tasks)).toBeUndefined();
    expect(parseCommand('launch the thing', tasks)).toBeUndefined();
    expect(parseCommand('what a nice room', tasks)).toBeUndefined();
    expect(parseCommand('', tasks)).toBeUndefined();
  });

  it('a send back wins over an approval in the same sentence', () => {
    expect(parseCommand("don't approve it, send it back", tasks)).toEqual({ kind: 'reject' });
  });
});
