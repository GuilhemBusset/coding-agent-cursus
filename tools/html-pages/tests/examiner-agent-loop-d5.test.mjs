import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { chromium } from '../browser.mjs';
import { openPage } from './component-helpers.mjs';

const root = process.cwd();
const cursus = path.join(root, 'sessions/01-fundamentals/cursus');
const file = path.join(cursus, 'labs/agent-loop.html');
const url = pathToFileURL(file).href;
const fixtures = path.join(cursus, 'fixtures/runs');
const demos = JSON.parse(readFileSync(path.join(fixtures, 'agent-demos.json'), 'utf8')).runs;
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

test('D5: every runbook fallback link selects its recorded demo and plays to the end', async t => {
  const p = await open(t);
  let count = 0;
  for (const book of ['loop.md', 'plan-first.md', 'context-bomb.md']) {
    const md = readFileSync(path.join(cursus, 'demos/agent', book), 'utf8');
    const ids = [...md.matchAll(/agent-loop\.html#run=([^\s)]+)/g)].map(m => m[1]);
    assert.ok(ids.length > 0);
    for (const id of ids) {
      await p.goto(`${url}#run=${id}`); await p.reload();
      assert.equal(await p.getByRole('combobox').inputValue(), id);
      const r = demos.find(r => r.id === id); assert.ok(r);
      await panel(p).locator('[data-step-stage]').focus(); await p.keyboard.press('End');
      assert.equal(await step(p).locator('pre').textContent(), textOf(r.steps.at(-1)));
      assert.match(await panel(p).locator('[data-usage-meter]').innerText(), /not recorded/);
      count++;
    }
  }
  assert.ok(count >= 3);
});
