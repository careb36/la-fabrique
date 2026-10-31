/**
 * The room's panels. Each is built once and then updated from the room's
 * state; nothing is rebuilt per frame.
 */

import { UIKit } from '@iwsdk/core';

import type { DemoTask } from '../demo/scenario';
import { AGENT_LINES, awaitingDecision, LOG_LINES, type AgentState, type AgentView, type RoomState, type TaskState } from '../model';
import { button, COLORS, panel, row, text } from './kit';

const AGENT_COLOR: Record<AgentState, string> = {
  idle: COLORS.muted,
  working: COLORS.warn,
  done: COLORS.ok,
  error: COLORS.bad,
};

const TASK_LABEL: Record<TaskState, string> = {
  queued: 'Ready',
  in_progress: 'Agents working',
  in_review: 'In review',
  waiting_for_person: 'Waiting for you',
  done: 'Done',
  sent_back: 'Sent back',
};

export interface Panel {
  root: UIKit.Container;
  update(state: RoomState, paused: boolean): void;
}

/** One agent: its name, role, state and latest lines. Read-only. */
export function agentPanel(view: AgentView): Panel {
  const root = panel(0.2, undefined, 'bottom');
  root.setProperties({ padding: 1.5, gap: 0.6 });
  const header = row(0.8);
  const dot = new UIKit.Container({ width: 1.4, height: 1.4, borderRadius: 0.7, backgroundColor: AGENT_COLOR.idle });
  header.add(dot);
  header.add(text(view.name === view.role ? view.role : `${view.name} (${view.role})`, 1.7, COLORS.text, true));
  root.add(header);
  const stateText = text('idle', 1.3, COLORS.muted);
  root.add(stateText);
  const lines = Array.from({ length: AGENT_LINES }, () => text('', 1.2, COLORS.muted));
  for (const l of lines) root.add(l);
  return {
    root,
    update(state) {
      const agent = state.agents[view.role];
      dot.setProperties({ backgroundColor: AGENT_COLOR[agent.state] });
      stateText.setProperties({ text: agent.state, color: AGENT_COLOR[agent.state] });
      // Newest line on top, the older ones fading.
      const recent = [...agent.lines].reverse();
      lines.forEach((l, i) => l.setProperties({ text: recent[i] ?? '', color: i === 0 ? COLORS.text : COLORS.muted }));
    },
  };
}

/** The tasks a person can launch with a pinch. */
export function taskPanel(tasks: DemoTask[], onLaunch: (id: string) => void): Panel {
  const root = panel(0.3);
  root.add(text('Tasks', 2.4, COLORS.text, true));
  root.add(text('Pinch or poke one to hand it to the agents.', 1.3, COLORS.muted));
  const rows = tasks.map((task) => {
    const box = new UIKit.Container({
      flexDirection: 'row',
      gap: 1,
      padding: 1,
      borderRadius: 1,
      backgroundColor: '#161a20',
      alignItems: 'center',
      flexShrink: 0,
    });
    const words = new UIKit.Container({ flexDirection: 'column', gap: 0.4, flexGrow: 1, flexShrink: 1 });
    words.add(text(task.title, 1.6, COLORS.text, true));
    words.add(text(task.summary, 1.15, COLORS.muted));
    const status = text(TASK_LABEL.queued, 1.2, COLORS.muted);
    words.add(status);
    box.add(words);
    const launch = button('Launch', () => onLaunch(task.id), { primary: true });
    box.add(launch.root);
    root.add(box);
    return { task, status, launch };
  });
  return {
    root,
    update(state) {
      for (const r of rows) {
        const t = state.tasks[r.task.id];
        r.status.setProperties({
          text: TASK_LABEL[t.state],
          color: t.state === 'waiting_for_person' ? COLORS.accent : t.state === 'done' ? COLORS.ok : COLORS.muted,
        });
        r.launch.root.setProperties({ display: t.state === 'queued' ? 'flex' : 'none' });
      }
    },
  };
}

