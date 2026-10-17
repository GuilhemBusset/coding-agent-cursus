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
function textOf(s) {
  if (s.text != null) return s.text.slice(0, 1200);
  if (s.type !== 'tool_call') return '';
  if (typeof s.input?.command === 'string') return s.input.command.slice(0, 1200);
  if (s.input?.changes) return s.input.changes.map(c => `${c.kind} ${c.path}`).join('\n').slice(0, 1200);
  return JSON.stringify(s.input, Object.keys(s.input || {}).sort(), 2).slice(0, 1200);
}
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

test('D3: marked calls are hidden, require lock before reveal, and reset to unanswered', async t => {
  const p = await open(t);
  for (const r of tasks) {
    await choose(p, r.meta.run);
    const index = await panel(p).locator('[data-step]').evaluateAll(ss => ss.findIndex(s => s.querySelector('[data-predict]')));
    assert.ok(index >= 0); await go(p, index);
    const quiz = step(p).locator('[data-predict]');
    assert.match(await quiz.locator('legend').innerText(), /what will it run next\?/i);
    assert.ok(await quiz.locator('[data-predict-answer]').isHidden());
    assert.ok(await quiz.locator('[data-predict-reveal]').isDisabled());
    assert.ok(!(await step(p).innerText()).includes(textOf(r.steps[index])));
    await reveal(p);
    assert.equal(await quiz.locator('pre').textContent(), textOf(r.steps[index]));
    await quiz.locator('[data-predict-reset]').click();
    assert.ok(await quiz.locator('[data-predict-answer]').isHidden());
    assert.equal(await quiz.locator('input:checked').count(), 0);
    assert.ok(await quiz.locator('[data-predict-lock]').isDisabled());
  }
});
