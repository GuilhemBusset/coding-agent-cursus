import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { chromium } from '../../../../tools/html-pages/browser.mjs';
import { openPage, repoRoot, eventually } from '../../../../tools/html-pages/tests/component-helpers.mjs';

// Act III deck: what would break in front of the room. Every number on its charts is a recording's,
// and is checked against it; each slide control (the #agent build, the #long-run steps, the six
// predicts, Copy) works, and after a pointer press the clicker's → still turns the slide; each replay
// fallback in the notes opens its recording.
// check-page covers the rest of every deck: layout, accessibility, navigation, links, no-JS and print.
const cursus = path.join(repoRoot, 'sessions/01-fundamentals/cursus');
const runs = path.join(cursus, 'fixtures/runs');
const recorded = path.join(cursus, 'demos/agent/recorded');
const file = path.join(cursus, '03-agent.html');
const norm = value => value.normalize('NFKC').replace(/[‘’]/g, "'").replace(/[“”]/g, '"')
  .replace(/[−–]/g, '-').replace(/\s+/g, ' ').trim().toLowerCase();
const fmt = n => n.toLocaleString('en-US');
const json = async file => JSON.parse(await readFile(file, 'utf8'));
const jsonl = async file => (await readFile(file, 'utf8')).split('\n').filter(Boolean).map(line => JSON.parse(line));
// One usage block per model call: Claude Code repeats it on every event of the same message id.
async function callsOf(raw) {
  const calls = new Map();
  for (const event of await jsonl(raw)) if (event.type === 'assistant' && !calls.has(event.message.id)) calls.set(event.message.id, event.message.usage);
  return [...calls.values()];
}
const toolRuns = run => run.steps.filter(step => step.type === 'tool_call').length;
// The slides that ask the room first, by the prefix of their data attributes.
const predicts = [['harness', 'hn'], ['two-harnesses', 'rp'], ['resend', 'rs'], ['prefix', 'cw'], ['mcp-skills', 'px'], ['stop', 'rp']];

