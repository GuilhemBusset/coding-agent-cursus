import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile, access } from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { chromium } from '../browser.mjs';
import { repoRoot, suites, eventually } from './component-helpers.mjs';

// Issue 41's public contracts: native labelled select, toolkit stepper, and
// data-step-type on each visible step. No page-specific functions or IDs.
const relative = 'sessions/01-fundamentals/cursus';
const file = path.join(repoRoot, relative, 'labs/agent-loop.html');
const fixtureFile = path.join(repoRoot, relative, 'fixtures/runs/agent-demos.json');
const url = pathToFileURL(file).href;

async function runs() {
  const fixture = JSON.parse(await readFile(fixtureFile, 'utf8'));
  assert.equal(fixture.schema, 1);
  assert.ok(Array.isArray(fixture.runs) && fixture.runs.length > 0, 'nonempty recorded catalog');
  assert.equal(new Set(fixture.runs.map(run => run.id)).size, fixture.runs.length);
  for (const demo of ['loop', 'plan', 'bomb']) {
    for (const cli of ['claude', 'codex']) {
      assert.ok(fixture.runs.some(run => run.demo === demo && run.cli === cli), `${demo}/${cli} fallback`);
    }
  }
  return fixture.runs;
}

async function open(t, { javaScriptEnabled = true } = {}) {
  await access(file);
  const browser = await chromium.launch();
  t.after(() => browser.close());
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, javaScriptEnabled });
  const errors = [];
  // A file:// viewer must never require a service, even on an instructor's host.
  await context.route('**/*', route => {
    const request = route.request().url();
    if (new URL(request).protocol !== 'file:') {
      errors.push(`non-file request: ${request}`);
      return route.abort();
    }
    return route.continue();
  });
  const page = await context.newPage();
  page.setDefaultTimeout(4000);
  page.on('pageerror', error => errors.push(`pageerror: ${error.message}`));
  page.on('console', message => { if (message.type() === 'error') errors.push(`console: ${message.text()}`); });
  page.on('websocket', socket => errors.push(`websocket: ${socket.url()}`));
  await page.goto(url);
  return { page, errors };
}

async function selectControl(page) {
  const select = page.getByRole('combobox');
  assert.equal(await select.count(), 1, 'one native run selector');
  assert.equal(await select.evaluate(el => el.tagName), 'SELECT');
  const name = await select.evaluate(el => el.getAttribute('aria-label') ||
    (el.getAttribute('aria-labelledby') || '').split(/\s+/).map(id => document.getElementById(id)?.textContent || '').join(' ').trim() ||
    [...(el.labels || [])].map(label => label.textContent).join(' ').trim());
  assert.ok(name, 'run selector has an accessible label');
  return select;
}

async function stepper(page) {
  const root = page.locator('[data-stepper]:visible');
  assert.equal(await root.count(), 1, 'one active step-through');
  return root;
}

async function stepAt(page, run, index) {
  const root = await stepper(page);
  await eventually(async () => {
    assert.equal((await root.locator('[data-step-status]').textContent()).trim(), `Step ${index + 1} of ${run.steps.length}`);
    assert.equal(await root.getAttribute('data-step-current'), String(index));
  }, `${run.id} step ${index + 1}`);
  const visible = root.locator('[data-step]:visible');
  assert.equal(await visible.count(), 1, 'only the current step is visible');
  const expected = run.steps[index];
  assert.equal(await visible.getAttribute('data-step-type'), expected.type, `${run.id} step type`);
  assert.ok((await visible.locator('pre').allTextContents()).includes(expected.text),
    `${run.id} step ${index + 1}: pre preserves exact normalized text, including whitespace`);
  const text = await visible.innerText();
  assert.ok(text.toLowerCase().replace(/[_-]/g, ' ').includes(expected.type.replaceAll('_', ' ')), 'visible type badge');
  if (expected.tool) assert.ok(text.includes(expected.tool), 'visible tool name');
  if (expected.exit_code != null) {
    assert.match(text, new RegExp(`(?:exit|return)(?:\\s+code)?\\s*[:=]?\\s*${expected.exit_code}\\b`, 'i'), 'visible tool exit code');
  }
  if (expected.is_error === true) assert.match(text, /error|failed|failure/i, 'visible error state');
  assert.equal(await root.locator('[data-step-prev]').isEnabled(), index > 0);
  assert.equal(await root.locator('[data-step-next]').isEnabled(), index < run.steps.length - 1);
  return root;
}

function usageScalars(value) {
  if (value && typeof value === 'object') return Object.values(value).flatMap(usageScalars);
  return value == null ? [] : [value];
}

async function runHeader(page, run) {
  const text = await page.locator('body').innerText();
  assert.match(text, /recorded,?\s+not illustrative/i);
  const cli = run.cli === 'claude' ? /Claude(?: Code)?/i : /Codex/i;
  assert.match(text, cli);
  const version = run.meta.cli_version.match(/\d+\.\d+\.\d+/)?.[0];
  assert.ok(version && text.includes(version), 'CLI version for the selected recording');
  for (const key of ['model', 'model_source', 'effort']) {
    assert.ok(text.includes(run.meta[key]), `${run.id}: visible ${key}`);
  }
  if (run.meta.started_utc) assert.ok(text.includes(run.meta.started_utc.slice(0, 10)), 'recording date');
  assert.match(text, /usage|tokens/i, 'reported usage header');
  // Thousands separators may be formatted for people. Counters are still the
  // reported ones, rather than an invented cost or cache-inclusive total.
  const ungrouped = text.replace(/(?<=\d)[,\u00a0\u202f](?=\d)/g, '');
  for (const value of usageScalars(run.usage)) {
    if (typeof value === 'number') assert.ok(ungrouped.includes(String(value)), `${run.id}: reported usage ${value}`);
  }
  assert.match(text, /not recorded/i, 'unknown per-step timing, usage or occupancy is labelled');
}

