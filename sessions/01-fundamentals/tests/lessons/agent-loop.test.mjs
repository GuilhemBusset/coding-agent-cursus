import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import { readFile, readdir } from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { chromium } from '../../../../tools/html-pages/browser.mjs';
import { repoRoot, eventually } from '../../../../tools/html-pages/tests/component-helpers.mjs';

// The agent-loop lab replays the recorded runs in cursus/fixtures/runs. The fixtures themselves,
// their sanitizing and the inline copy in the page are the session pytest's
// (test_agent_loop_recordings.py, test_agent_loop_replay.py). This suite proves the page renders
// every recorded step, and that its controls, lane, meter and side-by-side view work.
const cursus = path.join(repoRoot, 'sessions/01-fundamentals/cursus');
const file = path.join(cursus, 'labs/agent-loop.html');
const runsDir = path.join(cursus, 'fixtures/runs');
const url = pathToFileURL(file).href;
const ungroup = text => text.replace(/(?<=\d)[,\u00a0\u202f](?=\d)/g, '');

// Every run the page offers, as the page should show it: the agent-run/1 task recordings (with
// the clipped text the page embeds) and the demo catalog.
async function loadRuns() {
  const html = await readFile(file, 'utf8');
  const block = html.match(/<script type="application\/json" id="agent-run-recordings"[^>]*>([\s\S]*?)<\/script>/);
  assert.ok(block, 'inline agent-run recordings');
  const inline = new Map(JSON.parse(block[1]).runs.map(run => [run.meta.run, run]));
  const recordings = [];
  for (const name of (await readdir(runsDir)).filter(n => /-(claude|codex)\.json$/.test(n)).sort()) {
    const fixture = JSON.parse(await readFile(path.join(runsDir, name), 'utf8'));
    const shown = inline.get(fixture.meta.run);
    assert.ok(shown, `${fixture.meta.run} is embedded`);
    recordings.push({ id: fixture.meta.run, task: fixture.meta.task, cli: fixture.meta.vendor, recording: true,
      meta: fixture.meta, totals: fixture.totals, steps: fixture.steps.map((step, i) => ({ ...step, text: shown.steps[i]?.text })) });
  }
  const catalog = JSON.parse(await readFile(path.join(runsDir, 'agent-demos.json'), 'utf8')).runs;
  return [...recordings, ...catalog];
}

let browser, page, runs;
const errors = [];
before(async () => {
  runs = await loadRuns();
  browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  // A file:// viewer must never require a service, even on an instructor's host.
  await context.route('**/*', route => {
    if (new URL(route.request().url()).protocol === 'file:') return route.continue();
    errors.push(`non-file request: ${route.request().url()}`);
    return route.abort();
  });
  page = await context.newPage();
  page.setDefaultTimeout(4000);
  page.on('pageerror', error => errors.push(`pageerror: ${error.message}`));
  page.on('console', message => { if (message.type() === 'error') errors.push(`console: ${message.text()}`); });
  await page.goto(url);
});
after(() => browser?.close());

const select = () => page.getByRole('combobox');
const visiblePanel = () => page.locator('[data-run-panel]:visible');
const laneOf = scope => scope.locator('[data-lane-phase][aria-current="step"]')
  .evaluateAll(els => els.map(el => el.getAttribute('data-lane-phase')));
const byId = id => runs.find(run => run.id === id);

