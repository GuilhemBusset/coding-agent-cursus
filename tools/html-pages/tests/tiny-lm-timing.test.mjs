import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { cpus, platform, release } from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { chromium } from '../browser.mjs';
import { repoRoot, suites } from './component-helpers.mjs';

const file = path.join(repoRoot, 'sessions/01-fundamentals/cursus/labs/tiny-lm.html');

test('A3: timing suite is registered in the shared suites and npm test', async () => {
  assert.ok(suites.includes('tiny-lm-timing'), 'register component-helpers timing suite');
  const pkg = JSON.parse(await readFile(path.join(repoRoot, 'setup/package.json'), 'utf8'));
  assert.ok(pkg.scripts.test.split(/\s+/).includes('../tools/html-pages/tests/tiny-lm-timing.test.mjs'),
    'register timing suite in setup/package.json scripts.test');
});

// Relocated strict host proxy: no retries, discarded outliers or aggregate timing
// budget. Physical 2020-laptop evidence remains a separate owner obligation.
test('A3: five cold first-painted-token trials at native speed and 4x CPU proxy are under one second', async t => {
  const browser = await chromium.launch();
  t.after(() => browser.close());
  const trials = [];
  for (const rate of [1, 4]) {
    for (let trial = 1; trial <= 5; trial++) {
      let context, timing;
      const requests = [], errors = [];
      try {
        context = await browser.newContext({ offline: true, viewport: { width: 1280, height: 720 } });
        const page = await context.newPage();
        page.on('request', request => requests.push(request.url()));
        page.on('pageerror', error => errors.push(`page error: ${error.message}`));
        const cdp = await context.newCDPSession(page);
        await cdp.send('Emulation.setCPUThrottlingRate', { rate });
        await page.addInitScript(() => {
          window.__firstTokenTiming = null;
          // Schedule the click from DOMContentLoaded, after all page listeners
          // have run. A microtask here can precede later DCL listeners.
          document.addEventListener('DOMContentLoaded', () => setTimeout(() => {
            const step = [...document.querySelectorAll('button')].find(el => /^step\b/i.test((el.getAttribute('aria-label') || el.textContent).trim()));
            if (!step || step.disabled) { window.__firstTokenTiming = { error: 'Step not ready at DOMContentLoaded' }; return; }
            const start = performance.now();
            const observe = () => {
              const chip = document.querySelector('button[data-tlm-token]');
              if (!chip || !chip.getClientRects().length || getComputedStyle(chip).visibility === 'hidden') { requestAnimationFrame(observe); return; }
              // A second animation frame crosses a paint opportunity.
              requestAnimationFrame(() => { window.__firstTokenTiming = { coldMs: performance.now(), stepMs: performance.now() - start }; });
            };
            step.click();
            requestAnimationFrame(observe);
          }, 0), { once: true });
        });
        await page.goto(pathToFileURL(file).href, { waitUntil: 'domcontentloaded' });
        await page.waitForFunction(() => window.__firstTokenTiming !== null, null, { timeout: 5000 });
        timing = await page.evaluate(() => window.__firstTokenTiming);
        if (timing.error) errors.push(timing.error);
      } catch (error) {
        errors.push(error.message || String(error));
      } finally {
        try { await context?.close(); }
        catch (error) { errors.push(`context close: ${error.message || String(error)}`); }
      }
      if (!requests.length) errors.push('no file navigation request observed');
      const nonFileRequests = requests.filter(url => !url.startsWith('file://'));
      if (nonFileRequests.length) errors.push(`non-file requests: ${JSON.stringify(nonFileRequests)}`);
      trials.push(errors.length
        ? { rate, trial, error: errors.join('; ') }
        : { rate, trial, coldMs: timing.coldMs, stepMs: timing.stepMs });
    }
  }
  // Always publish all ten outcomes before asserting, including failed trials.
  t.diagnostic(JSON.stringify({ cpu: cpus()[0]?.model, os: `${platform()} ${release()}`, browser: browser.version(), trials }));
  t.diagnostic('Host/4x measurements are a proxy only. A3 requires separate owner evidence from an identified 2020 laptop.');
  const failures = [];
  for (const { rate, trial, error, coldMs, stepMs } of trials) {
    const label = `rate ${rate}, trial ${trial}`;
    if (error) {
      failures.push(`${label}: ${error}`);
      continue;
    }
    if (!(coldMs > 0 && coldMs < 1000)) failures.push(`${label}: cold ${coldMs} ms (required > 0 and < 1000 ms)`);
    if (!(stepMs > 0 && stepMs < 1000)) failures.push(`${label}: Step ${stepMs} ms (required > 0 and < 1000 ms)`);
  }
  assert.deepEqual(failures, [], 'every native and 4x trial must satisfy the offline first-token budget');
});
