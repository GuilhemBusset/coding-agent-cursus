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
function textOf(s) {
  if (s.text != null) return s.text.slice(0, 1200);
  if (s.type !== 'tool_call') return '';
  if (typeof s.input?.command === 'string') return s.input.command.slice(0, 1200);
  if (s.input?.changes) return s.input.changes.map(c => `${c.kind} ${c.path}`).join('\n').slice(0, 1200);
  return JSON.stringify(s.input, Object.keys(s.input || {}).sort(), 2).slice(0, 1200);
}
async function open(t) { return openPage(t, chromium, { file, offline: true }); }
async function choose(p, id) { await p.getByRole('combobox').selectOption(id); }

test('D1: every normalized task is embedded with its metadata, tokens and tools intact', async t => {
  const p = await open(t);
  const data = await p.locator('#agent-run-recordings').textContent();
  const embedded = JSON.parse(data).runs;
  assert.deepEqual(embedded.map(r => r.meta.run).sort(), tasks.map(r => r.meta.run).sort());
  for (const r of tasks) {
    const got = embedded.find(e => e.meta.run === r.meta.run);
    assert.deepEqual(got.meta, r.meta); assert.deepEqual(got.totals, r.totals);
    assert.equal(got.steps.length, r.steps.length);
    for (const [i, s] of r.steps.entries()) {
      for (const key of ['type', 'tokens', 'input', 'tool']) assert.deepEqual(got.steps[i][key], s[key]);
      assert.equal(got.steps[i].text, textOf(s));
    }
    await choose(p, r.meta.run);
    assert.equal(await panel(p).getAttribute('data-run-panel'), r.meta.run);
  }
});
