import assert from 'node:assert/strict';
import { mkdtemp, readFile, writeFile, rm, access } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { setTimeout } from 'node:timers/promises';
import { createPage } from '../create-page.mjs';
import { discoverSuites, testsDir, SUITE_SUFFIX } from './suites.mjs';

export const repoRoot = fileURLToPath(new URL('../../../', import.meta.url));
export const sample = path.join(repoRoot, 'sessions/01-fundamentals/cursus/demos/components.html');
export const sizes = [{ width: 1440, height: 900 }, { width: 1280, height: 720 }, { width: 390, height: 844 }];
// Every Node suite in this directory, by name ('pages' for pages.test.mjs), found by listing it.
export const suites = discoverSuites().map(file => path.basename(file, SUITE_SUFFIX));
export const read = relative => readFile(path.join(repoRoot, relative), 'utf8');

// `npm --prefix setup test` runs run-all.mjs, which runs every suite in this directory: a suite
// is collected by existing here, with nothing to register. This checks both halves for `name`.
export async function assertCollected(name) {
  const pkg = JSON.parse(await read('setup/package.json'));
  const [command, ...args] = pkg.scripts.test.trim().split(/\s+/);
  assert.deepEqual([command, ...args.map(arg => path.resolve(repoRoot, 'setup', arg))],
    ['node', path.join(testsDir, 'run-all.mjs')], 'npm --prefix setup test runs the suite discovery runner, unfiltered');
  assert.equal(suites.filter(suite => suite === name).length, 1, `npm --prefix setup test collects ${name}${SUITE_SUFFIX}`);
}

export async function scratch(t) {
  const dir = await mkdtemp(path.join(tmpdir(), 'cursus-components-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  return dir;
}

export async function fixture(t, body, script = '', kind = 'page') {
  const out = path.join(await scratch(t), 'fixture.html');
  await createPage({ kind, title: 'Component contract fixture', out });
  const html = await readFile(out, 'utf8');
  assert.match(html, /<main\b[\s\S]*?<\/main>/);
  await writeFile(out, html.replace(/<main\b[\s\S]*?<\/main>/,
    () => `<main id="content">${body}</main>`).replace('</body>', () => `<script>${script}</script></body>`));
  return out;
}

export async function openPage(t, chromium, options = {}) {
  const { file = sample, ...contextOptions } = options;
  await access(file); // Fail promptly with the missing deliverable's path.
  const browser = await chromium.launch();
  const errors = [];
  t.after(async () => { await browser.close(); assert.deepEqual(errors, [], 'offline page must have no runtime errors or remote requests'); });
  const context = await browser.newContext({ viewport: sizes[0], ...contextOptions });
  await context.route(/^(https?|wss?):/i, route => {
    errors.push(`remote request: ${route.request().url()}`);
    return route.abort();
  });
  const page = await context.newPage();
  page.setDefaultTimeout(4000);
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(pathToFileURL(file).href);
  return page;
}

export async function eventually(check, message = 'eventual state') {
  const until = Date.now() + 4000;
  for (;;) {
    try { return await check(); }
    catch (error) {
      if (Date.now() >= until) { error.message = `${message}: ${error.message}`; throw error; }
      await setTimeout(20);
    }
  }
}

export async function count(locator, expected) { assert.equal(await locator.count(), expected); }
export async function enabled(locator, expected = true) { assert.equal(await locator.isEnabled(), expected); }
export async function focused(locator) { assert.equal(await locator.evaluate(el => el === document.activeElement), true, 'expected focus transfer'); }
export async function textOf(locator) { return (await locator.textContent()).trim(); }

export async function predictRoots(page) {
  const roots = page.locator('[data-predict]');
  await count(roots, 2);
  let single, ticket;
  for (const root of await roots.all()) {
    const n = await root.locator('fieldset[data-predict-question]').count();
    if (n === 1) single = root;
    if (n === 2) ticket = root;
  }
  assert.ok(single && ticket, 'sample needs a one-question card and a two-question exit ticket');
  return { single, ticket };
}

export async function chooseAll(root, correct = true) {
  for (const q of await root.locator('[data-predict-question]').all()) {
    await q.locator(`input[type=radio]${correct ? '[data-correct]' : ':not([data-correct])'}`).first().check();
  }
}

export async function initialPredict(root) {
  await enabled(root.locator('[data-predict-lock]'), false);
  await enabled(root.locator('[data-predict-reveal]'), false);
  await enabled(root.locator('[data-predict-reset]'));
  await count(root.locator('input:checked'), 0);
  for (const input of await root.locator('input[type=radio]').all()) await enabled(input);
  for (const answer of await root.locator('[data-predict-answer]').all()) {
    assert.equal(await answer.evaluate(el => el.hidden), true);
    assert.equal(await answer.isVisible(), false);
    assert.equal(await answer.ariaSnapshot(), '', 'hidden answer must be absent from the accessibility tree');
    assert.doesNotMatch(await root.ariaSnapshot(), new RegExp(escapeRegExp(await textOf(answer))));
  }
  for (const result of await root.locator('[data-predict-result]').all()) assert.equal(await textOf(result), '');
}

export function escapeRegExp(value) { return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

export function stepperMarkup(id, n = 3, extra = '') {
  return `<section id="${id}" data-stepper><div data-step-stage tabindex="0" aria-label="${id} stage">
    ${Array.from({ length: n }, (_, i) => `<section data-step><h2>${id} step ${i + 1}</h2>${i === 0 ? extra : ''}</section>`).join('')}
    </div><div data-step-controls hidden><button data-step-prev>Previous</button><button data-step-next>Next</button>
    <button data-step-reset>Reset</button><span data-step-status aria-live="polite">Step 1 of ${n}</span></div></section>`;
}

export async function stepState(root, index, n) {
  assert.equal(await root.getAttribute('data-step-current'), String(index));
  assert.equal(await textOf(root.locator('[data-step-status]')), `Step ${index + 1} of ${n}`);
  assert.equal(await root.locator('[data-step-status]').getAttribute('aria-live'), 'polite');
  await enabled(root.locator('[data-step-prev]'), index > 0);
  await enabled(root.locator('[data-step-next]'), index < n - 1);
  await count(root.locator('[data-step]'), n);
  for (let i = 0; i < n; i++) {
    const step = root.locator('[data-step]').nth(i);
    assert.equal(await step.isVisible(), i === index);
    assert.equal(await step.evaluate(el => el.hidden), i !== index);
  }
}