async function captureDetails(page, run) {
  if (!run.captures) return;
  const details = page.locator('details');
  let found = false;
  for (const detail of await details.all()) {
    const content = await detail.textContent();
    if (!Object.values(run.captures).every(capture => content.includes(capture))) continue;
    found = true;
    await detail.evaluate(el => { el.open = true; });
    assert.equal(await detail.isVisible(), true);
    const blocks = await detail.locator('pre').allTextContents();
    for (const capture of Object.values(run.captures)) {
      assert.ok(blocks.some(block => block.includes(capture)), `${run.id}: full before/after capture in disclosure`);
    }
  }
  assert.ok(found, `${run.id}: disclosure with both unchanged /context or /status captures`);
}

test('A2: browser suite is registered in both explicit suite inventories', async () => {
  assert.ok(suites.includes('agent-loop'));
  const pkg = JSON.parse(await readFile(path.join(repoRoot, 'setup/package.json'), 'utf8'));
  assert.ok(pkg.scripts.test.split(/\s+/).some(arg => path.resolve(repoRoot, 'setup', arg) ===
    path.join(repoRoot, 'tools/html-pages/tests/agent-loop.test.mjs')));
});

test('A2: every recorded stream steps through offline with exact fixture text', { timeout: 240000 }, async t => {
  const catalog = await runs();
  const { page, errors } = await open(t);
  const select = await selectControl(page);
  const options = await select.locator('option').evaluateAll(els => els.map(el => ({
    id: el.value, text: el.textContent.trim(), group: el.parentElement.tagName === 'OPTGROUP' ? el.parentElement.label : null,
  })));
  assert.deepEqual(options.map(o => o.id).sort(), catalog.map(run => run.id).sort(), 'exactly every run id, no omitted arms');
  const groups = new Map();
  for (const run of catalog) {
    const option = options.find(o => o.id === run.id);
    assert.ok(option.text && option.group, 'named option inside a labelled demo optgroup');
    if (groups.has(run.demo)) assert.equal(option.group, groups.get(run.demo), 'one group per demo');
    groups.set(run.demo, option.group);
  }
  assert.equal(new Set(groups.values()).size, 3, 'three separate demo groups');
  for (const run of catalog) {
    await select.selectOption(run.id);
    assert.equal(await select.inputValue(), run.id);
    assert.ok(run.steps.length > 0);
    await stepAt(page, run, 0);
    await runHeader(page, run);
    await captureDetails(page, run);
    for (let i = 0; i < run.steps.length; i++) {
      const root = await stepAt(page, run, i);
      if (i < run.steps.length - 1) await root.locator('[data-step-next]').click();
    }
    const root = await stepper(page);
    assert.equal(await root.locator('[data-step-next]').isDisabled(), true, `${run.id}: Next stops at the end`);
    await root.locator('[data-step-reset]').click();
    await stepAt(page, run, 0);
  }
  assert.deepEqual(errors, [], 'no console errors, runtime errors or non-file requests');
});

test('A2: every run can be linked directly, including arms and second rehearsals', { timeout: 120000 }, async t => {
  const { page, errors } = await open(t);
  for (const run of await runs()) {
    await page.goto(`${url}#run=${encodeURIComponent(run.id)}`);
    // A deep link is a fresh page load; handling same-document hash changes
    // after load is not part of this issue's navigation contract.
    await page.reload();
    const select = await selectControl(page);
    await eventually(async () => assert.equal(await select.inputValue(), run.id), `hash preselects ${run.id}`);
    await stepAt(page, run, 0);
  }
  assert.deepEqual(errors, []);
});

test('A2: toolkit keyboard navigation resets correctly after switching recordings', async t => {
  const catalog = await runs();
  const { page, errors } = await open(t);
  const select = await selectControl(page);
  for (const run of [catalog.find(r => r.cli === 'codex' && r.steps.length > 2),
    catalog.find(r => r.cli === 'claude' && r.steps.length > 2)]) {
    assert.ok(run);
    await select.selectOption(run.id);
    let root = await stepAt(page, run, 0);
    const stage = root.locator('[data-step-stage]');
    await stage.focus();
    await stage.press('End');
    await stepAt(page, run, run.steps.length - 1);
    await stage.press('Home');
    root = await stepAt(page, run, 0);
    await root.locator('[data-step-next]').click();
    await stepAt(page, run, 1);
    await root.locator('[data-step-prev]').click();
    await stepAt(page, run, 0);
  }
  assert.deepEqual(errors, []);
});

test('A2: without JavaScript the terminal replay fallback is readable offline', async t => {
  const { page, errors } = await open(t, { javaScriptEnabled: false });
  const text = await page.locator('body').innerText();
  assert.match(text, /uv run agent_demo\.py replay\s+\S+[\s\S]*--via/);
  assert.equal(await page.locator('noscript:visible').count() > 0, true);
  assert.deepEqual(errors, []);
});