test('every recorded run is offered and renders each step with its exact text and loop phase', async () => {
  const rendered = await page.evaluate(() => ({
    options: [...document.querySelectorAll('select option')].map(o => o.value),
    panels: Object.fromEntries([...document.querySelectorAll('[data-run-panel]')].map(panel => [panel.dataset.runPanel,
      [...panel.querySelectorAll('[data-step]')].map(step => ({
        type: step.dataset.stepType, phase: step.dataset.phase, text: step.querySelector('pre')?.textContent,
      }))])),
  }));
  assert.deepEqual(rendered.options.sort(), runs.map(run => run.id).sort(), 'exactly every run id');
  for (const run of runs) {
    const steps = rendered.panels[run.id];
    assert.equal(steps?.length, run.steps.length, `${run.id}: every step rendered`);
    steps.forEach((step, i) => {
      assert.equal(step.type, run.steps[i].type, `${run.id} step ${i + 1} type`);
      assert.equal(step.text, run.steps[i].text, `${run.id} step ${i + 1}: exact text, whitespace included`);
    });
  }
  // Phase spot checks off the real calls: the first call gathers, a change acts, a test run before
  // it gathers (it shows the failure) and the first test run after it verifies.
  const checked = runs.filter(run => run.task === 'flipped-sense' || run.demo === 'loop').map(run => {
    const calls = run.steps.map((step, i) => ({ step, i })).filter(({ step }) => step.type === 'tool_call');
    const text = ({ step }) => JSON.stringify(step.input ?? step.text ?? '');
    const edit = calls.find(({ step }) => /^(Edit|file_change)$/.test(step.tool));
    const tests = calls.filter(call => /pytest/.test(text(call)));
    assert.ok(edit && tests.length >= 2, `${run.id}: an edit and two test runs`);
    const want = [[calls[0], 'gather'], [edit, 'act'], ...tests.filter(c => c.i < edit.i).map(c => [c, 'gather']),
      [tests.find(c => c.i > edit.i), 'verify']];
    for (const [call, phase] of want) assert.equal(rendered.panels[run.id][call.i].phase, phase, `${run.id} step ${call.i + 1}`);
    return run.id;
  });
  assert.ok(checked.length >= 6, 'both harnesses, task and demo runs');
  assert.deepEqual(errors, []);
});

// One step of the visible run: status, the one visible step, its prediction, lane and meter.
async function stepAt(run, index) {
  const panel = visiblePanel();
  const root = panel.locator('[data-stepper]');
  await eventually(async () => {
    assert.equal((await root.locator('[data-step-status]').textContent()).trim(), `Step ${index + 1} of ${run.steps.length}`);
  }, `${run.id} step ${index + 1}`);
  const step = root.locator('[data-step]:visible');
  assert.equal(await step.count(), 1, 'only the current step is visible');
  const expected = run.steps[index];
  assert.equal(await step.getAttribute('data-step-type'), expected.type);
  const predict = step.locator('[data-predict]');
  // A prediction point hides the call and the lane's phase until the reveal (which then stays).
  if (await predict.count() && await predict.locator('[data-predict-answer]').isHidden()) {
    assert.equal(expected.type, 'tool_call', 'predictions sit on tool calls');
    assert.ok(!expected.text || !(await step.innerText()).includes(expected.text), 'call hidden before reveal');
    assert.deepEqual(await laneOf(panel), [], 'phase hidden before reveal');
    await predict.locator('input[type="radio"]').first().check();
    await predict.locator('[data-predict-lock]').click();
    await predict.locator('[data-predict-reveal]').click();
    assert.equal(await predict.locator('[data-predict-answer]').isVisible(), true);
  }
  assert.deepEqual(await laneOf(panel), [await step.getAttribute('data-phase')], 'the lane lights the step\'s phase');
  assert.ok((await step.locator('pre').allTextContents()).includes(expected.text), 'exact step text');
  const text = await step.innerText();
  if (expected.tool) assert.ok(text.includes(expected.tool), 'tool name');
  if (expected.exit_code != null) assert.match(text, new RegExp(`exit code ${expected.exit_code}\\b`), 'tool exit code');
  // The meter: the latest call's input is the context; the inputs add up to what was sent so far.
  const reported = run.steps.slice(0, index + 1).filter(s => s.tokens?.input != null);
  if (reported.length) {
    const meter = panel.locator('[data-usage-meter]');
    const context = reported.at(-1).tokens.input, sent = reported.reduce((total, s) => total + s.tokens.input, 0);
    assert.equal(await meter.locator('meter').evaluate(el => el.value), context);
    const shown = ungroup(await meter.innerText());
    assert.ok(shown.includes(String(context)) && shown.includes(`${sent} tokens`), `step ${index + 1}: context ${context}, sent ${sent}`);
  }
  assert.equal(await root.locator('[data-step-prev]').isEnabled(), index > 0);
  assert.equal(await root.locator('[data-step-next]').isEnabled(), index < run.steps.length - 1);
  return root;
}

