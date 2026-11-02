import {
  createSystem,
  DistanceGrabbable,
  Grabbed,
  MovementMode,
  PokeInteractable,
  RayInteractable,
  SessionMode,
  UIKitDocument,
  VisibilityState,
  World,
} from '@iwsdk/core';
import { Object3D, Quaternion, Vector3 } from 'three';

import { dropOn } from './decide';
import { Dwell, gazed } from './gaze';
import { GUIDE_TEXT, guideStep } from './guide';
import { DEMO_TASKS } from './demo/scenario';
import { Player } from './engine/player';
import { layoutRoom, type Placed, type RoomLayout, type Surface } from './room';
import { SurfaceSystem } from './surfaces';
import { connectLive, liveConfig } from './live';
import { closeSprint, NEW_COMPANY, parseCompany, tasksWith, type Company } from './learning';
import { awaitingDecision, ROLES, tokenAt } from './model';
import { agentPanel, companyPanel, controlPanel, resultPanel, taskPanel, type Panel } from './ui/panels';
import { guide } from './ui/guide';
import { highContrast, setContrast } from './ui/kit';
import { roomRegistry, taskItems } from './commands';
import {
  FallbackSpeaker,
  firstAvailable,
  PiperSpeaker,
  SilentSpeaker,
  VoiceSession,
  WebSpeechRecognizer,
  WebSpeechSpeaker,
  WhisperRecognizer,
  whisperSize,
  type Lang,
  type Recognizer,
} from './voice';
import { FrameStats, perfLine } from './perf';
import { cueFor, Sound } from './sound';
import { ROLE_COLOR } from './ui/presence';
import { dropZone, presence, token } from './ui/presence';

/** Seated eye height above the floor. */
const HEAD_Y = 1.2;
/** Seconds after entering XR (or Recenter) before reading the room. */
const SURFACE_WAIT_S = 1.2;

const PLACEMENT_TEXT: Record<RoomLayout['mode'], string> = {
  'desk+wall': 'On your desk, the team on your wall.',
  desk: 'On your desk.',
  wall: 'The team on your wall.',
  arc: 'Floating in front of you.',
};

const container = document.getElementById('scene-container') as HTMLDivElement;
const notice = document.getElementById('notice') as HTMLDivElement;

/** Replace the loading notice with what went wrong and what to try. */
function fail(title: string, hint: string): never {
  notice.className = 'error';
  notice.replaceChildren();
  const p = document.createElement('p');
  const strong = document.createElement('strong');
  strong.textContent = title;
  p.append(strong, document.createElement('br'), hint);
  notice.append(p);
  throw new Error(title);
}

// The scene needs WebGL 2. Without it (hardware acceleration off, a blocked
// GPU) the page would stay black, so say so instead.
if (!document.createElement('canvas').getContext('webgl2')) {
  fail(
    'This browser cannot draw 3D (WebGL 2 is off).',
    'Turn on hardware acceleration in the browser settings, or open the link in a recent Chrome or Edge, or on a Meta Quest.',
  );
}

const world = await World.create(container, {
  xr: {
    // Mixed reality: the room stays visible around the panels.
    sessionMode: SessionMode.ImmersiveAR,
    offer: 'always',
    // The room's table and walls (plane and mesh detection) and an anchor
    // that keeps the factory where it was put; optional, so a browser
    // without them still opens the room.
    features: { handTracking: true, planeDetection: true, meshDetection: true, anchors: true },
  },
  // The desktop view only: a step back from the seat so every panel fits on
  // a screen. In a headset, tracking puts the camera at the person's eyes.
  render: { fov: 75, camera: { position: [0, HEAD_Y + 0.05, 0.42], lookAt: [0, HEAD_Y - 0.08, -0.45] } },
  // Grabbing: the person takes the delivery in hand to decide on it.
  features: { grabbing: true, locomotion: false, physics: false, sceneUnderstanding: true },
}).catch((error: unknown) =>
  fail('The room did not start.', `${error instanceof Error ? error.message : String(error)}. Try reloading the page.`),
);