/** The delivery in focus: its files as a diff, the Verifier's checks, and the decision. */
export function resultPanel(onDecide: (taskId: string, approved: boolean) => void): Panel {
  const DIFF_LINES = 10;
  /** Characters per diff line; longer ones are cut, never wrapped. */
  const DIFF_WIDTH = 64;
  const root = panel(0.42);
  const title = text('Result', 2.4, COLORS.text, true);
  root.add(title);
  const risk = text('Launch a task to see what the agents deliver.', 1.4, COLORS.muted);
  root.add(risk);
  const diffBox = new UIKit.Container({ flexDirection: 'column', padding: 1, borderRadius: 1, backgroundColor: '#0b0d10', gap: 0.15, flexGrow: 1 });
  const diff = Array.from({ length: DIFF_LINES }, () => text('', 1.15, COLORS.muted));
  for (const d of diff) diffBox.add(d);
  root.add(diffBox);
  const checkTexts = Array.from({ length: 3 }, () => text('', 1.2, COLORS.muted));
  for (const c of checkTexts) root.add(c);
  const actions = row(1.5);
  let current: string | undefined;
  const approve = button('Approve', () => current && onDecide(current, true), { color: '#3f6212', grow: true });
  const reject = button('Send back', () => current && onDecide(current, false), { color: '#7f1d1d', grow: true });
  actions.add(approve.root);
  actions.add(reject.root);
  root.add(actions);
  const verdict = text('', 1.5, COLORS.muted, true);
  root.add(verdict);

  return {
    root,
    update(state) {
      const task = state.focus ? state.tasks[state.focus] : undefined;
      const d = task?.delivery;
      const waiting = awaitingDecision(state);
      current = waiting?.id;
      actions.setProperties({ display: waiting ? 'flex' : 'none' });
      if (!task || !d) return;
      title.setProperties({ text: `${task.title}: ${d.runId}` });
      risk.setProperties({
        text: `Risk ${d.risk}: ${d.riskReason}`,
        color: d.risk === 'high' ? COLORS.accent : COLORS.muted,
      });
      const lines = d.files
        .flatMap((f) => [`> ${f.path}`, ...f.lines])
        .map((l) => (l.length > DIFF_WIDTH ? `${l.slice(0, DIFF_WIDTH - 3)}...` : l));
      diff.forEach((t, i) => {
        const l = lines[i] ?? '';
        const color = l.startsWith('> ') ? COLORS.text : l.startsWith('+') ? COLORS.add : l.startsWith('-') ? COLORS.remove : COLORS.muted;
        t.setProperties({ text: i === DIFF_LINES - 1 && lines.length > DIFF_LINES ? `... ${lines.length - i} more lines` : l, color });
      });
      checkTexts.forEach((t, i) => {
        const c = d.checks[i];
        t.setProperties({ text: c ? `${c.ok ? 'OK' : 'FAIL'}  ${c.name}: ${c.observed}` : '', color: c?.ok ? COLORS.ok : COLORS.bad });
      });
      verdict.setProperties({
        text: waiting
          ? 'Waiting for you: approve or send it back.'
          : task.decision
            ? task.decision.approved
              ? 'You approved it.'
              : 'You sent it back: the agents are on it.'
            : task.state === 'done'
              ? 'Closed by QA: low risk needs no person.'
              : '',
        color: waiting ? COLORS.accent : COLORS.muted,
      });
    },
  };
}

/** Pause, resume, restart, and the room's last events. */
export function controlPanel(actions: { onPause: () => void; onRestart: () => void }): Panel {
  const root = panel(0.24);
  root.add(text('Room', 2.4, COLORS.text, true));
  const buttons = row(1);
  const pause = button('Pause', actions.onPause, { grow: true });
  buttons.add(pause.root);
  buttons.add(button('Restart', actions.onRestart, { grow: true }).root);
  root.add(buttons);
  const clock = text('', 1.3, COLORS.muted);
  root.add(clock);
  const log = Array.from({ length: LOG_LINES }, () => text('', 1.1, COLORS.muted));
  for (const l of log) root.add(l);
  return {
    root,
    update(state, paused) {
      pause.label.setProperties({ text: paused ? 'Resume' : 'Pause' });
      clock.setProperties({ text: paused ? 'Paused: nothing moves until you resume.' : 'Live' , color: paused ? COLORS.warn : COLORS.ok });
      const recent = [...state.log].reverse();
      log.forEach((l, i) => l.setProperties({ text: recent[i] ?? '' }));
    },
  };
}