test('a task recording replays end to end: steps, predictions, lane, usage meter, keyboard and reset', async () => {
  const run = byId('flipped-sense-claude');
  assert.ok(run.steps.some(s => s.tokens?.input != null), 'a recording with per-call usage');
  await select().selectOption(run.id);
  const header = ungroup(await page.locator('body').innerText());
  for (const value of [run.meta.cli_version.match(/\d+\.\d+\.\d+/)[0], run.meta.model, run.meta.effort,
    ...Object.values(run.totals).filter(v => v != null).map(String)]) assert.ok(header.includes(value), `header shows ${value}`);
  let root;
  for (let i = 0; i < run.steps.length; i++) {
    root = await stepAt(run, i);
    if (i < run.steps.length - 1) await root.locator('[data-step-next]').click();
  }
  assert.ok(await page.locator('[data-run-panel]:visible [data-predict]').count() > 0, 'at least one prediction point');
  const stage = root.locator('[data-step-stage]');
  await stage.focus();
  await stage.press('Home');
  await stepAt(run, 0);
  await stage.press('End');
  await stepAt(run, run.steps.length - 1);
  await root.locator('[data-step-reset]').click();
  await stepAt(run, 0);
  assert.deepEqual(errors, []);
});

test('a deep link opens a demo arm with its reported usage and before/after captures', async () => {
  const run = byId('bomb-claude-run2-with-tool-search-off');
  assert.ok(run?.captures, 'a bomb arm with captures');
  await page.goto(`${url}#run=${encodeURIComponent(run.id)}`);
  await page.reload(); // A deep link is a fresh page load.
  await eventually(async () => assert.equal(await select().inputValue(), run.id), 'the hash preselects the run');
  await stepAt(run, 0);
  assert.equal(await visiblePanel().locator('[data-usage-meter]').getAttribute('data-usage-meter'), 'not-recorded');
  const text = ungroup(await page.locator('body').innerText());
  for (const value of [run.meta.cli_version.match(/\d+\.\d+\.\d+/)[0], run.meta.model, run.meta.effort]) {
    assert.ok(text.includes(value), `header shows ${value}`);
  }
  const usage = value => value && typeof value === 'object' ? Object.values(value).flatMap(usage) : [value];
  for (const value of usage(run.usage).filter(v => typeof v === 'number')) assert.ok(text.includes(String(value)), `usage ${value}`);
  const captures = page.locator('details[data-captures]');
  await captures.evaluate(el => { el.open = true; });
  const blocks = await captures.locator('pre').allTextContents();
  for (const capture of Object.values(run.captures)) assert.ok(blocks.some(block => block.includes(capture)), 'full capture shown');
  assert.deepEqual(errors, []);
});

test('side by side shows the same task in Claude Code and Codex, each stepping on its own', async () => {
  const pair = Object.fromEntries(['claude', 'codex'].map(cli => [cli, runs.find(r => r.task === 'flipped-sense' && r.cli === cli)]));
  await select().selectOption(pair.claude.id);
  const toggle = page.getByRole('checkbox', { name: /side by side/i });
  await toggle.check();
  assert.equal(await page.locator('[data-stepper]:visible').count(), 2);
  const column = cli => page.locator(`[data-run-panel][data-cli="${cli}"]:visible`);
  const status = async cli => (await column(cli).locator('[data-step-status]').innerText()).trim();
  for (const cli of ['claude', 'codex']) assert.equal(await column(cli).getAttribute('data-run-panel'), pair[cli].id);
  await column('codex').locator('[data-step-next]').click();
  assert.equal(await status('codex'), `Step 2 of ${pair.codex.steps.length}`);
  assert.equal(await status('claude'), `Step 1 of ${pair.claude.steps.length}`);
  await toggle.uncheck();
  assert.equal(await page.locator('[data-stepper]:visible').count(), 1, 'off again: one stepper');
  assert.deepEqual(errors, []);
});