// Foveated rendering: the edges of each eye's view drawn at lower resolution,
// where the lenses blur them anyway. A large saving on Quest, invisible to the
// person; browsers without it ignore the call.
world.renderer.xr.setFoveation?.(1);

// Live mode follows a real sprint when the build names a backend
// (VITE_FABRIQUE_API) and the address a sprint (?sprint=); otherwise the demo.
const live = liveConfig(import.meta.env.VITE_FABRIQUE_API, location.search);
// The company's record is kept on this device: each finished run of the demo
// is a sprint, and what it taught runs in the next one.
const COMPANY_KEY = 'la-fabrique-xr.company';
function loadCompany(): Company {
  try {
    return parseCompany(localStorage.getItem(COMPANY_KEY));
  } catch {
    return NEW_COMPANY;
  }
}
function saveCompany(c: Company): void {
  try {
    localStorage.setItem(COMPANY_KEY, JSON.stringify(c));
  } catch {
    /* kept for this session only */
  }
}
let company = loadCompany();
/** This run's sprint has closed and been recorded. */
let sprintClosed = false;
/** How many times faster than real time the demo's clock runs (director mode). */
let timeScale = 1;

const tasks = live
  ? [{ id: 'live', title: `Sprint ${live.sprintId}`, summary: 'Live from the factory', script: [] }]
  : DEMO_TASKS;
const player = new Player(live ? tasks : tasksWith(company, DEMO_TASKS));
let previous = VisibilityState.NonImmersive as VisibilityState;
/** Paused by the headset (system menu, headset off), not by the person. */
let autoPaused = false;

const panels: Panel[] = [];
let dirty = true;
const touch = () => {
  dirty = true;
};

interface Hosted {
  object: Object3D;
  root: Panel['root'];
  /** The edge the panel is held by, from the last layout. */
  anchor?: 'top' | 'bottom';
  /** Its size from the last layout, before any opening by a look. */
  scale: number;
}
const handPanels: Hosted[] = [];
const agentPanels: Hosted[] = [];

function place(p: Panel, group: Hosted[]): void {
  // Both ways a hand presses a button: a fingertip crossing it (poke) and a
  // pinch while pointing at it (ray). Either works with controllers too.
  const entity = world.createTransformEntity().addComponent(RayInteractable).addComponent(PokeInteractable);
  entity.object3D!.add(new UIKitDocument(p.root));
  group.push({ object: entity.object3D!, root: p.root, scale: 1 });
  panels.push(p);
}

/** Where the panels are now: on the desk and wall, or the floating arc. */
let placement: RoomLayout['mode'] = 'arc';

function apply(group: Hosted[], spots: Placed[]): void {
  group.forEach(({ object, root }, i) => {
    const at = spots[i];
    object.position.set(at.x, at.y, at.z);
    // Turn to face the head first, then lean back.
    object.rotation.set(-at.tilt, at.yaw, 0, 'YXZ');
    object.scale.setScalar(at.scale);
    root.setProperties({ anchorY: at.anchor });
    group[i].anchor = at.anchor;
    group[i].scale = at.scale;
  });
}

/** Lay the room out around a head, on whatever surfaces the room has. */
function arrange(head: Vector3, yaw: number, found: Surface[] = []): void {
  const room = layoutRoom(found, head, yaw, agentPanels.length);
  apply(handPanels, room.hands);
  apply(agentPanels, room.agents);
  placement = room.mode;
  touch();
}

const SEATED_HEAD = new Vector3(0, HEAD_Y, 0);
/** Set when the room should move to where the person's head is. */
let recenter = false;

/** Where the head is and which way it faces, from the camera. */
function headPose(): { head: Vector3; yaw: number } {
  const head = new Vector3();
  const forward = new Vector3();
  world.camera.getWorldPosition(head);
  world.camera.getWorldDirection(forward);
  return { head, yaw: Math.atan2(-forward.x, -forward.z) };
}

