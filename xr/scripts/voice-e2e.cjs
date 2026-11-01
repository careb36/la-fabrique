#!/usr/bin/env node
/**
 * The on-device recognizer, end to end, in a headless Chromium: a WAV is
 * the microphone, the page runs Whisper in its worker, and the room obeys.
 *
 *   npm run build
 *   node scripts/voice-e2e.cjs bench/audio/es-dora/es-pause-1.wav pause [tiny]
 *
 * The WAV (16-bit PCM) plays as the fake microphone, in a loop. The script
 * serves `dist/`, opens the room with `?e2e&stt=<size>`, starts voice
 * through the e2e hook and waits for the effect named: `pause` (the room
 * pauses), `approve` or `reject` (a confirmation is asked, so the effect is
 * the question), or any text the Room panel's voice line must contain. It
 * prints what was heard and said, and exits 0 only when the effect came.
 * The model is downloaded on each run (the browser profile is new).
 */

const { spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { chromium } = require('playwright');

const [wav, effect = 'pause', size = 'tiny'] = process.argv.slice(2);
if (!wav) {
  console.error('usage: node scripts/voice-e2e.cjs <wav> [pause|approve|reject|<text>] [tiny|base|small]');
  process.exit(2);
}

const ROOT = path.resolve(__dirname, '..');
const PORT = 4175;
/** Silence after the phrase: the fake microphone loops the file, and a phrase needs an end. */
const TAIL_SECONDS = 1.5;

/**
 * The WAV with silence appended (16-bit PCM, any rate). Chromium plays the
 * fake microphone's file in a loop; without a pause between repetitions the
 * voice detector hears one endless phrase.
 */
function withTail(file) {
  const bytes = fs.readFileSync(file);
  if (bytes.toString('ascii', 0, 4) !== 'RIFF' || bytes.readUInt16LE(34) !== 16) throw new Error(`${file}: a 16-bit PCM WAV is needed`);
  const channels = bytes.readUInt16LE(22);
  const rate = bytes.readUInt32LE(24);
  const silence = Buffer.alloc(Math.round(TAIL_SECONDS * rate) * channels * 2);
  // The data chunk is the last one in these files; sizes are patched for the new length.
  const out = Buffer.concat([bytes, silence]);
  out.writeUInt32LE(out.length - 8, 4);
  const dataAt = bytes.indexOf('data', 12, 'ascii');
  out.writeUInt32LE(out.length - dataAt - 8, dataAt + 4);
  const target = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'voice-e2e-')), path.basename(file));
  fs.writeFileSync(target, out);
  return target;
}

async function main() {
  const mic = withTail(path.resolve(wav));
  const preview = spawn('npx', ['vite', 'preview', '--port', String(PORT), '--strictPort'], { cwd: ROOT, stdio: 'pipe' });
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('vite preview did not start')), 60_000);
    preview.stdout.on('data', (chunk) => {
      if (String(chunk).includes(String(PORT))) {
        clearTimeout(timer);
        resolve();
      }
    });
    preview.on('exit', (code) => reject(new Error(`vite preview exited with ${code}`)));
  });
  const browser = await chromium.launch({
    // A Chrome of your own, when Playwright's download is not wanted.
    executablePath: process.env.CHROMIUM_PATH || undefined,
    args: [
      '--use-gl=angle',
      '--use-angle=swiftshader',
      '--enable-unsafe-swiftshader',
      '--use-fake-ui-for-media-stream',
      '--use-fake-device-for-media-stream',
      `--use-file-for-fake-audio-capture=${mic}`,
      '--autoplay-policy=no-user-gesture-required',
    ],
  });
  // The preview is HTTPS with a local certificate (the SDK's dev plugin), as WebXR wants.
  const context = await browser.newContext({ permissions: ['microphone'], ignoreHTTPSErrors: true });
  const page = await context.newPage();
  const log = [];
  page.on('console', (m) => {
    if (m.type() === 'error' || m.type() === 'warning') log.push(`[${m.type()}] ${m.text()}`);
  });
  page.on('pageerror', (e) => log.push(`[pageerror] ${e.message}`));
  // The context sees the worker's requests too.
  context.on('response', (r) => {
    if (r.status() >= 400) log.push(`[http ${r.status()}] ${r.url()}`);
  });
  context.on('requestfailed', (r) => log.push(`[failed] ${r.url()} ${r.failure()?.errorText ?? ''}`));
  await page.goto(`https://localhost:${PORT}/?e2e&stt=${size}&lang=es`);
  await page.waitForFunction(() => !!window.__room, null, { timeout: 60_000 });
  // Every exchange the session has, for the report.
  await page.evaluate(() => {
    window.__voiceLog = [];
    const session = window.__room.voice;
    const original = session.o.onEvent;
    session.o.onEvent = (e) => {
      window.__voiceLog.push(`${e.kind}: ${e.text}`);
      original?.(e);
    };
    session.start();
  });
  const started = Date.now();
  const deadline = started + 240_000;
  let ok = false;
  while (Date.now() < deadline && !ok) {
    await page.waitForTimeout(1000);
    ok = await page.evaluate((want) => {
      const room = window.__room;
      const events = window.__voiceLog;
      const said = events.filter((e) => e.startsWith('said: ')).map((e) => e.slice(6));
      if (want === 'pause') return room.player.paused;
      if (want === 'approve') return said.some((s) => /apruebo|approve/i.test(s));
      if (want === 'reject') return said.some((s) => /devuelvo|send .* back/i.test(s));
      return said.some((s) => s.toLowerCase().includes(want.toLowerCase()));
    }, effect);
  }
  const events = await page.evaluate(() => window.__voiceLog);
  console.log(`effect "${effect}": ${ok ? 'came' : 'did not come'} after ${((Date.now() - started) / 1000).toFixed(0)} s`);
  console.log('exchanges:');
  for (const e of events) console.log(`  ${e}`);
  if (log.length) {
    console.log('console:');
    for (const l of log.slice(0, 30)) console.log(`  ${l}`);
  }
  await browser.close();
  preview.kill();
  process.exit(ok ? 0 : 1);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
