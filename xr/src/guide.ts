/**
 * The first minute: a guide shows the person each first move where it is
 * made, then gets out of the way. Launch a task, look at an agent while it
 * works, then take the delivery to a ring. Once the person has decided once,
 * the guide is gone for the rest of the run.
 */

import { awaitingDecision, type RoomState } from './model';

export type GuideStep = 'launch' | 'look' | 'decide' | 'none';

export const GUIDE_TEXT: Record<Exclude<GuideStep, 'none'>, string> = {
  launch: 'Pinch Launch, or poke it, to hand the task to the agents.',
  look: 'Look at an agent for a moment to see what it does.',
  decide: 'Pinch the delivery, carry it onto a ring and let go.',
};

/**
 * Which first move to show. `looked` says the person already opened an
 * agent by looking at it, so that hint is not repeated.
 */
export function guideStep(state: RoomState, looked: boolean): GuideStep {
  const tasks = Object.values(state.tasks);
  if (tasks.some((t) => t.decision)) return 'none';
  if (awaitingDecision(state)) return 'decide';
  if (tasks.every((t) => t.state === 'queued')) return 'launch';
  return looked ? 'none' : 'look';
}