// Tasks on the left, the result ahead, the room's controls on the right:
// on the desk when there is one, otherwise on a floating arc.
const tasksPanel = taskPanel(
  tasks,
  (id) => {
    if (player.launch(id)) touch();
  },
  live ? 'Watching the factory: tasks start from the web app.' : undefined,
);
place(tasksPanel, handPanels);
place(
  resultPanel((id, approved) => decide(id, approved), live ? 'Live mode watches: approve or send back in the web app.' : undefined),
  handPanels,
);
function setPaused(paused: boolean): void {
  if (paused) player.pause();
  else player.resume();
  autoPaused = false;
  touch();
}
function restart(): void {
  // The next sprint runs with every procedure in force.
  player.restart(live ? undefined : tasksWith(company, DEMO_TASKS));
  sprintClosed = false;
  // Live mode clears the view; the sprint itself goes on.
  if (live) player.ingest({ type: 'task_state', taskId: 'live', state: 'in_progress' });
  touch();
}

// High contrast is remembered on this device; storage may be unavailable.
const CONTRAST_KEY = 'la-fabrique-xr.contrast';
try {
  if (localStorage.getItem(CONTRAST_KEY) === 'high') setContrast(true);
} catch {
  /* no storage: standard colors */
}

// Sound starts with a person's gesture, as browsers require: the click that
// enters XR (or any click on the page).
const sound = new Sound();
document.addEventListener('click', () => sound.unlock());
const SOUND_KEY = 'la-fabrique-xr.muted';
try {
  sound.muted = localStorage.getItem(SOUND_KEY) === 'yes';
} catch {
  /* sound on */
}
function setMuted(muted: boolean): void {
  sound.muted = muted;
  try {
    localStorage.setItem(SOUND_KEY, muted ? 'yes' : 'no');
  } catch {
    /* not remembered */
  }
  touch();
}

// The frame meter, with ?perf: measured in the room, shown on the Room panel.
const showPerf = new URLSearchParams(location.search).has('perf');
const frames = new FrameStats();
let perfText = '';

