import { describe, expect, it } from 'vitest';

import { DEMO_TASKS } from './demo/scenario';
import { Player } from './engine/player';
import { closeSprint, curve, NEW_COMPANY, parseCompany, reworkCount, tasksWith } from './learning';

/** Play a whole sprint: launch everything, send the reset back once if asked, approve the rest. */
function playSprint(player: Player, sendBackReset: boolean): void {
  for (const t of DEMO_TASKS) player.launch(t.id);
  let sentBack = false;
  for (let i = 0; i < 1000; i++) {
    player.tick(500);
    for (const t of Object.values(player.state.tasks)) {
      if (t.state !== 'waiting_for_person') continue;
      const reject = sendBackReset && t.id === 'reset' && !sentBack;
      if (reject) sentBack = true;
      player.decide(t.id, !reject, reject ? 'add a test for a reused token' : '');
    }
    if (Object.values(player.state.tasks).every((t) => t.state === 'done')) return;
  }
  throw new Error('the sprint never closed');
}

describe('the company learns', () => {
  it('counts the rework of a sprint: QA requests and send backs', () => {
    const player = new Player(DEMO_TASKS);
    playSprint(player, true);
    expect(reworkCount(player.history())).toBe(2);
  });

  it('adopts a procedure for each task that needed rework, and the next sprint needs none', () => {
    const player = new Player(DEMO_TASKS);
    playSprint(player, true);
    const after1 = closeSprint(NEW_COMPANY, player.history(), DEMO_TASKS);
    expect(Object.fromEntries(after1.procedures.map((p) => [p.taskId, p.from]))).toEqual({ reset: 'you', csv: 'QA' });

    player.restart(tasksWith(after1, DEMO_TASKS));
    playSprint(player, false);
    const after2 = closeSprint(after1, player.history(), DEMO_TASKS);
    expect(curve(after2)).toEqual([2 / 3, 0]);
    // Nothing new to learn, nothing adopted twice.
    expect(after2.procedures).toHaveLength(2);
  });

  it('learns only what was asked: a sprint without a send back keeps the reset as it was', () => {
    const player = new Player(DEMO_TASKS);
    playSprint(player, false);
    const company = closeSprint(NEW_COMPANY, player.history(), DEMO_TASKS);
    expect(company.procedures.map((p) => p.taskId)).toEqual(['csv']);
    const next = tasksWith(company, DEMO_TASKS);
    expect(next.find((t) => t.id === 'reset')!.script).toBe(DEMO_TASKS[0].script);
  });

  it('reads back what it stored, and anything malformed as a new company', () => {
    const player = new Player(DEMO_TASKS);
    playSprint(player, true);
    const company = closeSprint(NEW_COMPANY, player.history(), DEMO_TASKS);
    expect(parseCompany(JSON.stringify(company))).toEqual(company);
    expect(parseCompany(null)).toEqual(NEW_COMPANY);
    expect(parseCompany('{not json')).toEqual(NEW_COMPANY);
    expect(parseCompany('{"sprints": 3}')).toEqual(NEW_COMPANY);
  });
});
