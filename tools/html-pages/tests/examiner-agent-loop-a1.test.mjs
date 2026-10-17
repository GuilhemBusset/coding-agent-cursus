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
const demos = JSON.parse(readFileSync(path.join(fixtures, 'agent-demos.json'), 'utf8')).runs;
const all = [...tasks.map(r => ({ ...r, id: r.meta.run })), ...demos];
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

test('A1: all committed task and demo steps play with networking disabled', { timeout: 120000 }, async t => {
  const p = await open(t);
  assert.deepEqual((await p.getByRole('combobox').locator('option').evaluateAll(os => os.map(o => o.value))).sort(), all.map(r => r.id).sort());
  for (const r of all) {
    await choose(p, r.id);
    for (const [i, s] of r.steps.entries()) {
      assert.equal(await step(p).getAttribute('data-step-type'), s.type);
      await reveal(p);
      assert.equal(await step(p).locator('pre').textContent(), textOf(s), `${r.id}, step ${i}`);
      if (i + 1 < r.steps.length) await panel(p).locator('[data-step-next]').evaluate(b => b.click());
    }
    assert.ok(await panel(p).locator('[data-step-next]').isDisabled());
  }
});