// Voice: the room's actions declared in `commands.ts`, listened for and
// answered by the voice layer, in the language the person speaks. The page
// language (`?lang=es`, else the browser's) decides the answer when a phrase
// does not tell, and which language the browser's recognizer listens in.
const voiceLang = (): Lang => ((new URLSearchParams(location.search).get('lang') ?? navigator.language).toLowerCase().startsWith('es') ? 'es' : 'en');
const ROLE_NAME_ES: Record<string, string> = { Architect: 'el Arquitecto', Developer: 'el Desarrollador', QA: 'QA', Verifier: 'el Verificador', ScrumMaster: 'el Scrum Master' };
const LIVE_DECIDES = { es: 'En modo live se decide en la aplicación web.', en: 'Live mode: decide in the web app.' };
const NOTHING_WAITING = { es: 'No hay ninguna entrega esperándote.', en: 'Nothing is waiting for you.' };
const voiceRegistry = roomRegistry(
  {
    approve: () => {
      const waiting = awaitingDecision(player.state);
      if (!waiting) return NOTHING_WAITING;
      decide(waiting.id, true);
      return { es: 'Aprobada.', en: 'Approved.' };
    },
    reject: () => {
      const waiting = awaitingDecision(player.state);
      if (!waiting) return NOTHING_WAITING;
      decide(waiting.id, false);
      return { es: 'Devuelta a los agentes.', en: 'Sent back.' };
    },
    restart: () => {
      restart();
      return { es: 'Reiniciado.', en: 'Restarted.' };
    },
    next: () => {
      if (!sprintClosed) return { es: 'El sprint todavía está en marcha.', en: 'The sprint is still running.' };
      restart();
      return { es: 'Arranca el siguiente sprint.', en: 'Next sprint starting.' };
    },
    pause: () => {
      setPaused(true);
      return { es: 'En pausa.', en: 'Paused.' };
    },
    resume: () => {
      setPaused(false);
      return { es: 'Seguimos.', en: 'Resumed.' };
    },
    recenter: () => {
      recenter = true;
      return { es: 'Centrando.', en: 'Recentering.' };
    },
    mute: () => {
      setMuted(true);
      return { es: 'Sin sonido.', en: 'Sound off.' };
    },
    unmute: () => {
      setMuted(false);
      return { es: 'Con sonido.', en: 'Sound on.' };
    },
    launch: ({ item }) => {
      if (live) return { es: 'En modo live las tareas arrancan desde la aplicación web.', en: 'Live mode: tasks start from the web app.' };
      if (!item || !player.launch(item.id)) return { es: 'Esa tarea ya está en marcha o terminada.', en: 'That task is already running or done.' };
      touch();
      return { es: `Lanzada: ${item.label.es}.`, en: `Launched ${item.label.en}.` };
    },
    status: () => {
      const all = Object.values(player.state.tasks);
      const done = all.filter((t) => t.state === 'done').length;
      const waiting = awaitingDecision(player.state);
      const active = player.state.active;
      return {
        es:
          `${done} de ${all.length} tareas listas.` +
          (waiting ? ` ${waiting.title} espera tu decisión.` : '') +
          (active ? ` Está trabajando ${ROLE_NAME_ES[active] ?? active}.` : '') +
          (player.paused ? ' La sala está en pausa.' : ''),
        en:
          `${done} of ${all.length} tasks done.` +
          (waiting ? ` ${waiting.title} is waiting for your decision.` : '') +
          (active ? ` The ${active} is working.` : '') +
          (player.paused ? ' The room is paused.' : ''),
      };
    },
  },
  () => taskItems(tasks),
  {
    // A decision needs a delivery waiting, and in live mode the web app decides.
    decisionBlocked: () => (live ? LIVE_DECIDES : awaitingDecision(player.state) ? undefined : NOTHING_WAITING),
    decisionSubject: () => awaitingDecision(player.state)?.title,
  },
);
/** The last exchange, shown on the Room panel; '' while voice is off. */
let voiceLine = '';
let lastHeard = '';
// Who listens: the browser's own recognizer where it exists (instant, no
// download), else Whisper running in the page, the only one the Meta Quest
// browser has. `?stt=whisper` forces the latter, `?stt=tiny|base|small`
// picks its size (the bench's numbers decide the default).
const voiceParams = new URLSearchParams(location.search);
const sttChoice = voiceParams.get('stt') ?? 'auto';
const whisper = new WhisperRecognizer({
  size: whisperSize(sttChoice, 'base'),
  hints: () => ({ es: voiceRegistry.vocabularyHint('es'), en: voiceRegistry.vocabularyHint('en') }),
  preferredLanguage: voiceLang,
  // Absolute: the worker fetches it, and a relative path would be read against the worker's own URL.
  vadUrl: new URL(`${import.meta.env.BASE_URL}silero_vad_v6.onnx`, document.baseURI).href,
});
const webSpeech = new WebSpeechRecognizer(voiceLang);
const voiceRecognizer: Recognizer | undefined = firstAvailable(sttChoice === 'auto' || sttChoice === 'web' ? [webSpeech, whisper] : [whisper, webSpeech]);
// Who talks back: the browser's voice where it has one, else Piper running
// in the page (a voice per language, downloaded once); `?tts=piper` forces
// Piper, `?tts=web` the browser's. Without either the words stay on the panel.
const ttsChoice = voiceParams.get('tts') ?? 'auto';
const piper = new PiperSpeaker({
  onStatus: (s) => {
    if (s.kind === 'loading') {
      voiceLine = s.percent < 100 ? `${s.lang === 'es' ? 'Descargando la voz' : 'Downloading the voice'} (${s.percent}%)...` : voiceLine;
      touch();
    } else console.info(`[voice] piper spoke ${s.audioSeconds.toFixed(1)} s of ${s.lang} in ${s.synthesisSeconds.toFixed(1)} s`);
  },
});
const browserVoice = new WebSpeechSpeaker();
const speakers = ttsChoice === 'piper' ? [piper, browserVoice] : ttsChoice === 'web' ? [browserVoice] : [browserVoice, piper];
const voice = new VoiceSession({
  registry: voiceRegistry,
  recognizer: voiceRecognizer ?? webSpeech,
  speaker: new FallbackSpeaker([...speakers, new SilentSpeaker()]),
  language: voiceLang,
  onEvent: (e) => {
    if (e.kind === 'heard') {
      lastHeard = e.text;
      return;
    }
    if (e.kind === 'status') {
      // Progress and "hearing you" replace the line only while nothing was said.
      if (e.text && !lastHeard) voiceLine = e.text;
      else if (e.status.kind === 'speech-start') lastHeard = '';
      touch();
      return;
    }
    if (e.kind === 'listening') lastHeard = '';
    voiceLine = e.kind === 'stopped' ? '' : lastHeard ? `"${lastHeard}": ${e.text}` : e.text;
    if (e.kind === 'error') player.ingest({ type: 'status', role: 'System', agent: 'Voice', message: e.text, taskId: tasks[0].id });
    touch();
  },
});

