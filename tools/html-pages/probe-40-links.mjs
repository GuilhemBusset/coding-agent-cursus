import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { readFileSync, existsSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { chromium } from './browser.mjs';

test('D8: concept links open both offline widgets and the effort reveal agrees with its replay', async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.route(/^https?:/, route => { errors.push(route.request().url()); return route.abort(); });
    const deck = pathToFileURL(path.resolve('sessions/01-fundamentals/cursus/02-thinking.html')).href;
    for (const id of ['search', 'sharpen-or-expand', 'overthinking', 'kepler', 'repo-model']) {
      await page.goto(deck + '#' + id);
      await page.locator(`#${id} a[href^="labs/"]`).click();
      const target = new URL(page.url());
      assert.equal(target.protocol, 'file:');
      assert.ok(target.hash.length > 1);
      assert.ok(await page.locator(target.hash).isVisible());
    }
    await page.goto(deck + '#effort-demo');
    const runbook = await page.locator('#effort-demo a[href]').getAttribute('href');
    const runbookPath = fileURLToPath(new URL(runbook, deck));
    assert.ok(existsSync(runbookPath));
    assert.match(readFileSync(runbookPath, 'utf8'), /--cli claude/);
    assert.match(readFileSync(runbookPath, 'utf8'), /--cli codex/);
    await page.locator('#effort-demo .reveal summary').click();
    const rows = await page.locator('#effort-demo .reveal tbody tr').evaluateAll(rows => rows.map(row => [...row.cells].map(cell => cell.textContent.trim())));
    const demoDir = path.dirname(runbookPath);
    const recording = JSON.parse(readFileSync(path.join(demoDir, 'recorded/results.json')));
    assert.equal(rows.length, recording.runs.length);
    recording.runs.forEach((run, i) => {
      assert.deepEqual(rows[i], [run.model, run.effort, String(run.tokens.output), String(run.cli === 'claude' ? run.tokens.thinking : run.tokens.reasoning_output), run.wall_seconds.toFixed(1), run.cost_usd.toFixed(4), String(run.answer) + ', ' + (run.correct ? 'correct' : 'incorrect')]);
    });
    const replay = execFileSync('python3', [path.join(demoDir, 'effort.py'), 'replay'], { encoding: 'utf8' });
    assert.ok(replay.includes(recording.run_date));
    for (const run of recording.runs) assert.ok(replay.includes(run.cost_usd.toFixed(4)));
    assert.deepEqual(errors, []);
  } finally { await browser.close(); }
});