test('Act III deck', async t => {
  const page = await openPage(t, chromium, { file, permissions: ['clipboard-read', 'clipboard-write'] });
  const topic = id => page.locator(`section[data-slide]#${id}`);
  const slides = page.locator('main[data-deck] section[data-slide]');
  // The labels of a slide's pictures (not the spine), one per SVG text, so numbers never run together.
  const labels = id => topic(id).evaluate(el => [...el.querySelectorAll('svg:not(.spine) text')]
    .map(text => text.textContent.replace(/\s+/g, ' ').trim()).filter(Boolean).join(' | ')).then(norm);
  const at = id => eventually(async () => {
    assert.equal(decodeURIComponent(new URL(page.url()).hash.slice(1)), id);
    assert.deepEqual(await slides.evaluateAll(els => els.filter(el => el.checkVisibility()).map(el => el.id)), [id]);
  }, `on #${id}`);
  const goTo = async id => { await page.evaluate(id => { location.hash = id; }, id); await at(id); };
  // A pointer press on a slide control hands focus back to the slide, so the clicker's → still turns it.
  const stillTurns = async id => {
    const ids = await slides.evaluateAll(els => els.map(el => el.id));
    await page.keyboard.press('ArrowRight');
    await at(ids[ids.indexOf(id) + 1]);
    await goTo(id);
  };
  const flipped = await json(path.join(runs, 'flipped-sense-claude.json'));
  const meta = await json(path.join(runs, 'raw/flipped-sense-claude.meta.json'));

  await t.test('#harness replays the recorded run: its replies, test results, counts and duration', async () => {
    const calls = await callsOf(path.join(runs, 'raw/flipped-sense-claude.jsonl'));
    const tools = flipped.steps.filter(step => step.type === 'tool_call');
    const said = flipped.steps.filter(step => step.type === 'message').map(step => step.text);
    const results = flipped.steps.filter(step => step.type === 'tool_result').map(step => step.text);
    const pytests = tools.filter(step => step.tool === 'Bash' && step.input.command.includes('uv run pytest')).length;
    const summary = text => [...text.matchAll(/(?:\d+ failed, )?\d+ passed/g)].at(-1)[0];
    const lanes = norm(await topic('harness').locator('svg:not(.spine)').first().evaluate(el => el.textContent));
    for (const result of [results[0], results.at(-1)]) assert.ok(lanes.includes(summary(result)), `pytest said ${summary(result)}`);
    assert.ok(lanes.includes(norm(said[0])), 'call 2’s sentence, verbatim');
    assert.ok(lanes.includes(norm(said.at(-1).split('\n')[0].split('. ')[0])), 'call 3’s first sentence, verbatim');
    const text = norm(await topic('harness').evaluate(el => el.textContent));
    for (const count of [`${calls.length} model calls`, `${tools.length} tool runs`, `${pytests} test runs`]) assert.ok(text.includes(count), count);
    assert.ok((await labels('harness')).split(' | ').includes(`${Math.round(flipped.steps.at(-1).t_ms / 1000)} s`), 'the time axis ends at the run’s last event');
  });

  await t.test('#two-harnesses: the recorded prompt, loop.md’s launch commands, and the recorded tool counts', async () => {
    const pres = await topic('two-harnesses').locator('details.speaker-notes pre[id]').allTextContents();
    assert.ok(pres.includes(meta.scenario.prompt), 'the prompt, word for word the recorded one');
    const launch = pres.filter(text => /\b(?:claude|codex) /.test(text) && text.includes('agent_demo.py reset loop'));
    assert.equal(launch.length, 2, 'one launch command per harness');
    // The runbook rehearses the same two lines and the same prompt.
    const runbook = await readFile(path.join(cursus, 'demos/agent/loop.md'), 'utf8');
    const live = runbook.slice(runbook.indexOf('## Live in class'));
    for (const text of [...launch, meta.scenario.prompt]) assert.ok(live.includes(text), `loop.md's live section has: ${text.slice(0, 60)}…`);
    const shown = (await labels('two-harnesses')).split(' | ');
    for (const vendor of ['claude', 'codex']) {
      const n = toolRuns(await json(path.join(runs, `flipped-sense-${vendor}.json`)));
      assert.ok(shown.includes(`${n} tool runs`), `${vendor}: ${n} tool runs`);
    }
  });

  await t.test('#resend draws its three calls to scale', async () => {
    const calls = await callsOf(path.join(runs, 'raw/flipped-sense-claude.jsonl'));
    const bars = await topic('resend').locator('.rs-bar').evaluateAll(els => els.map(bar => ({
      title: bar.querySelector('title').textContent,
      cached: Number(bar.querySelector('rect.rs-cached').getAttribute('width')),
      fresh: Number(bar.querySelector('rect.rs-new').getAttribute('width')),
    })));
    assert.equal(bars.length, 3);
    const scale = bars[0].cached / calls[0].cache_read_input_tokens;
    bars.forEach((bar, i) => {
      const call = calls[i], total = call.cache_read_input_tokens + call.cache_creation_input_tokens + call.input_tokens;
      for (const n of [total, call.cache_read_input_tokens, call.cache_creation_input_tokens]) assert.ok(bar.title.includes(fmt(n)), `${bar.title} shows ${n}`);
      assert.ok(Math.abs(bar.cached - call.cache_read_input_tokens * scale) < 1, `call ${i + 1}: cached part to scale`);
      assert.ok(Math.abs(bar.fresh - call.cache_creation_input_tokens * scale) < 1, `call ${i + 1}: new part to scale`);
    });
  });

  await t.test('#long-run prices every recorded call to scale, and its totals are the CLI’s', async () => {
    // Every call priced at Opus 5.5 list prices: grey what it read from the cache, teal what it wrote to it
    // (and its uncached tokens); the run wrote with the 1-hour lifetime.
    const raw = path.join(runs, 'raw/context-bomb-claude.jsonl');
    const usage = await callsOf(raw);
    const price = { input: 4, read: 0.2, write1h: 8, output: 20 }; // $ per million tokens
    const priced = usage.map(u => {
      assert.equal(u.cache_creation.ephemeral_1h_input_tokens, u.cache_creation_input_tokens, 'written with the 1-hour lifetime');
      return {
        sent: u.cache_read_input_tokens + u.cache_creation_input_tokens + u.input_tokens,
        read: u.cache_read_input_tokens * price.read / 1e6,
        fresh: (u.cache_creation_input_tokens * price.write1h + u.input_tokens * price.input) / 1e6,
      };
    });
    const result = (await jsonl(raw)).find(event => event.type === 'result');
    const output = result.usage.output_tokens * price.output / 1e6;
    const billed = priced.reduce((sum, call) => sum + call.read + call.fresh, 0) + output;
    assert.ok(Math.abs(billed - result.total_cost_usd) < 0.005, 'list prices reproduce the CLI’s total');
    // The scale is the chart's own axis: $0 on the axis line, $0.50, $1.00 and $1.50 on its grid lines.
    const chart = await topic('long-run').evaluate(el => {
      const y = path => Number(path.getAttribute('d').match(/^M[\d.]+ ([\d.]+)/)[1]);
      const num = (node, name) => Number(node.getAttribute(name));
      return {
        base: y(el.querySelector('.lr-axis')),
        grid: [...el.querySelectorAll('.lr-grid')].map(y),
        columns: [...el.querySelectorAll('.lr-bar')].map(bar => {
          const [read, fresh] = ['rect.lr-cached', 'rect.lr-new'].map(sel => bar.querySelector(sel));
          return { title: bar.querySelector('title').textContent, readY: num(read, 'y'), read: num(read, 'height'), freshY: num(fresh, 'y'), fresh: num(fresh, 'height') };
        }),
        dots: [...el.querySelectorAll('.lr-full-dot')].map(dot => num(dot, 'cy')),
        expired: el.querySelector('.lr-break title').textContent,
        misses: [...el.querySelectorAll('.lr-xl.is-miss')].map(node => node.textContent),
      };
    });
    const perDollar = (chart.base - chart.grid[2]) / 1.5;
    assert.deepEqual(chart.grid.map(y => Math.round((chart.base - y) / perDollar * 100) / 100), [0.5, 1, 1.5], 'evenly spaced grid');
    assert.equal(chart.columns.length, priced.length, 'a column per recorded call');
    chart.columns.forEach((column, i) => {
      assert.ok(column.title.includes(`${fmt(priced[i].sent)} tokens sent`), column.title);
      assert.ok(Math.abs(column.readY + column.read - chart.base) < 0.05, `call ${i + 1}: stands on the axis`);
      assert.ok(Math.abs(column.freshY + column.fresh - column.readY) < 0.05, `call ${i + 1}: teal on top of grey`);
      assert.ok(Math.abs(column.read - priced[i].read * perDollar) < 0.05, `call ${i + 1}: the cache read to scale`);
      assert.ok(Math.abs(column.fresh - priced[i].fresh * perDollar) < 0.05, `call ${i + 1}: the cache write to scale`);
    });
    // The amber line: each call's tokens at the input price, on the same axis.
    assert.equal(chart.dots.length, priced.length);
    chart.dots.forEach((cy, i) => assert.ok(Math.abs(chart.base - cy - priced[i].sent * price.input / 1e6 * perDollar) < 0.1, `call ${i + 1}: full price to scale`));
    // The call after a break: the last call's input written to the cache again, computed.
    const expired = priced.at(-1).sent * price.write1h / 1e6;
    assert.ok(chart.expired.includes(`$${expired.toFixed(2)}`), chart.expired);
    // The misses: a call that read no more from the cache than the one before it.
    assert.deepEqual(chart.misses, usage.map((_, i) => i).filter(i => i > 0 && usage[i].cache_read_input_tokens === usage[i - 1].cache_read_input_tokens).map(i => String(i + 1)));
    const full = priced.reduce((sum, call) => sum + call.sent, 0) * price.input / 1e6 + output;
    const drawn = (await labels('long-run')).split(' | ');
    const cost = call => call.read + call.fresh;
    for (const amount of [result.total_cost_usd, full, cost(priced[0]), cost(priced.at(-1))]) assert.ok(drawn.includes(`$${amount.toFixed(2)}`), `$${amount.toFixed(2)}`);
    assert.ok(drawn.includes(`≈ $${Math.round(expired)}`), 'the call after a break, rounded');
    const ratio = Math.round(priced.at(-1).sent / priced[0].sent);
    assert.ok(drawn.includes(`call ${priced.length}: ${ratio}× the tokens,`) && drawn.includes(`${Math.round(cost(priced.at(-1)) / cost(priced[0]))}× the cost of call 1`), 'tokens against cost');
    assert.ok(norm(await topic('long-run').locator('h2').textContent()).includes(`${ratio}× the tokens`), 'the headline’s ratio');
  });

  await t.test('#mcp-skills and #prefix draw the recorded /context captures, and quote the server', async () => {
    // Claude Code's own /context, before and after adding one noisy MCP server (its tools deferred, as installed).
    const captures = (await readFile(path.join(recorded, 'bomb-claude-run1-context-before.txt'), 'utf8') +
      await readFile(path.join(recorded, 'bomb-claude-run1-context-after.txt'), 'utf8')).split(/^\$ /m).filter(Boolean).map(block => ({
      total: block.match(/\*\*Tokens:\*\* ([\d.]+k)/)[1],
      rows: Object.fromEntries([...block.matchAll(/^\| ([^|]+?) \| ([\d.]+k?) \|/gm)].map(m => [m[1], m[2]])),
    }));
    const [before, deferred] = captures;
    const server = { instructions: deferred.rows['MCP server instructions'], tools: deferred.rows['MCP tools (deferred)'] };
    const added = `+${Number((parseFloat(server.instructions) + parseFloat(server.tools)).toFixed(1))}k`;
    const drawn = await labels('mcp-skills');
    for (const n of [before.total, deferred.total, `instructions ${server.instructions}`, server.tools, added,
      before.rows['System prompt'], `its tools ${before.rows['System tools']}`, before.rows.Skills]) {
      assert.ok(drawn.split(' | ').some(label => label.includes(norm(n))), `#mcp-skills draws ${n}`);
    }
    // The bad server's own words, as the model reads them.
    const source = await readFile(path.join(cursus, 'demos/agent/context_bomb.py'), 'utf8');
    assert.ok(source.includes('Filler tool {_i:02d} — intentionally useless. '), 'the server’s tool description');
    assert.match(drawn, /"filler tool 01 — intentionally/);
    const strip = await labels('prefix');
    for (const n of [`tools ${before.rows['System tools']}`, `system prompt ${before.rows['System prompt']}`, `skills ${before.rows.Skills}`]) {
      assert.ok(strip.includes(norm(n)), `#prefix draws ${n}`);
    }
  });

  await t.test('#gate and #stop show what the runs’ logs record', async () => {
    // Who let each tool call through, in the run's own log, call by call.
    const decisions = (await jsonl(path.join(runs, 'raw/flipped-sense-claude.jsonl'))).flatMap(event => event.tool_result_meta ?? [])
      .map(entry => entry.permission_decision);
    const kinds = (await labels('gate')).split(' | ').filter(label => /^(?:rule|mode):$/.test(label)).map(label => label.slice(0, -1));
    assert.deepEqual(kinds, decisions.map(d => d.reason_type));
    const stop = (await labels('stop')).split(' | ');
    for (const vendor of ['claude', 'codex']) {
      const n = toolRuns(await json(path.join(runs, `impossible-${vendor}.json`)));
      assert.ok(stop.includes(`${n} tool runs`), `${vendor}: ${n} tool runs`);
    }
  });

  await t.test('#agent builds one step per chip, from the model to an agent', async () => {
    await goTo('agent');
    const slide = topic('agent');
    const chips = slide.locator('[data-ag-chip]');
    const seen = () => slide.evaluate(el => ({
      pressed: [...el.querySelectorAll('[data-ag-chip]')].flatMap((chip, i) => chip.getAttribute('aria-pressed') === 'true' ? [i + 1] : []),
      says: [...el.querySelectorAll('[data-ag-say]')].flatMap((say, i) => say.checkVisibility() ? [i + 1] : []),
    }));
    await eventually(async () => assert.deepEqual(await seen(), { pressed: [1], says: [1] }), 'it opens on the model alone');
    for (const step of [2, 3, 4, 1]) {
      await chips.nth(step - 1).click();
      await eventually(async () => assert.deepEqual(await seen(), { pressed: [step], says: [step] }), `step ${step}`);
      await stillTurns('agent');
    }
  });

  await t.test('#long-run adds one priced layer per chip', async () => {
    await goTo('long-run');
    const slide = topic('long-run');
    const chips = slide.locator('[data-lr-chip]');
    const layers = () => slide.evaluate(el => [1, 2, 3].map(step => [...el.querySelectorAll(`svg [data-lr-l="${step}"]`)]
      .every(layer => getComputedStyle(layer).visibility === 'visible' && getComputedStyle(layer).opacity === '1')));
    await eventually(async () => assert.deepEqual(await layers(), [true, false, false]), 'it opens at full price');
    for (const step of [2, 3, 1]) {
      await chips.nth(step - 1).click();
      await eventually(async () => assert.deepEqual(await layers(), [1, 2, 3].map(n => n <= step)), `step ${step}: its layer on the earlier ones`);
      await stillTurns('long-run');
    }
  });

  for (const [id, p] of predicts) {
    await t.test(`#${id}: the room’s pick, then the run revealed beside it, then Reset`, async () => {
      await goTo(id);
      const slide = topic(id);
      const chips = slide.locator(`[data-${p}-chip]`);
      const state = () => slide.evaluate((el, p) => {
        const run = [...el.querySelectorAll(`[data-${p}-run], .${p}-ans`)].map(node => getComputedStyle(node).visibility);
        return {
          run: run.length && run.every(v => v === 'visible') ? 'shown' : run.every(v => v === 'hidden') ? 'hidden' : 'partly shown',
          pressed: [...el.querySelectorAll(`[data-${p}-chip]`)].flatMap((chip, i) => chip.getAttribute('aria-pressed') === 'true' ? [i] : []),
        };
      }, p);
      await eventually(async () => assert.deepEqual(await state(), { run: 'hidden', pressed: [] }), 'the run starts hidden');
      await chips.nth(0).click();
      await chips.nth(1).click();
      assert.deepEqual((await state()).pressed, [1], 'one pick at a time');
      await stillTurns(id);
      await slide.locator(`[data-${p}-reveal]`).click();
      await eventually(async () => assert.deepEqual(await state(), { run: 'shown', pressed: [1] }), 'the run shows beside the pick');
      await stillTurns(id);
      await slide.locator(`[data-${p}-reset]`).click();
      await eventually(async () => assert.deepEqual(await state(), { run: 'hidden', pressed: [] }), 'Reset hides the run and clears the pick');
      await stillTurns(id);
    });
  }

  await t.test('Copy in #two-harnesses’ notes puts each command and the prompt on the clipboard', async () => {
    await goTo('two-harnesses');
    const notes = topic('two-harnesses').locator('details.speaker-notes');
    await notes.locator(':scope > summary').click();
    const buttons = await notes.locator('button[data-copy]').all();
    assert.ok(buttons.length > 0);
    for (const button of buttons) {
      const source = await notes.locator(`pre#${await button.getAttribute('data-copy')}`).textContent();
      await button.click();
      await eventually(async () => assert.equal(await page.evaluate(() => navigator.clipboard.readText()), source), `Copy ${await button.getAttribute('data-copy')}`);
    }
    await stillTurns('two-harnesses');
  });

  await t.test('each replay fallback in the notes opens its recording in the replay lab', async () => {
    const hrefs = [...new Set(await page.locator('details.speaker-notes a[href*="agent-loop.html#run="]').evaluateAll(els => els.map(el => el.getAttribute('href'))))];
    for (const vendor of ['claude', 'codex']) assert.ok(hrefs.some(href => href.endsWith(`#run=flipped-sense-${vendor}`)), `the opening run, ${vendor}`);
    const replay = await page.context().newPage();
    const errors = [];
    replay.on('pageerror', error => errors.push(error.message));
    try {
      for (const href of hrefs) {
        await replay.goto(new URL(href, pathToFileURL(file)).href);
        const run = href.split('#run=')[1];
        assert.equal(await replay.locator('#run-select').inputValue(), run);
        assert.equal(await replay.locator(`[data-run-panel="${run}"]`).isVisible(), true, `${run} is shown`);
      }
    } finally { await replay.close(); }
    assert.deepEqual(errors, [], 'the replay lab runs without errors');
  });
});
