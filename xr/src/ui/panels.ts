/**
 * The room's panels. Each is built once and then updated from the room's
 * state; nothing is rebuilt per frame.
 */

import { UIKit } from '@iwsdk/core';
import type { Object3D } from 'three';

import type { DemoTask } from '../demo/scenario';
import { curve, type Company } from '../learning';
import { AGENT_LINES, awaitingDecision, LOG_LINES, type AgentState, type AgentView, type RoomState, type TaskState } from '../model';
import { button, COLORS, panel, row, text } from './kit';

/** An agent's state color, read from the palette in use. */
const agentColor = (state: AgentState): string =>
  ({ idle: COLORS.muted, working: COLORS.warn, done: COLORS.ok, error: COLORS.bad })[state];

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

/** What each agent is for, shown when the person looks at it. */
export const ROLE_DUTY: Record<AgentView['role'], string> = {
  Architect: 'Writes the brief before the code: what to build, and the traps to avoid.',
  Developer: 'Writes the code. What it says it wrote is a claim, never evidence.',
  QA: 'Reviews the delivery against the brief. Only an explicit APPROVED closes a task.',
  Verifier: 'Observes what really happened: hashes the files on disk and runs the tests.',
  ScrumMaster: 'Sends rework back, escalates what is stuck, and learns from each sprint.',
};

/** An agent's panel can be opened by looking at it. */
export interface AgentPanel extends Panel {
  focus(on: boolean): void;
}

/** One agent: its name, role, state and latest lines. Read-only. */
export function agentPanel(view: AgentView): AgentPanel {
  const root = panel(0.2, undefined, 'bottom');
  root.setProperties({ padding: 1.5, gap: 0.6 });
  const header = row(0.8);
  const dot = new UIKit.Container({ width: 1.4, height: 1.4, borderRadius: 0.7, backgroundColor: agentColor('idle') });
  header.add(dot);
  header.add(text(view.name === view.role ? view.role : `${view.name} (${view.role})`, 1.7, COLORS.text, true));
  root.add(header);
  const stateText = text('idle', 1.3, COLORS.muted);
  root.add(stateText);
  const lines = Array.from({ length: AGENT_LINES }, () => text('', 1.2, COLORS.muted));
  for (const l of lines) root.add(l);
  // Its duty, under a rule: shown only while the person looks at it.
  const duty = text(ROLE_DUTY[view.role], 1.25, COLORS.text);
  duty.setProperties({ display: 'none', borderTopWidth: 0.15, borderColor: COLORS.border, paddingTop: 0.6 });
  root.add(duty);
  return {
    root,
    focus(on) {
      duty.setProperties({ display: on ? 'flex' : 'none' });
      root.setProperties({ borderColor: on ? COLORS.accent : COLORS.border, borderWidth: on ? 0.35 : 0.2 });
    },
    update(state) {
      const agent = state.agents[view.role];
      dot.setProperties({ backgroundColor: agentColor(agent.state) });
      stateText.setProperties({ text: agent.state, color: agentColor(agent.state) });
      // Newest line on top, the older ones fading.
      const recent = [...agent.lines].reverse();
      lines.forEach((l, i) => l.setProperties({ text: recent[i] ?? '', color: i === 0 ? COLORS.text : COLORS.muted }));
    },
  };
}

/** The tasks panel can say where its first Launch button is, for the guide. */
export interface TaskPanel extends Panel {
  firstLaunch(state: RoomState): Object3D | undefined;
}

