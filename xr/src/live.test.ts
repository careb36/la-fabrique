import { describe, expect, it } from 'vitest';
import { liveConfig, streamUrl, toRoomEvent } from './live';

describe('liveConfig', () => {
  it('is the demo without an API address', () => {
    expect(liveConfig(undefined, '?sprint=3')).toBeUndefined();
  });

  it('needs a numeric sprint', () => {
    expect(liveConfig('https://api.example', '')).toBeUndefined();
    expect(liveConfig('https://api.example', '?sprint=abc')).toBeUndefined();
  });

  it('reads the sprint and the ticket from the page address', () => {
    const cfg = liveConfig('https://api.example/', '?sprint=12&ticket=t.k')!;
    expect(cfg).toEqual({ api: 'https://api.example', sprintId: '12', ticket: 't.k' });
    expect(streamUrl(cfg)).toBe('https://api.example/v1/glassroom/stream?sprint_id=12&ticket=t.k');
  });
});

describe('toRoomEvent', () => {
  it('keeps an agent event with its role', () => {
    expect(toRoomEvent({ type: 'agent_start', agent: 'Dev', role: 'Developer', message: 'Writing' }, 'live')).toEqual({
      type: 'agent_start',
      role: 'Developer',
      agent: 'Dev',
      message: 'Writing',
      taskId: 'live',
    });
  });

  it('gives the gates to the Verifier', () => {
    const e = toRoomEvent({ type: 'status', agent: 'Verifier', role: 'System', message: 'files_written: verified' }, 'live');
    expect(e && 'role' in e && e.role).toBe('Verifier');
  });

  it('keeps system events as the room log', () => {
    const e = toRoomEvent({ type: 'status', agent: 'System', role: 'System', message: 'Sprint completed' }, 'live');
    expect(e && 'role' in e && e.role).toBe('System');
  });

  it('drops what the room does not show', () => {
    expect(toRoomEvent({ type: 'ping' }, 'live')).toBeUndefined();
    expect(toRoomEvent({ type: 'status', agent: 'System', message: '' }, 'live')).toBeUndefined();
    expect(toRoomEvent('nonsense', 'live')).toBeUndefined();
    expect(toRoomEvent(null, 'live')).toBeUndefined();
  });
});