place(
  controlPanel({
    onPause: () => setPaused(!player.paused),
    onRecenter: () => {
      recenter = true;
    },
    onRestart: restart,
    where: () => PLACEMENT_TEXT[placement],
    restartLabel: () => (sprintClosed ? 'Next sprint' : 'Restart'),
    onSound: () => {
      sound.unlock();
      setMuted(!sound.muted);
    },
    sound: () => !sound.muted,
    perf: () => perfText,
    onContrast: () => {
      setContrast(!highContrast);
      try {
        localStorage.setItem(CONTRAST_KEY, highContrast ? 'high' : 'standard');
      } catch {
        /* not remembered */
      }
      touch();
    },
    contrast: () => highContrast,
    onVoice: voiceRecognizer ? () => voice.toggle() : undefined,
    voice: () => voiceLine,
  }),
  handPanels,
);
// The agents only show: on the wall ahead as the team's board, or above.
const agentViews = ROLES.map((role) =>
  agentPanel({ ...player.state.agents[role] }, `#${ROLE_COLOR[role].toString(16).padStart(6, '0')}`),
);
for (const view of agentViews) place(view, agentPanels);
// The company's record hangs with the team, after the agents.
if (!live) {
  place(
    companyPanel(
      () => company,
      newCompany,
    ),
    agentPanels,
  );
}

function newCompany(): void {
  company = NEW_COMPANY;
  saveCompany(company);
  restart();
}

/**
 * When every task of the run is done, the sprint closes: its numbers are
 * recorded and its rework becomes procedures, announced by the ScrumMaster.
 */
function closeIfDone(): void {
  if (live || sprintClosed) return;
  if (!Object.values(player.state.tasks).every((t) => t.state === 'done')) return;
  sprintClosed = true;
  const before = company.procedures.length;
  company = closeSprint(company, player.history(), DEMO_TASKS);
  saveCompany(company);
  const last = company.sprints[company.sprints.length - 1];
  const adopted = company.procedures.length - before;
  player.ingest({
    type: 'message',
    role: 'ScrumMaster',
    agent: 'Sam',
    message:
      `Sprint ${last.sprint} closed: ${last.rework} rework on ${last.tasks} tasks. ` +
      (adopted ? `Adopted ${adopted} procedure${adopted === 1 ? '' : 's'}; Next sprint runs with them.` : 'Nothing new to learn.'),
    taskId: DEMO_TASKS[0].id,
  });
  touch();
}

