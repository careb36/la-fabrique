#!/usr/bin/env node
/**
 * The render budget, measured without a headset: opens the built room in
 * Chromium with the Quest 3 emulator, enters XR in its synthetic office,
 * runs the demo to its busiest moment and reads the renderer's per-frame
 * counts. Fails when the room draws more than its budget.
 *
 *   npm run build && npx vite preview --port 4173 &
 *   node scripts/render-budget.cjs https://localhost:4173/?e2e
 *
 * Needs Playwright with Chromium (or CHROMIUM_PATH pointing at one). Frame rate in a software-rendered browser
 * says nothing about a headset, so this checks what does carry over: how
 * many draw calls and triangles each frame asks for.
 */
const { chromium } = require('playwright');

// Keep in step with RENDER_BUDGET in src/perf.ts.
const BUDGET = { drawCalls: 200, triangles: 150_000 };

const url = process.argv[2] ?? 'https://localhost:4173/?e2e';

(async () => {
  // CHROMIUM_PATH points at a Chromium of your own when Playwright's is not installed.
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined, args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 }, ignoreHTTPSErrors: true });
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto(url);
  await page.waitForFunction(() => window.__room, null, { timeout: 30_000 });
  await page.waitForTimeout(4000);
  // The emulator's Enter XR button sits at the top of the page.
  await page.mouse.click(640, 27);
  await page.waitForTimeout(4000);
  const counts = await page.evaluate(async () => {
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const { world, player } = window.__room;
    const peak = async () => {
      let calls = 0;
      let triangles = 0;
      for (let i = 0; i < 10; i++) {
        await sleep(100);
        calls = Math.max(calls, world.renderer.info.render.calls);
        triangles = Math.max(triangles, world.renderer.info.render.triangles);
      }
      return { calls, triangles };
    };
    const idle = await peak();
    for (const id of Object.keys(player.state.tasks)) player.launch(id);
    for (let i = 0; i < 40; i++) {
      player.tick(500);
      await sleep(10);
    }
    return { idle, busy: await peak(), inXR: world.renderer.xr.isPresenting };
  });
  await browser.close();
  console.log(JSON.stringify(counts));
  const over = counts.busy.calls > BUDGET.drawCalls || counts.busy.triangles > BUDGET.triangles;
  if (!counts.inXR) console.error('Did not enter XR: the counts are for the desktop view.');
  if (errors.length) console.error(errors.join('\n'));
  if (over) console.error(`Over budget: ${JSON.stringify(BUDGET)}`);
  process.exit(over || !counts.inXR || errors.length ? 1 : 0);
})();
