import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { chromium } from '../../../../tools/html-pages/browser.mjs';
import { repoRoot, eventually } from '../../../../tools/html-pages/tests/component-helpers.mjs';

/* The context lab's arithmetic, computed here, never with a ContextLab calculation as the oracle.
 * Selectors are the agreed data attributes. Charts are compared vertex by vertex on one affine
 * scale, without prescribing plot dimensions. Prose, citations, layout, accessibility and the
 * no-JS view are reviewed by a person or by the page checker, not here.
 */
const file = path.join(repoRoot, 'sessions/01-fundamentals/cursus/labs/context.html');
const panelIds = ['what-it-sees', 'cost-over-turns', 'budget'];
const categories = ['system', 'tools', 'mcp', 'memory', 'skills', 'messages', 'free', 'buffer'];
const actions = ['read-log', 'add-mcp', 'run-tests', 'compact', 'clear', 'subagent'];
const panel = (page, id) => page.locator(`section[data-ctx-panel="${id}"]`);
const norm = text => text.replace(/\s+/g, ' ').trim();
const key = text => text.toLowerCase().replace(/[^a-z0-9]/g, '');
const sum = values => values.reduce((a, b) => a + b, 0);
const text = async locator => norm(await locator.textContent());

function near(actual, expected, tolerance = 1e-9, label = 'value') {
  assert.ok(Number.isFinite(actual) && Math.abs(actual - expected) <= tolerance,
    `${label}: ${actual} != ${expected} (tolerance ${tolerance})`);
}
function numbers(text) {
  // Accept full integers with grouping, scientific notation, and k/M suffixes.
  return [...text.replace(/\u202f|\u00a0/g, ' ').matchAll(/(?<![\w.])[-+]?\d[\d,]*(?:\.\d+)?(?:e[-+]?\d+)?\s*[kKmM]?(?![a-zA-Z])/g)].map(match => {
    const raw = match[0].trim(), suffix = raw.match(/[kKmM]$/)?.[0];
    const literal = raw.replace(/[,\s]|[kKmM]$/g, '');
    const scale = suffix ? (suffix.toLowerCase() === 'k' ? 1000 : 1e6) : 1;
    const decimals = literal.split('.')[1]?.replace(/e.*/i, '').length ?? 0;
    return { value: Number(literal) * scale, resolution: 10 ** -decimals * scale };
  });
}
function numberIn(text, expected, money = false, label = 'readout') {
  const values = numbers(text);
  assert.ok(values.some(n => Math.abs(n.value - expected) <= (money ? Math.min(0.00501, n.resolution / 2 + 1e-9) : 1e-9)),
    `${label}: ${expected} absent from ${JSON.stringify(text)}`);
}
function oneNumber(text, expected, money = false, label = 'cell') {
  const values = numbers(text);
  assert.equal(values.length, 1, `${label}: one numerical value (${text})`);
  near(values[0].value, expected, money ? Math.min(0.00501, values[0].resolution / 2 + 1e-9) : 1e-9, label);
}
function leaves(object, prefix = '') {
  assert.ok(object && typeof object === 'object' && !Array.isArray(object), `CONFIG group ${prefix}`);
  if (Object.hasOwn(object, 'value')) return [{ name: prefix, ...object }];
  const entries = Object.entries(object);
  assert.ok(entries.length, `nonempty CONFIG group ${prefix}`);
  return entries.flatMap(([name, value]) => leaves(value, prefix ? `${prefix}.${name}` : name));
}
function parameter(config, group, aliases) {
  const canonical = name => key(name).replace(/^initial/, '').replace(/tokens$/, '');
  const matches = leaves(config[group], group).filter(leaf => aliases.map(canonical).includes(canonical(leaf.name.split('.').at(-1))));
  assert.equal(matches.length, 1, `one CONFIG.${group} leaf for ${aliases.join('/')}`);
  return matches[0];
}
function model(config) {
  const value = (group, ...names) => parameter(config, group, names).value;
  return {
    P: value('conversation', 'prefix', 'prefixTokens'), U: value('conversation', 'user', 'userMessage', 'userTokens'),
    A: value('conversation', 'reply', 'replyTokens'), T: value('conversation', 'turns'),
    input: value('pricing', 'input'), write: value('pricing', 'cacheWrite5m'), read: value('pricing', 'cacheRead'),
    system: value('budget', 'system'), tools: value('budget', 'tools'), mcp: value('budget', 'mcp', 'mcpTools'),
    memory: value('budget', 'memory', 'memoryFiles'), skills: value('budget', 'skills'), messages: value('budget', 'messages'),
    buffer: value('budget', 'buffer', 'autocompactBuffer'),
    log: value('actions', 'solverLog'), tests: value('actions', 'testRun'), server: value('actions', 'mcpServer'),
    compact: value('actions', 'compactSummary'), dispatch: value('actions', 'subagentDispatch'),
    summary: value('actions', 'subagentSummary'), child: value('actions', 'childInvestigation'),
  };
}
// Independent input/caching oracle. Replies become input on subsequent turns.
function costOracle(m) {
  let totalInput = 0, totalRead = 0, totalWrite = 0, uncached = 0, cached = 0, previous = 0;
  return Array.from({ length: m.T }, (_, i) => {
    const turn = i + 1, input = m.P + m.U + i * (m.U + m.A);
    const read = i ? previous : 0, write = input - read;
    const inputCost = input * m.input / 1e6, cachedCost = (read * m.read + write * m.write) / 1e6;
    totalInput += input; totalRead += read; totalWrite += write;
    uncached += inputCost; cached += cachedCost; previous = input;
    return { turn, input, read, write, inputCost, cachedCost, totalInput, totalRead, totalWrite, uncached, cached };
  });
}
function initialOracle(m, window = 200000) {
  return { window, system: m.system, tools: m.tools, mcp: m.mcp, memory: m.memory,
    skills: m.skills, messages: m.messages, buffer: m.buffer, installed: false, child: 0, auto: false };
}
function budgetOracle(before, action, m) {
  const state = { ...before, auto: false };
  if (typeof action === 'number') state.window = action;
  else if (action === 'read-log') state.messages += m.log;
  else if (action === 'add-mcp' && !state.installed) { state.mcp += m.server; state.installed = true; }
  else if (action === 'run-tests') state.messages += m.tests;
  else if (action === 'compact') state.messages = Math.min(state.messages, m.compact);
  else if (action === 'clear') state.messages = 0;
  else if (action === 'subagent') { state.messages += m.dispatch + m.summary; state.child = m.child; }
  if (sum(categories.slice(0, 6).map(name => state[name])) > state.window - state.buffer) {
    state.messages = Math.min(state.messages, m.compact); state.auto = true;
  }
  return state;
}