// Each agent's light sits just above its panel, wherever the panel goes;
// the task travels between them and down to the result.
const presences = ROLES.map((role, i) => {
  const p = presence(role);
  p.group.position.set(0, 0.22, 0.01);
  agentPanels[i].object.add(p.group);
  return { role, p, state: player.state.agents[role].state, changedAt: 0 };
});
const task = token();
// The delivery can be taken in hand: a pinch while pointing at it, near or
// across the desk, moves it with the hand. Dropped on Approve or Send back
// it decides; anywhere else it glides back.
const taskEntity = world.createTransformEntity(task.group).addComponent(DistanceGrabbable, {
  movementMode: MovementMode.MoveAtSource,
  rotate: false,
  scale: false,
});
const target = new Vector3();
const DECISION = { decline: 'add a test for a reused token' };

/** Approve on the right, Send back on the left, beside the delivery. */
const zones = {
  approve: dropZone('Approve', 0xa3e635),
  reject: dropZone('Send back', 0xf87171),
};
handPanels[1].object.add(zones.approve.group, zones.reject.group);
let held = false;

// Looking at an agent for a moment opens its panel: larger, with its duty.
const dwell = new Dwell();
/** The person has opened an agent by looking at it at least once. */
let looked = false;
// The guide for the first moves; demo only, since live mode starts and
// decides tasks in the web app.
const firstMoves = guide();
world.scene.add(firstMoves.group);

function decide(id: string, approved: boolean): void {
  if (player.decide(id, approved, approved ? '' : DECISION.decline)) touch();
}

/** Where the task should be now, in world space, or undefined when idle. */
function taskTarget(): Vector3 | undefined {
  const at = tokenAt(player.state);
  if (at === 'none') return undefined;
  if (at === 'result') {
    // Just above the result panel's top edge.
    const { object, anchor } = handPanels[1];
    return object.localToWorld(target.set(0, anchor === 'bottom' ? 0.42 : 0.05, 0.02));
  }
  const holder = presences.find((x) => x.role === at)!;
  return holder.p.group.localToWorld(target.set(0, 0.05, 0));
}
arrange(SEATED_HEAD, 0);

// Leaving the headset or opening the system menu pauses the room; coming
// back resumes it, unless the person had paused it themselves.
world.visibilityState.subscribe((v) => {
  // Entering XR: the room moves to wherever the person's head is, sitting or
  // standing. Leaving it: back to the seated view of the desktop page.
  if (v === VisibilityState.Visible && previous === VisibilityState.NonImmersive) recenter = true;
  if (v === VisibilityState.NonImmersive && previous !== VisibilityState.NonImmersive) arrange(SEATED_HEAD, 0);
  previous = v;
  const away = v === VisibilityState.Hidden || v === VisibilityState.VisibleBlurred;
  if (away && !player.paused) {
    player.pause();
    autoPaused = true;
    touch();
  } else if (!away && autoPaused) {
    player.resume();
    autoPaused = false;
    touch();
  }
});
document.addEventListener('visibilitychange', () => {
  if (document.hidden && !player.paused) {
    player.pause();
    autoPaused = true;
    touch();
  } else if (!document.hidden && autoPaused) {
    player.resume();
    autoPaused = false;
    touch();
  }
});

const surfaces = world.registerSystem(SurfaceSystem).getSystem(SurfaceSystem)!;

class RoomSystem extends createSystem() {
  private waited = 0;
  /** How many of the player's events have been heard. */
  private heard = 0;
  private perfAge = 0;

  /** Every new event that makes a sound plays it from where it happens. */
  hear(): void {
    const history = player.history();
    if (history.length < this.heard) this.heard = 0; // a restart
    const head = world.camera.getWorldPosition(new Vector3());
    const forward = world.camera.getWorldDirection(new Vector3());
    const up = new Vector3(0, 1, 0).applyQuaternion(world.camera.getWorldQuaternion(new Quaternion()));
    sound.listen(head, forward, up);
    for (; this.heard < history.length; this.heard++) {
      const cue = cueFor(history[this.heard]);
      if (!cue) continue;
      const at = cue.role
        ? presences[ROLES.indexOf(cue.role)].p.group.getWorldPosition(new Vector3())
        : handPanels[1].object.getWorldPosition(new Vector3());
      sound.play(cue, at);
    }
  }