/** The tasks a person can launch with a pinch. */
export function taskPanel(
  tasks: DemoTask[],
  onLaunch: (id: string) => void,
  hint = 'Pinch or poke one to hand it to the agents.',
): TaskPanel {
  const root = panel(0.3);
  root.add(text('Tasks', 2.4, COLORS.text, true));
  root.add(text(hint, 1.3, COLORS.muted));
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
    firstLaunch(state) {
      return rows.find((r) => state.tasks[r.task.id].state === 'queued')?.launch.root;
    },
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
export function resultPanel(
  onDecide: (taskId: string, approved: boolean) => void,
  idle = 'Launch a task to see what the agents deliver.',
): Panel {
  const DIFF_LINES = 10;
  /** Characters per diff line; longer ones are cut, never wrapped. */
  const DIFF_WIDTH = 64;
  const root = panel(0.42);
  const title = text('Result', 2.4, COLORS.text, true);
  root.add(title);
  const risk = text(idle, 1.4, COLORS.muted);
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
          ? 'Waiting for you: pinch the delivery and drop it on Approve or Send back, or press a button.'
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

/** Pause, resume, restart, recenter, and the room's last events. */
export function controlPanel(actions: {
  onPause: () => void;
  onRecenter: () => void;
  onRestart: () => void;
  /** Where the room is laid out, in a few words. */
  where: () => string;
  /** 'Restart', or 'Next sprint' once the sprint has closed. */
  restartLabel: () => string;
  /** Switch high contrast; the label says what a press turns it to. */
  onContrast: () => void;
  contrast: () => boolean;
  /** Voice on or off; absent when the browser cannot listen. */
  onVoice?: () => void;
  /** What voice is doing, in a few words, or '' when it is off. */
  voice: () => string;
}): Panel {
  const root = panel(0.24);
  root.add(text('Room', 2.4, COLORS.text, true));
  const buttons = row(1);
  const pause = button('Pause', actions.onPause, { grow: true });
  buttons.add(pause.root);
  const restart = button('Restart', actions.onRestart, { grow: true });
  buttons.add(restart.root);
  root.add(buttons);
  // Seated or standing, the room comes back in front of the head.
  root.add(button('Recenter', actions.onRecenter).root);
  // Other ways in: high contrast, and voice where the browser can listen.
  // One per row: side by side, their longer labels outgrow the panel.
  const contrast = button('Contrast', actions.onContrast);
  root.add(contrast.root);
  const voice = actions.onVoice ? button('Voice', actions.onVoice) : undefined;
  if (voice) root.add(voice.root);
  const heard = text('', 1.2, COLORS.muted);
  root.add(heard);
  const clock = text('', 1.3, COLORS.muted);
  root.add(clock);
  const where = text('', 1.2, COLORS.muted);
  root.add(where);
  const log = Array.from({ length: LOG_LINES }, () => text('', 1.1, COLORS.muted));
  for (const l of log) root.add(l);
  return {
    root,
    update(state, paused) {
      pause.label.setProperties({ text: paused ? 'Resume' : 'Pause' });
      clock.setProperties({ text: paused ? 'Paused: nothing moves until you resume.' : 'Live', color: paused ? COLORS.warn : COLORS.ok });
      where.setProperties({ text: actions.where() });
      restart.label.setProperties({ text: actions.restartLabel() });
      contrast.label.setProperties({ text: actions.contrast() ? 'Contrast off' : 'Contrast' });
      const v = actions.voice();
      voice?.label.setProperties({ text: v ? 'Voice off' : 'Voice' });
      heard.setProperties({ text: v, display: v ? 'flex' : 'none' });
      const recent = [...state.log].reverse();
      log.forEach((l, i) => l.setProperties({ text: recent[i] ?? '' }));
    },
  };
}

/** How many sprints the curve shows, newest last. */
const CURVE_SPRINTS = 6;
/** The tallest bar, in centimeters. */
const BAR_CM = 5;

/**
 * The company's record across sessions: rework per task, sprint by sprint,
 * and the procedures in force with where each came from.
 */
export function companyPanel(read: () => Company, onNewCompany: () => void): Panel {
  const root = panel(0.2, undefined, 'bottom');
  root.setProperties({ padding: 1.5, gap: 0.6 });
  root.add(text('The company learns', 1.7, COLORS.text, true));
  const headline = text('', 1.25, COLORS.muted);
  root.add(headline);
  const chart = new UIKit.Container({ flexDirection: 'row', gap: 0.6, alignItems: 'flex-end', height: BAR_CM + 2.4, flexShrink: 0 });
  const columns = Array.from({ length: CURVE_SPRINTS }, () => {
    const col = new UIKit.Container({ flexDirection: 'column', alignItems: 'center', gap: 0.2, flexGrow: 1, flexShrink: 0 });
    const value = text('', 0.9, COLORS.muted);
    const bar = new UIKit.Container({ width: 1.6, height: 0.2, borderRadius: 0.3, backgroundColor: COLORS.accent });
    const label = text('', 0.9, COLORS.muted);
    col.add(value);
    col.add(bar);
    col.add(label);
    chart.add(col);
    return { col, value, bar, label };
  });
  root.add(chart);
  const procedures = Array.from({ length: 3 }, () => text('', 1.25, COLORS.text));
  for (const p of procedures) root.add(p);
  const fresh = button('New company', onNewCompany);
  // Tight padding: the label fits the narrow panel on one line.
  fresh.root.setProperties({ paddingX: 0.6 });
  fresh.label.setProperties({ fontSize: 1.5 });
  root.add(fresh.root);
  return {
    root,
    update() {
      const company = read();
      const values = curve(company).slice(-CURVE_SPRINTS);
      const first = Math.max(0, company.sprints.length - CURVE_SPRINTS);
      const top = Math.max(...values, 0.01);
      columns.forEach((c, i) => {
        const v = values[i];
        c.col.setProperties({ display: v === undefined ? 'none' : 'flex' });
        if (v === undefined) return;
        c.value.setProperties({ text: v.toFixed(2) });
        // A sprint with no rework still shows a sliver, in green.
        c.bar.setProperties({ height: Math.max(0.2, (v / top) * BAR_CM), backgroundColor: v === 0 ? COLORS.ok : COLORS.accent });
        c.label.setProperties({ text: `S${first + i + 1}` });
      });
      chart.setProperties({ display: values.length ? 'flex' : 'none' });
      const n = company.sprints.length;
      headline.setProperties({
        text:
          n === 0
            ? 'Finish a sprint: its rework becomes procedures, and the next sprint runs with them.'
            : `Rework per task. In force:`,
      });
      procedures.forEach((t, i) => {
        const p = company.procedures[i];
        t.setProperties({
          text: p ? `${p.text} From ${p.from === 'you' ? 'you' : 'QA'}, S${p.adoptedAfter}.` : '',
          display: p ? 'flex' : 'none',
        });
      });
    },
  };
}