let browser, page;
const errors = [];
before(async () => {
  browser = await chromium.launch();
  const context = await browser.newContext({ offline: true, viewport: { width: 1280, height: 900 } });
  await context.route(/^(?:https?|wss?|ftp):/i, route => { errors.push(`remote: ${route.request().url()}`); return route.abort(); });
  page = await context.newPage();
  page.setDefaultTimeout(5000);
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  await page.goto(pathToFileURL(file).href);
});
after(() => browser?.close());
async function configFor() {
  const config = await page.evaluate(() => window.ContextLab?.CONFIG);
  assert.ok(config, 'window.ContextLab.CONFIG is exposed');
  return config;
}
async function keyboardRange(input, value) {
  const min = Number(await input.getAttribute('min')), max = Number(await input.getAttribute('max'));
  const step = Number(await input.getAttribute('step') ?? 1);
  assert.ok(value >= min && value <= max && Number.isInteger((value - min) / step));
  await input.focus();
  const low = (value - min) / step, high = (max - value) / step;
  await input.press(low <= high ? 'Home' : 'End');
  for (let i = 0; i < Math.min(low, high); i++) await input.press(low <= high ? 'ArrowRight' : 'ArrowLeft');
  near(Number(await input.inputValue()), value, 0, 'native keyboard range');
}
function resetFor(root) {
  return root.locator('button:not([data-predict-reset]):not([data-ctx-action])').filter({ hasText: /reset/i });
}

