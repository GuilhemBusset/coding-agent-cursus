import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile, readdir, access } from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { chromium } from '../browser.mjs';
import { repoRoot, eventually, assertCollected } from './component-helpers.mjs';

// Issue 41's public contracts: native labelled select, toolkit stepper, and
// data-step-type on each visible step. No page-specific functions or IDs.
// Issue 47 adds the agent-run/1 task recordings, a gather/act/verify lane
// ([data-lane-phase] with aria-current), a usage meter ([data-usage-meter]),
// toolkit predict-and-reveal on marked tool calls, and a side-by-side toggle.
const relative = 'sessions/01-fundamentals/cursus';
const file = path.join(repoRoot, relative, 'labs/agent-loop.html');
const fixtureFile = path.join(repoRoot, relative, 'fixtures/runs/agent-demos.json');
const recordingsDir = path.join(repoRoot, relative, 'fixtures/runs');
const TASKS = ['flipped-sense', 'impossible', 'context-bomb'];
const url = pathToFileURL(file).href;

async function catalogRuns() {
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

// Every committed agent-run/1 recording, with the display text the page embeds
// (the pytest proves that block matches these files, clipped at 1,200 characters).
async function recordingRuns() {
  const html = await readFile(file, 'utf8');
  const block = html.match(/<script type="application\/json" id="agent-run-recordings"[^>]*>([\s\S]*?)<\/script>/);
  assert.ok(block, 'inline agent-run recordings');
  const inline = new Map(JSON.parse(block[1]).runs.map(run => [run.meta.run, run]));
  const names = (await readdir(recordingsDir)).filter(name => /-(claude|codex)\.json$/.test(name)).sort();
  assert.equal(names.length, TASKS.length * 2, 'three tasks, two harnesses');
  const out = [];
  for (const name of names) {
    const fixture = JSON.parse(await readFile(path.join(recordingsDir, name), 'utf8'));
    assert.equal(fixture.schema, 'agent-run/1');
    const shown = inline.get(fixture.meta.run);
    assert.ok(shown, `${fixture.meta.run} is embedded`);
    assert.equal(shown.steps.length, fixture.steps.length, `${fixture.meta.run}: every step embedded`);
    out.push({
      id: fixture.meta.run, task: fixture.meta.task, cli: fixture.meta.vendor, recording: true, totals: fixture.totals,
      meta: { cli_version: fixture.meta.cli_version, model: fixture.meta.model, effort: fixture.meta.effort },
      steps: fixture.steps.map((step, i) => ({ ...step, text: shown.steps[i].text })),
    });
  }
  assert.deepEqual(out.map(run => run.task).sort(), [...TASKS, ...TASKS].sort());
  return out;
}

async function runs() {
  return [...await recordingRuns(), ...await catalogRuns()];
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

async function laneOf(scope) {
  return scope.locator('[data-lane-phase][aria-current="step"]').evaluateAll(els => els.map(el => el.getAttribute('data-lane-phase')));
}

// A marked step hides its call (and the lane's phase) until the toolkit reveal.
async function revealPrediction(panel, step, run, index) {
  const predict = step.locator('[data-predict]');
  if (!await predict.count()) return false;
  assert.equal(run.steps[index].type, 'tool_call', 'predictions sit on tool calls');
  const answer = predict.locator('[data-predict-answer]');
  if (await answer.isHidden()) {
    assert.match(await predict.locator('legend').innerText(), /what will it run next\?/i);
    assert.ok(!(await step.innerText()).includes(run.steps[index].text.trim() || '\u0000'), 'call hidden before reveal');
    assert.deepEqual(await laneOf(panel), [], 'phase hidden before reveal');
    const radios = predict.locator('input[type="radio"]');
    assert.equal(await radios.count(), 3);
    await radios.first().check();
    await predict.locator('[data-predict-lock]').click();
    await predict.locator('[data-predict-reveal]').click();
    await eventually(async () => assert.equal(await answer.isVisible(), true), 'answer revealed');
    assert.match(await predict.locator('[data-predict-result]').innerText(), /^(Correct\.|Not quite\.)/);
  }
  const correct = await predict.locator('input[data-correct]').getAttribute('value');
  assert.deepEqual(await laneOf(panel), [correct], 'the lane shows the revealed phase');
  return true;
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
  const panel = page.locator('[data-run-panel]:visible', { has: root });
  await revealPrediction(panel, visible, run, index);
  const lit = await laneOf(panel);
  assert.equal(lit.length, 1, `${run.id} step ${index + 1}: one lit lane phase`);
  assert.ok(['gather', 'act', 'verify'].includes(lit[0]));
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
  if (run.recording) {
    const ungrouped = text.replace(/(?<=\d)[,\u00a0\u202f](?=\d)/g, '');
    assert.ok(text.includes(run.meta.cli_version.match(/\d+\.\d+\.\d+/)[0]) && text.includes(run.meta.model) && text.includes(run.meta.effort));
    for (const value of Object.values(run.totals)) if (value != null) assert.ok(ungrouped.includes(String(value)), `${run.id}: total ${value}`);
    return;
  }
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

test('A2: browser suite is collected by npm --prefix setup test', async () => {
  await assertCollected('agent-loop');
});

// The tokens and context the meter must show at a step, from the fixture alone.
function expectedUsage(run, index) {
  const reported = run.steps.slice(0, index + 1).filter(step => step.tokens && step.tokens.input != null);
  if (!reported.length) return null;
  return { context: reported.at(-1).tokens.input, sent: reported.reduce((sum, step) => sum + step.tokens.input, 0) };
}

async function meterAt(page, run, index) {
  const meter = page.locator('[data-run-panel]:visible [data-usage-meter]');
  assert.equal(await meter.count(), 1, 'one meter per visible run');
  const text = (await meter.innerText()).replace(/(?<=\d)[,\u00a0\u202f](?=\d)/g, '');
  const perStep = run.recording && run.steps.some(step => step.tokens && step.tokens.input != null);
  if (!perStep) {
    assert.match(text, /not recorded/i, `${run.id}: the meter says per-step usage is not recorded`);
    return;
  }
  const want = expectedUsage(run, index);
  if (!want) return;
  assert.ok(text.includes(String(want.context)), `${run.id} step ${index + 1}: context ${want.context}`);
  assert.ok(text.includes(String(want.sent)), `${run.id} step ${index + 1}: input so far ${want.sent}`);
  assert.equal(Number(await meter.locator('meter').getAttribute('value')), Number(await meter.locator('meter').evaluate(el => el.value)));
  assert.equal(await meter.locator('meter').evaluate(el => el.value), want.context);
}

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
    const key = run.recording ? 'task' : run.demo;
    if (groups.has(key)) assert.equal(option.group, groups.get(key), 'one group per demo');
    groups.set(key, option.group);
  }
  assert.equal(new Set(groups.values()).size, 4, 'one group for the tasks, one per demo');
  for (const run of catalog) {
    await select.selectOption(run.id);
    assert.equal(await select.inputValue(), run.id);
    assert.ok(run.steps.length > 0);
    await stepAt(page, run, 0);
    await runHeader(page, run);
    await captureDetails(page, run);
    let marked = 0;
    for (let i = 0; i < run.steps.length; i++) {
      const root = await stepAt(page, run, i);
      await meterAt(page, run, i);
      marked += await root.locator('[data-step]:visible [data-predict]').count();
      if (i < run.steps.length - 1) await root.locator('[data-step-next]').click();
    }
    if (run.steps.some(step => step.type === 'tool_call')) assert.ok(marked > 0, `${run.id}: at least one prediction point`);
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
    await meterAt(page, run, 0);
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

// Phase spot checks from the fixtures: a change is act, a test run after it is verify,
// and a test run before any change is gather (it shows the failure).
test('D2: the lane reads gather, act and verify off the real calls', { timeout: 120000 }, async t => {
  const all = await runs();
  const { page, errors } = await open(t);
  const select = await selectControl(page);
  const checked = [];
  for (const run of all.filter(r => r.task === 'flipped-sense' || r.demo === 'loop')) {
    await select.selectOption(run.id);
    const root = await stepper(page);
    const calls = run.steps.map((step, i) => ({ step, i })).filter(({ step }) => step.type === 'tool_call');
    const text = ({ step }) => JSON.stringify(step.input ?? step.text ?? '');
    const edit = calls.find(({ step }) => /^(Edit|file_change)$/.test(step.tool));
    const tests = calls.filter(call => /pytest/.test(text(call)));
    assert.ok(edit && tests.length >= 2, `${run.id}: an edit and two test runs`);
    const before = tests.filter(call => call.i < edit.i);
    const after = tests.filter(call => call.i > edit.i);
    const want = [[calls[0], 'gather'], [edit, 'act'], ...before.map(c => [c, 'gather']), [after[0], 'verify']];
    for (const [call, phase] of want) {
      await root.locator('[data-step-stage]').focus();
      await root.locator('[data-step-stage]').press('Home');
      for (let i = 0; i < call.i; i++) await root.locator('[data-step-next]').click();
      await stepAt(page, run, call.i);
      assert.deepEqual(await laneOf(page.locator('[data-run-panel]:visible')), [phase], `${run.id} step ${call.i + 1}`);
    }
    checked.push(run.id);
  }
  assert.ok(checked.length >= 6, 'both harnesses, task and demo runs');
  assert.deepEqual(errors, []);
});

test('D4: side by side shows the same task in Claude Code and Codex, each stepping on its own', { timeout: 120000 }, async t => {
  const all = await recordingRuns();
  const { page, errors } = await open(t);
  const select = await selectControl(page);
  const toggle = page.getByRole('checkbox', { name: /side by side/i });
  for (const task of TASKS) {
    const pair = Object.fromEntries(['claude', 'codex'].map(cli => [cli, all.find(r => r.task === task && r.cli === cli)]));
    for (const first of ['claude', 'codex']) {
      await select.selectOption(pair[first].id);
      await toggle.check();
      const columns = page.locator('[data-run-panel]:visible');
      assert.equal(await columns.count(), 2, `${task}: two columns`);
      assert.equal(await page.locator('[data-stepper]:visible').count(), 2);
      const byCli = {};
      for (const cli of ['claude', 'codex']) {
        byCli[cli] = page.locator(`[data-run-panel][data-cli="${cli}"]:visible`);
        assert.equal(await byCli[cli].count(), 1);
        assert.equal(await byCli[cli].getAttribute('data-run-panel'), pair[cli].id);
        assert.match(await byCli[cli].locator('.run-title, h3').first().innerText(), cli === 'claude' ? /Claude Code/ : /Codex/);
        assert.equal((await byCli[cli].locator('[data-step-status]').innerText()).trim(), `Step 1 of ${pair[cli].steps.length}`);
      }
      const other = first === 'claude' ? 'codex' : 'claude';
      await byCli[other].locator('[data-step-next]').click();
      assert.equal((await byCli[other].locator('[data-step-status]').innerText()).trim(), `Step 2 of ${pair[other].steps.length}`);
      assert.equal((await byCli[first].locator('[data-step-status]').innerText()).trim(), `Step 1 of ${pair[first].steps.length}`);
      const boxes = await Promise.all(['claude', 'codex'].map(cli => byCli[cli].boundingBox()));
      assert.ok(boxes[0].x + boxes[0].width <= boxes[1].x + 1, `${task}: Claude Code left of Codex at desktop width`);
      await toggle.uncheck();
      assert.equal(await page.locator('[data-stepper]:visible').count(), 1, 'off again: one stepper');
    }
  }
  assert.deepEqual(errors, []);
});
