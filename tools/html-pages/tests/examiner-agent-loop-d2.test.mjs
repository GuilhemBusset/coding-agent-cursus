import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { chromium } from '../browser.mjs';
import { openPage, repoRoot } from './component-helpers.mjs';

const root = repoRoot;
const cursus = path.join(root, 'sessions/01-fundamentals/cursus');
const file = path.join(cursus, 'labs/agent-loop.html');
const fixtures = path.join(cursus, 'fixtures/runs');
const tasks = readdirSync(fixtures).filter(n => /-(claude|codex)\.json$/.test(n))
  .map(n => JSON.parse(readFileSync(path.join(fixtures, n), 'utf8')));
const panel = p => p.locator('[data-run-panel]:visible');
const step = p => panel(p).locator('[data-step]:visible');
const compact = s => s.replace(/,/g, '');
async function open(t) { return openPage(t, chromium, { file, offline: true }); }
async function choose(p, id) { await p.getByRole('combobox').selectOption(id); }
async function reveal(p) {
  const quiz = step(p).locator('[data-predict]');
  if (!await quiz.count()) return;
  if (!await quiz.locator('[data-predict-answer]').isHidden()) return;
  await quiz.locator('input[type=radio]').first().check();
  await quiz.locator('[data-predict-lock]').click();
  await quiz.locator('[data-predict-reveal]').click();
}
async function go(p, i) {
  await panel(p).locator('[data-step-stage]').focus();
  await p.keyboard.press('Home');
  for (let n = 0; n < i; n++) await panel(p).locator('[data-step-next]').evaluate(b => b.click());
}

test('D2: toolkit navigation, phase changes and measured context/input counters follow real steps', async t => {
  const p = await open(t);
  for (const cli of ['claude', 'codex']) {
    const r = tasks.find(r => r.meta.run === `flipped-sense-${cli}`);
    await choose(p, r.meta.run);
    const edit = r.steps.findIndex(s => /^(Edit|file_change)$/.test(s.tool));
    const verify = r.steps.findIndex((s, i) => i > edit && s.type === 'tool_call' && /pytest/.test(JSON.stringify(s.input)));
    for (const [i, phase] of [[r.steps.findIndex(s => s.type === 'tool_call'), 'gather'], [edit, 'act'], [verify, 'verify']]) {
      await go(p, i); await reveal(p);
      assert.equal(await panel(p).locator('[data-lane-phase][aria-current=step]').getAttribute('data-lane-phase'), phase);
    }
    await panel(p).locator('[data-step-stage]').focus(); await p.keyboard.press('End');
    assert.equal(await panel(p).locator('[data-stepper]').getAttribute('data-step-current'), String(r.steps.length - 1));
    assert.ok(await panel(p).locator('[data-step-next]').isDisabled());
    await panel(p).locator('[data-step-reset]').click();
    assert.equal(await panel(p).locator('[data-stepper]').getAttribute('data-step-current'), '0');
  }
  for (const r of tasks.filter(r => r.meta.vendor === 'claude')) {
    await choose(p, r.meta.run);
    let sent = 0, latest = null;
    for (const [i, s] of r.steps.entries()) {
      if (s.tokens?.input != null) { sent += s.tokens.input; latest = s.tokens.input; }
      const box = panel(p).locator('[data-usage-meter]');
      if (latest != null) {
        assert.equal(await box.locator('meter').evaluate(m => m.value), latest);
        assert.ok(compact(await box.locator('[data-meter-sent]').innerText()).includes(`Input sent so far: ${sent} tokens`));
      }
      if (i + 1 < r.steps.length) await panel(p).locator('[data-step-next]').evaluate(b => b.click());
    }
  }
});