async function segmentContract(root, divisor) {
  const raw = root.locator('[data-ctx-view="raw"]');
  const segments = await raw.locator('[data-segment]').evaluateAll(nodes => nodes.map(n => ({
    kind: n.dataset.segment, content: n.querySelector('[data-segment-text]')?.textContent,
    badges: [...n.querySelectorAll('[data-tokens]')].map(b => b.textContent),
  })));
  assert.deepEqual(segments.map(s => s.kind), ['system', 'tools', 'user', 'tool_call', 'tool_result', 'reply']);
  const counts = segments.map(s => {
    assert.ok(typeof s.content === 'string' && s.content.trim(), `${s.kind}: serialized content`);
    assert.equal(s.badges.length, 1);
    const count = Math.ceil(s.content.length / divisor);
    oneNumber(s.badges[0], count, false, `${s.kind} estimate`);
    return count;
  });
  for (const [call, input, output] of [[1, sum(counts.slice(0, 3)), counts[3]], [2, sum(counts.slice(0, 5)), counts[5]]]) {
    numberIn(await text(root.locator(`output[data-ctx-call-input="${call}"]`)), input, false, `call ${call} input`);
    numberIn(await text(root.locator(`output[data-ctx-call-output="${call}"]`)), output, false, `call ${call} output`);
  }
  // Also check any authored badges in the rendered view, if it repeats segments.
  for (const segment of await root.locator('[data-ctx-view="chat"] [data-segment]').all()) {
    const kind = await segment.getAttribute('data-segment'), index = segments.findIndex(s => s.kind === kind);
    assert.ok(index >= 0);
    for (const badge of await segment.locator('[data-tokens]').all()) oneNumber(await text(badge), counts[index]);
  }
}
async function costTable(root, rows) {
  const data = await root.locator('details[data-ctx-cost-table] table').evaluate(table => ({
    headerCells: [...([...table.querySelectorAll('tr')].find(row => row.querySelector('th') && !row.querySelector('td'))?.children || [])].map(n => n.textContent),
    rows: [...table.querySelectorAll('tr')].filter(r => r.querySelector('td')).map(r => [...r.children].map(c => c.textContent)),
  }));
  assert.equal(data.rows.length, rows.length, 'full static turn table');
  assert.ok(data.headerCells.length, 'cost table has column headings');
  const choices = data.headerCells.map(header => {
    const h = norm(header).toLowerCase(), cumulative = /cumul|total|to date|so far/.test(h);
    if (/turn|message\s*(?:number|#)/.test(h)) return ['turn'];
    if (/cost|usd|\$/.test(h)) {
      const cached = !/without|uncached|no cach/.test(h) && /with|cached|caching/.test(h);
      assert.match(h, /without|uncached|no cach|with|cached|caching/, 'cost column identifies cache mode');
      return cached ? (cumulative ? ['cached'] : ['cachedCost', 'cached']) : (cumulative ? ['uncached'] : ['inputCost', 'uncached']);
    }
    if (/read|hit/.test(h)) return cumulative ? ['totalRead'] : ['read', 'totalRead'];
    if (/write/.test(h)) return cumulative ? ['totalWrite'] : ['write', 'totalWrite'];
    if (/input|logical/.test(h)) return cumulative ? ['totalInput'] : ['input', 'totalInput'];
    assert.fail(`Unlabelled numerical cost-table column: ${header}`);
  });
  // A heading without 'cumulative' may mean a per-turn value or a running
  // total, explained by the table caption. Select one interpretation for the
  // WHOLE column, never whichever value happens to fit a particular row.
  const types = choices.map((options, column) => {
    const found = options.find(name => data.rows.every((cells, i) => {
      try { oneNumber(cells[column], rows[i][name], /cost|cached/i.test(name)); return true; }
      catch { return false; }
    }));
    assert.ok(found, `column ${data.headerCells[column]} agrees with all thirty oracle rows`);
    return found;
  });
  assert.ok(types.includes('turn'));
  for (const options of [['input', 'totalInput'], ['inputCost', 'uncached'], ['cachedCost', 'cached']]) assert.ok(options.some(k => types.includes(k)), `table discloses ${options.join('/')}`);
  data.rows.forEach((cells, i) => {
    assert.equal(cells.length, types.length, 'labelled table columns');
    cells.forEach((cell, j) => oneNumber(cell, rows[i][types[j]], /cost|cached/i.test(types[j]), `turn ${i + 1} ${types[j]}`));
  });
}
async function costReadout(root, row) {
  const readout = root.locator('output[data-ctx-cost-readout]');
  assert.equal(await readout.isVisible(), true);
  const content = await text(readout);
  for (const name of ['totalInput', 'totalRead', 'totalWrite', 'uncached', 'cached']) numberIn(content, row[name], /cached/.test(name), name);
}
async function chartSnapshot(figure) {
  return figure.evaluate(figure => {
    function endpoints(d) {
      const tokens = d.match(/[a-zA-Z]|[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:e[-+]?\d+)?/g) || [];
      const sizes = { M: 2, L: 2, H: 1, V: 1, C: 6, S: 4, Q: 4, T: 2 };
      const result = []; let command, i = 0, x = 0, y = 0;
      while (i < tokens.length) {
        if (/^[a-z]$/i.test(tokens[i])) command = tokens[i++];
        const upper = command?.toUpperCase(), size = sizes[upper];
        if (!size || i + size > tokens.length) return [];
        const values = tokens.slice(i, i + size).map(Number); i += size;
        if (values.some(n => !Number.isFinite(n))) return [];
        const relative = command === command.toLowerCase();
        if (upper === 'H') x = values[0] + (relative ? x : 0);
        else if (upper === 'V') y = values[0] + (relative ? y : 0);
        else { x = values.at(-2) + (relative ? x : 0); y = values.at(-1) + (relative ? y : 0); }
        result.push({ x, y });
        if (upper === 'M') command = relative ? 'l' : 'L';
      }
      return result;
    }
    const curves = [];
    for (const node of figure.querySelectorAll('svg polyline, svg path')) {
      if (node.closest('defs, pattern, clipPath, marker')) continue;
      const style = getComputedStyle(node);
      if (!node.getClientRects().length || style.display === 'none' || style.visibility === 'hidden' || style.stroke === 'none' || Number(style.opacity) === 0) continue;
      let points = node.tagName.toLowerCase() === 'polyline' ? Array.from({ length: node.points.numberOfItems }, (_, i) => {
        const p = node.points.getItem(i); return { x: p.x, y: p.y };
      }) : endpoints(node.getAttribute('d') || '');
      if (points.length < 3) continue;
      const matrix = node.getCTM();
      points = points.map(p => { const q = new DOMPoint(p.x, p.y).matrixTransform(matrix); return { x: q.x, y: q.y }; });
      curves.push({ points });
    }
    return { curves };
  });
}
function chartMatches(snapshot, rows, measure) {
  const curves = snapshot.curves;
  assert.equal(curves.length, 2, 'exactly two arithmetic series, no performance curve');
  curves.forEach(c => assert.equal(c.points.length, rows.length, 'one vertex per turn'));
  const values = measure === 'cost' ? [rows.map(r => r.uncached), rows.map(r => r.cached)] : [rows.map(r => r.totalInput), rows.map(r => r.totalRead)];
  // All 60 vertices must fit ONE pair of linear axes, not separate fitted scales.
  const fits = order => {
    const a = order[0].points[0], b = order[0].points.at(-1);
    const dx = (b.x - a.x) / (rows.length - 1), dy = (b.y - a.y) / (values[0].at(-1) - values[0][0]);
    if (!(dx > 0 && dy < 0)) return false;
    return order.every((curve, series) => curve.points.every((point, i) =>
      Math.abs(point.x - (a.x + i * dx)) <= 0.6 &&
      Math.abs(point.y - (a.y + (values[series][i] - values[0][0]) * dy)) <= 0.6));
  };
  assert.ok(fits(curves) || fits([...curves].reverse()), `all ${measure} vertices match the independent cumulative oracle`);
}
async function measureOption(select, mode) {
  const options = await select.locator('option').evaluateAll(nodes => nodes.map(n => ({ value: n.value, text: n.textContent })));
  const matches = options.filter(o => mode === 'cost' ? /cost/i.test(o.text) : /tokens/i.test(o.text) && !/cost/i.test(o.text));
  assert.equal(matches.length, 1, `one ${mode} option`);
  return matches[0].value;
}
async function meterMatches(root, state) {
  const seen = await root.evaluate(root => {
    const child = root.querySelector('[data-ctx-child]');
    return {
      rows: [...root.querySelectorAll('table[data-ctx-meter-table] tr[data-category]')].map(n => ({ name: n.dataset.category, text: n.textContent })),
      enabled: Object.fromEntries([...root.querySelectorAll('button[data-ctx-action]')].map(b => [b.dataset.ctxAction, !b.disabled])),
      status: root.querySelector('[data-ctx-meter-status][role=status]')?.textContent ?? null,
      child: child?.checkVisibility() ? child.textContent : null,
    };
  });
  assert.deepEqual(seen.rows.map(r => r.name).sort(), [...categories].sort());
  const used = sum(categories.slice(0, 6).map(c => state[c])), free = state.window - used - state.buffer;
  assert.ok(free >= 0);
  for (const row of seen.rows) {
    const value = row.name === 'free' ? free : state[row.name], displayed = numbers(row.text);
    assert.equal(displayed.length, 2, `${row.name}: tokens and percentage`);
    near(displayed[0].value, value, 0, `${row.name} tokens`);
    near(displayed[1].value, value / state.window * 100, Math.min(0.501, displayed[1].resolution / 2 + 1e-9), `${row.name} percent`);
  }
  // Adding the MCP server is one-shot; every other action is always available.
  assert.deepEqual(seen.enabled, Object.fromEntries(actions.map(a => [a, a === 'add-mcp' ? !state.installed : true])));
  assert.notEqual(seen.status, null, 'a status line');
  if (state.auto) assert.match(seen.status, /auto.*compact|compact.*automatic|automatically.*summari/i, 'autocompact announced');
  if (state.child) {
    assert.ok(seen.child, 'the child context is shown');
    numberIn(seen.child, state.child, false, 'child investigation stays in child context');
  }
}
async function replay(root, m, window, script) {
  await root.locator('button[data-ctx-meter-reset]').click();
  // Reset restores the complete default, including window and one-shot install.
  let state = initialOracle(m);
  assert.equal(await root.locator('input[name=ctx-window]:checked').inputValue(), '200000');
  await meterMatches(root, state);
  if (window !== state.window) {
    await root.locator(`input[name=ctx-window][value="${window}"]`).check(); state = budgetOracle(state, window, m);
  }
  for (const action of script) {
    if (typeof action === 'number') await root.locator(`input[name=ctx-window][value="${action}"]`).check();
    else await root.locator(`button[data-ctx-action="${action}"]`).click();
    state = budgetOracle(state, action, m);
    await eventually(() => meterMatches(root, state), `meter after ${action}`);
    assert.equal(await root.locator('input[name=ctx-window]:checked').inputValue(), String(state.window));
  }
  return state;
}
async function hatchedMeterMatches(root, state) {
  const patterns = await root.evaluate(root => {
    const result = [];
    for (const node of root.querySelectorAll('*')) {
      if (node.closest('table, defs, pattern')) continue;
      const style = getComputedStyle(node), box = node.getBoundingClientRect();
      if (!box.width || !box.height || style.display === 'none' || style.visibility === 'hidden') continue;
      // A hatch may live on the segment itself or its CSS pseudo-element.
      const styles = [style, getComputedStyle(node, '::before'), getComputedStyle(node, '::after')];
      const paint = node instanceof SVGElement ? style.fill : styles.map(s => `${s.backgroundImage} ${s.backgroundSize} ${s.backgroundPosition}`).join(' ');
      if (/gradient\(|url\(/.test(paint)) result.push({ paint, x: box.x, y: box.y, width: box.width, height: box.height });
    }
    return result;
  });
  const used = sum(categories.slice(0, 6).map(c => state[c]));
  const values = categories.map(c => c === 'free' ? state.window - used - state.buffer : state[c]);
  assert.ok(values.every(value => value > 0), 'visual probe uses eight nonempty allocations');
  assert.ok(patterns.some(first => {
    const row = patterns.filter(p => Math.abs(p.y - first.y) < 1 && Math.abs(p.height - first.height) < 1).sort((a, b) => a.x - b.x);
    if (row.length !== 8) return false;
    const width = sum(row.map(p => p.width));
    if (!(width > 0) || row.some((p, i) => i && Math.abs(p.x - row[i - 1].x - row[i - 1].width) > 1)) return false;
    // Compare the multiset of widths: label/legend order is an authoring choice.
    const actual = row.map(p => p.width).sort((a, b) => a - b);
    const expected = values.map(value => value / state.window * width).sort((a, b) => a - b);
    return actual.every((value, i) => Math.abs(value - expected[i]) <= 1);
  }), 'eight contiguous segments reflect current token proportions');
}
test('what it sees: each segment\'s token estimate and both calls\' sums follow the serialized text; the view toggles and resets', async () => {
  const config = await configFor(), root = panel(page, panelIds[0]);
  await segmentContract(root, config.tokens.charsPerToken.value);
  const toggle = root.locator('button[data-ctx-view-toggle]'), chat = root.locator('[data-ctx-view="chat"]'), raw = root.locator('[data-ctx-view="raw"]');
  assert.equal(await chat.isVisible(), true); assert.equal(await raw.isVisible(), false);
  await toggle.click();
  assert.equal(await raw.isVisible(), true); assert.equal(await chat.isVisible(), false);
  await resetFor(root).click();
  assert.equal(await chat.isVisible(), true); assert.equal(await raw.isVisible(), false);
  assert.deepEqual(errors, []);
});

test('cost over turns: the table, both charts and the readout follow the caching oracle; reset restores', async () => {
  const m = model(await configFor()), rows = costOracle(m), root = panel(page, panelIds[1]);
  await costTable(root, rows);
  const range = root.locator('input[type=range]');
  near(Number(await range.inputValue()), 30, 0);
  const select = root.locator('select[data-ctx-measure]'), cost = await measureOption(select, 'cost'), tokens = await measureOption(select, 'tokens');
  assert.equal(await select.inputValue(), cost);
  const figure = root.locator('figure').filter({ has: page.locator('svg') });
  for (const [value, mode] of [[tokens, 'tokens'], [cost, 'cost']]) {
    await select.selectOption(value);
    await eventually(async () => chartMatches(await chartSnapshot(figure), rows, mode));
  }
  for (const turn of [1, 19]) {
    await keyboardRange(range, turn);
    await eventually(() => costReadout(root, rows[turn - 1]));
  }
  await select.selectOption(tokens); await resetFor(root).click();
  near(Number(await range.inputValue()), 30, 0); assert.equal(await select.inputValue(), cost);
  await costReadout(root, rows.at(-1));
  await eventually(async () => chartMatches(await chartSnapshot(figure), rows, 'cost'));
  assert.deepEqual(errors, []);
});

test('budget: every action, window switches, autocompact past the exact threshold, the meter bar and reset', async () => {
  const m = model(await configFor()), root = panel(page, panelIds[2]);
  await replay(root, m, 200000, ['read-log', 'add-mcp', 'run-tests', 'subagent', 'compact', 'read-log', 'clear', 'compact', 'subagent', 'run-tests']);
  const auto = await replay(root, m, 200000, Array(4).fill('read-log'));
  assert.equal(auto.auto, true, 'the threshold is really crossed');
  // A window switch moves the threshold: this crosses it on the way back to 200k.
  const switched = await replay(root, m, 1000000, ['add-mcp', ...Array(4).fill('read-log'), 200000, 'clear', 'subagent', 1000000, 'run-tests', 200000]);
  assert.equal(switched.mcp, m.server, 'clear and switches keep installed tools');
  // At exactly the threshold nothing compacts; one more test run pushes it over.
  const boundary = await replay(root, m, 200000, ['read-log', ...Array(13).fill('run-tests'), ...Array(10).fill('subagent')]);
  near(sum(categories.slice(0, 6).map(c => boundary[c])), boundary.window - boundary.buffer, 0, 'exact boundary');
  assert.equal(boundary.auto, false, 'threshold is >, not >=');
  await root.locator('button[data-ctx-action="run-tests"]').click();
  await meterMatches(root, budgetOracle(boundary, 'run-tests', m));
  // The bar's segments are proportional to the eight allocations.
  const bar = await replay(root, m, 200000, ['add-mcp', 'read-log']);
  await eventually(() => hatchedMeterMatches(root, bar));
  await root.locator('button[data-ctx-meter-reset]').click(); await meterMatches(root, initialOracle(m));
  assert.deepEqual(errors, []);
});

test('the prices are the repository\'s price list', async () => {
  const config = await configFor();
  const prices = JSON.parse(await readFile(path.join(repoRoot, 'sessions/01-fundamentals/cursus/demos/effort/prices.json'), 'utf8'));
  const rates = prices.anthropic.models['claude-sonnet-5-5'];
  for (const [name, field] of [['input', 'input'], ['cacheWrite5m', 'cache_write_5m'], ['cacheRead', 'cache_read']]) {
    near(config.pricing[name].value, rates[field], 0, `${name}: repository price`);
  }
});