  /** The frame meter: every frame counted, the line refreshed twice a second. */
  meter(delta: number): void {
    if (!showPerf) return;
    frames.add(delta);
    if ((this.perfAge += delta) < 0.5) return;
    this.perfAge = 0;
    const { calls, triangles } = world.renderer.info.render;
    perfText = perfLine(frames.report(), calls, triangles);
    touch();
  }

  /** Which agent the head rests on; that panel opens. */
  look(delta: number): void {
    const before = dwell.open;
    let target = -1;
    if (world.visibilityState.value !== VisibilityState.NonImmersive) {
      const head = new Vector3();
      const forward = new Vector3();
      world.camera.getWorldPosition(head);
      world.camera.getWorldDirection(forward);
      // The middle of each panel: it stands on its bottom edge.
      const middles = agentPanels.map((h) => h.object.localToWorld(new Vector3(0, 0.08, 0)));
      target = gazed(head, forward, middles);
    }
    const open = dwell.update(target, delta);
    if (open !== before) {
      agentViews.forEach((v, i) => v.focus(i === open));
      if (open >= 0) looked = true;
    }
    // Opened panels grow a little, smoothly.
    const k = 1 - Math.exp(-delta * 10);
    agentPanels.forEach((h, i) => {
      const want = h.scale * (i === open ? 1.2 : 1);
      h.object.scale.setScalar(h.object.scale.x + (want - h.object.scale.x) * k);
    });
  }

  /** The guide points at the next first move, until the person has decided once. */
  guide(time: number): void {
    // Only for a company's first sprint: after that, the person knows the moves.
    const step = live || company.sprints.length ? 'none' : guideStep(player.state, looked);
    let at: Vector3 | undefined;
    if (step === 'launch') {
      at = tasksPanel.firstLaunch(player.state)?.getWorldPosition(new Vector3());
    } else if (step === 'look') {
      const i = ROLES.indexOf(player.state.active ?? 'Architect');
      at = presences[i].p.group.localToWorld(new Vector3(0, 0.03, 0));
    } else if (step === 'decide' && !held) {
      at = task.group.getWorldPosition(new Vector3());
    }
    firstMoves.update(at, step === 'none' ? '' : GUIDE_TEXT[step], world.camera.getWorldPosition(new Vector3()), time);
  }

  /** The drop zones and the delivery in hand: release over a zone decides. */
  hands(time: number): void {
    // Only a delivery that waits for a person can be decided, and in live
    // mode the web app decides.
    const waiting = live ? undefined : awaitingDecision(player.state);
    const { anchor } = handPanels[1];
    // Level with where the delivery rests above the result panel.
    const y = anchor === 'bottom' ? 0.42 : 0.05;
    zones.approve.group.position.set(0.17, y, 0.03);
    zones.reject.group.position.set(-0.17, y, 0.03);
    const at = task.group.getWorldPosition(new Vector3());
    const approveAt = zones.approve.group.getWorldPosition(new Vector3());
    const rejectAt = zones.reject.group.getWorldPosition(new Vector3());
    const over = held ? dropOn(at, approveAt, rejectAt) : undefined;
    zones.approve.update(!!waiting, over === 'approve', time);
    zones.reject.update(!!waiting, over === 'reject', time);
    const now = taskEntity.hasComponent(Grabbed);
    if (held && !now && waiting) {
      const landed = dropOn(at, approveAt, rejectAt);
      if (landed) decide(waiting.id, landed === 'approve');
    }
    held = now;
  }

