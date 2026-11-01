/**
 * What the room can be asked to do by voice: the declarations.
 *
 * Data only: each action's phrases in both languages, its label, whether it
 * must be confirmed. `main.ts` attaches what each one does (`roomRegistry`);
 * the bench reads the same declarations with no room behind them, so the
 * grammar measured is the grammar shipped. Order is priority: a sentence
 * that matches two actions gets the first, so a send back beats an approval
 * and a restart beats a launch ("arrancá otra vez desde cero").
 */

import { CommandRegistry, type Action, type ActionSpec, type Item, type Outcome, type RunContext, type Speech } from './voice';

export const ROOM_ACTIONS: ActionSpec[] = [
  {
    id: 'reject',
    label: { es: 'devolver', en: 'send back' },
    phrases: {
      es: ['devolv*', 'devuelv*', 'rechaz*', 'mand* de vuelta', 'de vuelta', 'rehag*', 'rehac*', 'no va', 'que lo arreglen'],
      en: ['send back', 'send _ back', 'send _ _ back', 'reject*', 'rework', 'needs work', 'not good enough'],
    },
    risk: 'confirm',
    confirm: { es: '¿Devuelvo {item}?', en: 'Send {item} back?' },
  },
  {
    id: 'approve',
    label: { es: 'aprobar', en: 'approve' },
    phrases: {
      es: ['aprob*', 'aprueb*', 'acept*', 'esta bien asi', 'dale para adelante'],
      en: ['approv*', 'accept*', 'ship it', 'ship', 'looks good', 'sign off'],
    },
    risk: 'confirm',
    confirm: { es: '¿Apruebo {item}?', en: 'Approve {item}?' },
  },
  {
    id: 'restart',
    label: { es: 'reiniciar', en: 'restart' },
    phrases: {
      es: ['reinici*', 'de nuevo', 'otra vez', 'desde cero'],
      en: ['restart*', 'start over', 'start again', 'from scratch', 'begin again'],
    },
  },
  {
    id: 'next',
    label: { es: 'siguiente sprint', en: 'next sprint' },
    phrases: {
      es: ['siguiente sprint', 'proximo sprint', 'otro sprint', '^siguiente', '^proximo', '^el siguiente', '^el proximo'],
      en: ['next sprint', 'another sprint', 'move on', '^next', '^the next one'],
    },
  },
  {
    id: 'pause',
    label: { es: 'pausar', en: 'pause' },
    phrases: {
      es: ['pausa*', 'para un momento', 'para un segundo', 'para un rato', 'para ahi', '^para', 'esper*', 'deten*', 'frena*'],
      en: ['pause*', 'hold on', 'hold it', 'wait', 'stop', 'freeze'],
    },
  },
  {
    id: 'resume',
    label: { es: 'seguir', en: 'resume' },
    phrases: {
      es: ['segui*', 'sigue', 'siga', 'sigamos', 'continu*', 'reanud*', 'retom*'],
      en: ['resume*', 'continue', 'go on', 'carry on', 'keep going', 'unpause'],
    },
  },
  {
    id: 'recenter',
    label: { es: 'centrar', en: 'recenter' },
    phrases: {
      es: ['centr*', 'recentr*', 'veni aca', 'ven aca', 'vengan aca', 'al frente', 'aca adelante', 'frente a mi'],
      en: ['recenter*', 'recentre*', 'center*', 'centre*', 'come here', 'in front of me', 'bring _ back'],
    },
  },
  {
    id: 'mute',
    label: { es: 'silenciar', en: 'mute' },
    phrases: {
      es: ['silenci*', 'sin sonido', 'sac* el sonido', 'apag* el sonido', 'callat*', 'calla*', 'mute*', 'shh'],
      en: ['mute*', 'sound off', 'quiet', 'silence*', 'turn _ sound off', 'hush'],
    },
  },
  {
    id: 'unmute',
    label: { es: 'poner sonido', en: 'unmute' },
    phrases: {
      es: ['con sonido', 'pon* el sonido', 'pon* sonido', 'activ* el sonido', 'prend* el sonido', 'volve* el sonido'],
      en: ['unmute*', 'sound on', 'turn _ sound on', 'turn _ sound back on'],
    },
  },
  {
    id: 'launch',
    label: { es: 'lanzar una tarea', en: 'launch a task' },
    phrases: {
      es: ['lanz*', 'arranc*', 'empez*', 'empiec*', 'inici*', 'dale con', 'manda* la', 'larg*'],
      en: ['launch*', 'start*', 'run', 'begin*', 'go ahead with', 'kick off', 'fire up'],
    },
    whichItem: { es: '¿Cuál tarea? {items}.', en: 'Which task? {items}.' },
  },
  {
    id: 'status',
    label: { es: 'preguntar cómo va', en: 'ask for the status' },
    phrases: {
      es: ['como va*', 'como vamos', 'como anda*', 'estado', 'que estan haciendo', 'que hacen', 'novedades', 'que paso', 'que pasa'],
      en: ['how is it going', 'how s it going', 'hows it going', 'how are we doing', 'status', 'what are _ doing', 'what are _ _ doing', 'what is happening', 'what s happening', 'any news'],
    },
  },
];

/** Words a person uses for the demo's tasks that are not in their titles. */
export const TASK_WORDS: Record<string, { es: string[]; en: string[] }> = {
  reset: { es: ['contraseña', 'clave', 'password', 'reset', 'login'], en: ['password', 'reset', 'login'] },
  csv: { es: ['csv', 'exportación', 'exportar', 'planilla'], en: ['csv', 'export', 'spreadsheet'] },
  ci: { es: ['ci', 'runner', 'pipeline', 'acciones', 'integración'], en: ['ci', 'runner', 'pipeline', 'actions'] },
};

/** What the room does for each action; `main.ts` provides them. */
type Handler = (ctx: RunContext) => Outcome | Speech;
export type RoomHandlers = Record<'approve' | 'reject' | 'restart' | 'next' | 'pause' | 'resume' | 'recenter' | 'mute' | 'unmute' | 'launch' | 'status', Handler>;

/** The tasks as items a person can name: by title, by alias, by place. */
export function taskItems(tasks: { id: string; title: string }[]): Item[] {
  return tasks.map((t) => ({ id: t.id, label: { es: t.title, en: t.title }, words: TASK_WORDS[t.id] }));
}

/** What the room knows about a decision right now; `main.ts` provides it. */
export interface DecisionState {
  /** Why approving or sending back is not possible now, or undefined when it is. */
  decisionBlocked: () => Speech | undefined;
  /** The delivery a decision would be about, for the confirmation question. */
  decisionSubject: () => Speech | undefined;
}

const NO_DECISION: DecisionState = { decisionBlocked: () => undefined, decisionSubject: () => undefined };

/** The registry the room listens with: declarations plus what each does. */
export function roomRegistry(handlers: RoomHandlers, items: () => Item[], decision: DecisionState = NO_DECISION): CommandRegistry {
  const actions: Action[] = ROOM_ACTIONS.map((spec) => ({
    ...spec,
    items: spec.id === 'launch' ? items : undefined,
    blocked: spec.risk === 'confirm' ? decision.decisionBlocked : undefined,
    subject: spec.risk === 'confirm' ? decision.decisionSubject : undefined,
    run: handlers[spec.id as keyof RoomHandlers],
  }));
  // "No la apruebo" is a send back, not an approval.
  return new CommandRegistry(actions, { approve: 'reject' });
}
