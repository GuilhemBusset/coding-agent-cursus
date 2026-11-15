import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { after, before, test } from 'node:test';
import { chromium } from '../../../../tools/html-pages/browser.mjs';

const cursus = new URL('../../cursus/', import.meta.url);
const manifest = JSON.parse(await readFile(new URL('fixtures/research-loop/manifest.json', cursus)));
const fixtures = {};
for (const { name } of manifest.demos) {
  fixtures[name] = {};
  for (const [key, filename] of Object.entries({ events: 'trace.jsonl', score: 'scorecard.json', claims: 'claims.json', requests: 'requests.jsonl', memory: 'memory-context.jsonl' })) {
    const raw = await readFile(new URL(`fixtures/research-loop/${name}/${filename}`, cursus), 'utf8');
    fixtures[name][key] = filename.endsWith('.jsonl') ? raw.trim().split('\n').map(JSON.parse) : JSON.parse(raw);
  }
}
let browser;
before(async () => { browser = await chromium.launch(); });
after(async () => { await browser?.close(); });

test('embedded events, requests, counters and citations match the actual bundled runs', async () => {
  const page = await browser.newPage();
  try {
    await page.route(/^https?:/, route => route.abort());
    await page.goto(pathToFileURL(fileURLToPath(new URL('demos/research-loop.html', cursus))).href);
    assert.deepEqual(await page.locator('#fixtures').evaluate(el => JSON.parse(el.textContent)), fixtures);
    for (const [name, data] of Object.entries(fixtures)) {
      const root = page.locator(`[data-demo="${name}"]`);
      const states = await root.locator('[data-step]').evaluateAll(steps => steps.map(step => ({
        models: Number(step.querySelector('[data-models]').textContent),
        tools: Number(step.querySelector('[data-tools]').textContent),
        tokens: step.querySelector('[data-tokens]').textContent,
        errors: Number(step.querySelector('[data-errors]').textContent),
        stop: step.querySelector('[data-stop]').textContent,
        grade: step.querySelector('[data-grade]').textContent,
        records: [...step.querySelectorAll('pre code')].map(el => JSON.parse(el.textContent)),
      })));
      let models = 0, tools = 0, tokens = 0, errors = 0;
      data.events.forEach((event, i) => {
        if (event.type === 'model_attempt') {
          models++;
          tokens = tokens === null || event.usage === null ? null : tokens + event.usage.input_tokens + event.usage.output_tokens;
          if (event.status !== 'ok') errors++;
          const request = data.requests.find(r => r.attempt_id === event.attempt_id);
          assert.deepEqual(states[i].records[0], { attempt_id: request.attempt_id, model: request.body.model,
            declared_tools: (request.body.tools ?? []).map(t => t.name), max_output_tokens: request.body.max_output_tokens,
            input_roles: request.body.input.map(m => m.role ?? m.type) });
          const context = data.memory.find(r => r.attempt_id === event.attempt_id);
          assert.deepEqual(states[i].records[1], { attempt_id: context.attempt_id, context_line: context.context_line,
            context_bytes: context.context_bytes, memory: context.memory.map(m => ({ ledger_entries: m.ledger.length,
              sources: m.sources, experiments: m.experiments, calculations: m.calculations ?? [], unresolved: m.unresolved })) });
        }
        if (event.type === 'tool_invocation') { tools++; if (event.result.status !== 'ok') errors++; }
        assert.deepEqual({ ...states[i], records: undefined }, { models, tools, tokens: tokens === null ? 'unknown' : String(tokens), errors,
          stop: event.stop_reason ?? 'running', grade: i === data.events.length - 1 ? String(data.score.quality_pass) : 'pending', records: undefined });
        assert.deepEqual(states[i].records[event.type === 'model_attempt' ? 2 : 0], event);
      });
      assert.equal(models, data.score.model_attempts);
      assert.equal(tools, data.score.tool_invocations);
      assert.equal(tokens, data.score.total_tokens);
      const expectedCitations = data.claims.claims.flatMap(c => c.evidence.map(e => `${c.claim_id} → ${e.source_id} ${e.kind} [${e.start}, ${e.end})`));
      assert.deepEqual(await root.locator('[data-citations] a').allTextContents(), expectedCitations);
      assert.equal(await root.getAttribute('data-step-current'), '0');
      assert.equal(await root.locator('[data-step-prev]').isDisabled(), true);
    }
    const root = page.locator('[data-demo="recovery"]');
    const stage = root.locator('[data-step-stage]');
    const last = fixtures.recovery.events.length - 1;
    await root.locator('[data-step-next]').click();
    assert.equal(await root.getAttribute('data-step-current'), '1');
    await root.locator('[data-step-prev]').click();
    assert.equal(await root.getAttribute('data-step-current'), '0');
    await stage.focus();
    await page.keyboard.press('End');
    assert.equal(await root.getAttribute('data-step-current'), String(last));
    assert.equal(await root.locator('[data-step-next]').isDisabled(), true);
    assert.equal(await root.locator('[data-step]:visible [data-stop]').textContent(), fixtures.recovery.score.stop_reason);
    await page.keyboard.press('ArrowLeft');
    assert.equal(await root.getAttribute('data-step-current'), String(last - 1));
    await page.keyboard.press('ArrowRight');
    await page.keyboard.press('Home');
    assert.equal(await root.getAttribute('data-step-current'), '0');
    await page.keyboard.press('ArrowLeft');
    assert.equal(await root.getAttribute('data-step-current'), '0');
    await root.locator('[data-step-next]').click();
    await root.locator('[data-step-reset]').focus();
    await page.keyboard.press('Enter');
    assert.equal(await root.getAttribute('data-step-current'), '0');
    assert.equal(await root.locator('[data-step]:visible').count(), 1);
  } finally { await page.close(); }
});