  update(delta: number, time: number): void {
    if (recenter && world.visibilityState.value !== VisibilityState.NonImmersive) {
      // Give the headset a moment to report its pose and the room's
      // surfaces, then lay the factory out on them.
      if ((this.waited += delta) > SURFACE_WAIT_S) {
        const { head, yaw } = headPose();
        arrange(head, yaw, surfaces.room());
        recenter = false;
        this.waited = 0;
      }
    } else if (recenter) {
      recenter = false;
    }
    // IWSDK passes seconds; a long frame (tab restored) is clamped.
    if (player.tick(Math.min(delta, 0.25) * 1000 * timeScale) > 0) dirty = true;
    closeIfDone();
    this.hear();
    this.meter(delta);
    // The lights and the task move every frame; the panels only on a change.
    for (const x of presences) {
      const now = player.state.agents[x.role].state;
      if (now !== x.state) {
        x.state = now;
        x.changedAt = time;
      }
      x.p.update(now, time, x.changedAt);
    }
    this.hands(time);
    this.look(delta);
    this.guide(time);
    task.update(taskTarget(), player.state.seals, delta, time, held);
    if (!dirty) return;
    dirty = false;
    notice.style.display = 'none';
    for (const p of panels) p.update(player.state, player.paused);
  }
}
world.registerSystem(RoomSystem);

if (live) {
  player.ingest({ type: 'task_state', taskId: 'live', state: 'in_progress' });
  connectLive(
    live,
    'live',
    (event) => {
      player.ingest(event);
      touch();
    },
    (status) => {
      player.ingest({ type: 'status', role: 'System', agent: 'Room', message: status, taskId: 'live' });
      touch();
    },
  );
}

// Browser tests drive the emulator's hands against the real scene; `?e2e`
// lets them find the room. Nothing else reads it.
if (new URLSearchParams(location.search).has('e2e')) {
  (window as unknown as { __room: unknown }).__room = {
    world,
    player,
    placement: () => placement,
    surfaces: () => surfaces.room(),
    token: () => task.group.getWorldPosition(new Vector3()),
    zones: () => ({
      approve: zones.approve.group.getWorldPosition(new Vector3()),
      reject: zones.reject.group.getWorldPosition(new Vector3()),
    }),
    held: () => held,
    open: () => dwell.open,
    guide: () => (live || company.sprints.length ? 'none' : guideStep(player.state, looked)),
    company: () => company,
    sound,
    restart,
    voice,
  };
}

// Director mode plays the video's script by itself in the emulator, for
// recording without a headset (see src/director.ts).
if (!live && new URLSearchParams(location.search).has('director')) {
  const labelled = (label: string): Object3D | undefined => {
    let found: Object3D | undefined;
    world.scene.traverse((o) => {
      const text = (o as unknown as { inputProperties?: { text?: unknown } }).inputProperties?.text;
      if (!found && text === label) found = o.parent ?? o;
    });
    return found;
  };
  const presenceAt = (i: number) => presences[i].p.group.getWorldPosition(new Vector3());
  void import('./director').then(({ direct }) =>
    direct({
      player,
      camera: world.camera,
      inXR: () => world.visibilityState.value === VisibilityState.Visible,
      token: () => task.group.getWorldPosition(new Vector3()),
      zone: (kind) => zones[kind].group.getWorldPosition(new Vector3()),
      launchButton: () => tasksPanel.firstLaunch(player.state),
      label: labelled,
      agent: (role) => presenceAt(ROLES.indexOf(role)),
      // The middle of the team, a little under the lights.
      wall: () => presenceAt(Math.floor(ROLES.length / 2)).add(new Vector3(0, -0.12, 0)),
      // The result panel's middle, wherever it stands.
      desk: () => handPanels[1].object.localToWorld(new Vector3(0, handPanels[1].anchor === 'bottom' ? 0.2 : -0.15, 0)),
      restart,
      newCompany,
      setSpeed: (times) => {
        timeScale = times;
      },
    }),
  );
}
