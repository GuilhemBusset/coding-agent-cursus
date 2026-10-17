import test from 'node:test';
import assert from 'node:assert/strict';
import { access, readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { chromium } from '../browser.mjs';
import { repoRoot, eventually, initialPredict, focused, assertCollected } from './component-helpers.mjs';

/* Locked acceptance contract for issue 34. All expected arithmetic is computed
 * here, never by using a ContextLab calculation as an oracle. Only the agreed
 * API and data attributes are selectors; table headings, CONFIG subkeys not
 * named in the design, chart geometry, and reset labels may vary.
 *
 * Charts may use SVG polylines/paths or a canvas. Their thirty actual vertices
 * are compared on a common affine scale, without prescribing plot dimensions,
 * private data attributes, or series IDs. Canvas instrumentation observes real
 * drawing operations; it does not supply data to the page.
 *
 * Factual prose, source qualifications (including command parity), and visual
 * composition require the named, hash-bound review. Presence of that evidence
 * is checked here; keywords are not treated as proof of factual accuracy.
 */
const stem = 'sessions/01-fundamentals/cursus/labs/context';
const file = path.join(repoRoot, `${stem}.html`);
const reviewFile = path.join(repoRoot, stem, 'review.md');
const asOf = '2026-10-11';
const panelIds = ['what-it-sees', 'cost-over-turns', 'budget'];
const categories = ['system', 'tools', 'mcp', 'memory', 'skills', 'messages', 'free', 'buffer'];
const actions = ['read-log', 'add-mcp', 'run-tests', 'compact', 'clear', 'subagent'];
const engineering = 'https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents';
const chroma = 'https://www.trychroma.com/research/context-rot';
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

async function pageFor(t, options = {}) {
  await access(file); // No browser/fixture can conceal a missing deliverable.
  const browser = await chromium.launch(), errors = [], requests = [];
  t.after(async () => {
    await browser.close();
    assert.deepEqual(errors, [], 'no runtime errors, failed requests, or remote requests');
    assert.ok(requests.length && requests.every(url => url.split('#')[0] === pathToFileURL(file).href || url.startsWith('data:')),
      `self-contained offline requests: ${requests.join(', ')}`);
  });
  const context = await browser.newContext({ offline: true, serviceWorkers: 'block', viewport: { width: 1280, height: 900 }, ...options });
  await context.route(/^(?:https?|wss?|ftp):/i, route => { errors.push(`remote: ${route.request().url()}`); return route.abort(); });
  // Observe canvas line plots without demanding an implementation-specific API.
  await context.addInitScript(() => {
    window.__contextAcceptanceCanvas = new Map();
    const proto = CanvasRenderingContext2D.prototype;
    const record = ctx => {
      if (!window.__contextAcceptanceCanvas.has(ctx.canvas)) window.__contextAcceptanceCanvas.set(ctx.canvas, { path: [], strokes: [], labels: [] });
      return window.__contextAcceptanceCanvas.get(ctx.canvas);
    };
    for (const name of ['beginPath', 'moveTo', 'lineTo', 'stroke', 'clearRect', 'fillText']) {
      const original = proto[name];
      proto[name] = function (...args) {
        const r = record(this);
        if (name === 'beginPath') r.path = [];
        if (name === 'clearRect' && args[2] >= this.canvas.width && args[3] >= this.canvas.height) { r.strokes = []; r.labels = []; }
        if (name === 'moveTo' || name === 'lineTo') {
          const p = new DOMPoint(args[0], args[1]).matrixTransform(this.getTransform());
          r.path.push({ x: p.x, y: p.y });
        }
        if (name === 'stroke') r.strokes.push({ points: r.path.slice(), dash: this.getLineDash().join(','), width: this.lineWidth });
        if (name === 'fillText') r.labels.push(String(args[0]));
        return original.apply(this, args);
      };
    }
  });
  const page = await context.newPage();
  page.setDefaultTimeout(5000);
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  page.on('request', request => requests.push(request.url()));
  page.on('requestfailed', request => errors.push(`failed: ${request.url()}`));
  page.on('websocket', socket => errors.push(`websocket: ${socket.url()}`));
  await page.goto(pathToFileURL(file).href);
  return page;
}
async function configFor(page) {
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
async function reviewEvidence() {
  const bytes = await readFile(file), review = await readFile(reviewFile, 'utf8');
  assert.ok(review.includes(createHash('sha256').update(bytes).digest('hex')), 'review binds current page SHA256');
  assert.ok(new RegExp(`\\b${bytes.length.toLocaleString('en-US').replace(/,/g, '[, ]?')}\\s*bytes\\b`, 'i').test(review), 'review binds current byte count');
  assert.match(review, /review(?:er|ed| by)|agent review/i);
  assert.match(review, /\b\d{4}-\d{2}-\d{2}\b/, 'review records its actual date; source snapshots keep their own dates');
  assert.match(review, /check-page\.mjs/); assert.match(review, /PASS/);
  const counts = review.match(/(\d+)\s+(?:of|\/)\s*(\d+)\s+checks/i);
  assert.ok(counts && Number(counts[1]) > 0 && counts[1] === counts[2], 'review records all checker checks passing');
  assert.match(review, /context\.test\.mjs/); assert.match(review, /\b10\s+tests\b/i);
  assert.match(review, /all\s+(?:passing|passed)|10\s*(?:of|\/)\s*10\s*(?:tests)?\s*pass/i, 'suite passing result');
  for (const mode of [/1440/, /1280/, /390/, /no[- ]?(?:js|javascript)/i, /print/i, /reduced[- ]motion/i, /autocompact|auto[- ]compact/i]) assert.match(review, mode);
  assert.match(review, /screenshot|visual.*inspect/i);
  assert.match(review, /constant|parameter/i); assert.match(review, /illustrative/i);
  return review;
}

test('D1: session lab, ordered panels, registered suite and final-page review evidence', async t => {
  const page = await pageFor(t);
  assert.equal(await page.locator('html').getAttribute('data-design-system'), 'cursus');
  assert.equal(await page.locator('html').getAttribute('data-page-kind'), 'lab');
  assert.deepEqual(await page.locator('section[data-ctx-panel]').evaluateAll(nodes => nodes.map(n => n.dataset.ctxPanel)), panelIds);
  assert.equal(await page.locator('section#sources table[data-ctx-sources]').count(), 1);
  const reserved = await page.locator('*').evaluateAll(nodes => nodes.flatMap(n => [...n.attributes].filter(a => a.name === 'data-lab' || a.name === 'data-reset' || a.name.startsWith('data-budget')).map(a => a.name)));
  assert.deepEqual(reserved, [], 'reserved starter hooks are absent');
  await assertCollected('context');
  const api = await page.evaluate(() => Object.fromEntries(['estimateTokens', 'requestInput', 'costRow', 'applyAction', 'initialBudget'].map(name => [name, typeof window.ContextLab?.[name]])));
  assert.ok(Object.values(api).every(type => type === 'function'), 'agreed pure API is exposed');
  await reviewEvidence();
});

async function segmentContract(root, divisor) {
  const raw = root.locator('[data-ctx-view="raw"]');
  const segments = await raw.locator('[data-segment]').evaluateAll(nodes => nodes.map(n => ({
    kind: n.dataset.segment, content: n.querySelector('[data-segment-text]')?.textContent,
    badges: [...n.querySelectorAll('[data-tokens]')].map(b => b.textContent),
  })));
  assert.deepEqual(segments.map(s => s.kind), ['system', 'tools', 'user', 'tool_call', 'tool_result', 'reply']);
  const counts = segments.map(s => {
    assert.ok(typeof s.content === 'string' && s.content.trim(), `${s.kind}: serialized content`);
    assert.equal(s.badges.length, 1); assert.match(s.badges[0], /estimated tokens/i);
    const count = Math.ceil(s.content.length / divisor);
    oneNumber(s.badges[0], count, false, `${s.kind} estimate`);
    return count;
  });
  const serialized = await text(raw);
  for (const shape of [/\bsystem\b/i, /\btools\b/i, /["']role["']\s*:\s*["']user["']/, /["']type["']\s*:\s*["']tool_use["']/, /["']type["']\s*:\s*["']tool_result["']/, /["']role["']\s*:\s*["']assistant["']/]) assert.match(serialized, shape, 'Messages-API-shaped serialization');
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
test('D2: serialized segments, separate calls, estimated tokens and pointer/keyboard view reset', async t => {
  const page = await pageFor(t), config = await configFor(page), root = panel(page, panelIds[0]);
  const divisor = config.tokens.charsPerToken.value;
  await segmentContract(root, divisor);
  const toggle = root.locator('button[data-ctx-view-toggle]'), chat = root.locator('[data-ctx-view="chat"]'), raw = root.locator('[data-ctx-view="raw"]');
  assert.equal(await chat.isVisible(), true); assert.equal(await raw.isVisible(), false);
  assert.equal(await toggle.getAttribute('aria-pressed'), 'false');
  await toggle.click();
  assert.equal(await raw.isVisible(), true); assert.equal(await chat.isVisible(), false);
  assert.equal(await toggle.getAttribute('aria-pressed'), 'true');
  await toggle.focus(); await toggle.press('Space');
  assert.equal(await chat.isVisible(), true); assert.equal(await toggle.getAttribute('aria-pressed'), 'false');
  await toggle.press('Enter'); assert.equal(await raw.isVisible(), true);
  await resetFor(root).click();
  assert.equal(await chat.isVisible(), true); assert.equal(await raw.isVisible(), false);
  assert.equal(await toggle.getAttribute('aria-pressed'), 'false');
  const samples = ['', 'x', 'A'.repeat(Math.ceil(divisor) + 1), 'solver.log\nΔ = 12; 🧪', 'xy'.repeat(137)];
  for (const sample of samples) near(await page.evaluate(s => window.ContextLab.estimateTokens(s), sample), Math.ceil(sample.length / divisor), 0, 'independent token estimate');
});

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
  for (const label of [/input/i, /read/i, /writ/i, /without|uncached|no cach/i, /with cach|cached/i, /USD|\$/]) assert.match(content, label);
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
      curves.push({ points, dash: style.strokeDasharray, width: parseFloat(style.strokeWidth) });
    }
    let labels = figure.textContent;
    for (const canvas of figure.querySelectorAll('canvas')) {
      const record = window.__contextAcceptanceCanvas?.get(canvas);
      if (record) { curves.push(...record.strokes.filter(s => s.points.length >= 3)); labels += ` ${record.labels.join(' ')}`; }
    }
    return { curves, labels };
  });
}
function chartMatches(snapshot, rows, measure) {
  const curves = snapshot.curves;
  assert.equal(curves.length, 2, 'exactly two arithmetic series, no performance curve');
  curves.forEach(c => { assert.equal(c.points.length, rows.length, 'one vertex per turn'); assert.ok(c.width > 0); });
  assert.notEqual(curves[0].dash, curves[1].dash, 'distinct line styles as well as color');
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
  assert.match(snapshot.labels, /turn/i, 'turn axis');
  if (measure === 'cost') {
    assert.match(snapshot.labels, /USD|\$/); assert.match(snapshot.labels, /without|uncached|no cach/i); assert.match(snapshot.labels, /with cach|cached/i);
  } else { assert.match(snapshot.labels, /input.*tokens|tokens.*input/is); assert.match(snapshot.labels, /cache.*read|read.*cache/is); }
}
async function measureOption(select, mode) {
  const options = await select.locator('option').evaluateAll(nodes => nodes.map(n => ({ value: n.value, text: n.textContent })));
  const matches = options.filter(o => mode === 'cost' ? /cost/i.test(o.text) : /tokens/i.test(o.text) && !/cost/i.test(o.text));
  assert.equal(matches.length, 1, `one ${mode} option`);
  return matches[0].value;
}
test('D3: all thirty table/chart rows, caching accounting, dated prices and native slider/reset', { timeout: 90000 }, async t => {
  const page = await pageFor(t), config = await configFor(page), m = model(config), rows = costOracle(m), root = panel(page, panelIds[1]);
  await costTable(root, rows);
  for (const row of rows) {
    near(row.totalRead + row.totalWrite, row.totalInput, 0, 'caching preserves logical input');
    if (row.turn > 1) assert.ok(row.cached < row.uncached, `caching cheaper from turn ${row.turn}`);
  }
  const formula = await text(root.locator('[data-ctx-formula]'));
  for (const assumption of [/5[- ]?\s*(?:minute|min)|five.minute/i, /TTL|time.to.live/i, /last.*block|final.*block/i, /minimum.*cach|cach.*minimum/i, /output.*exclud|exclud.*output/i]) assert.match(formula, assumption);
  const range = root.locator('input[type=range]');
  assert.equal(await range.count(), 1); assert.equal(await range.getAttribute('min'), '1'); assert.equal(await range.getAttribute('max'), '30');
  near(Number(await range.inputValue()), 30, 0);
  const select = root.locator('select[data-ctx-measure]'), cost = await measureOption(select, 'cost'), tokens = await measureOption(select, 'tokens');
  assert.equal(await select.inputValue(), cost);
  const figure = root.locator('figure').filter({ has: page.locator('svg, canvas') });
  assert.equal(await figure.count(), 1);
  for (const [value, mode] of [[cost, 'cost'], [tokens, 'tokens']]) {
    await select.selectOption(value);
    await eventually(async () => chartMatches(await chartSnapshot(figure), rows, mode));
  }
  for (const turn of [1, 2, 7, 19, 23, 30]) {
    await keyboardRange(range, turn);
    await eventually(() => costReadout(root, rows[turn - 1]));
  }
  const price = config.pricing.input;
  assert.equal(await figure.locator(`figcaption a[href="${price.source}"]`).count(), 1);
  assert.ok((await text(figure.locator('figcaption'))).includes(price.asOf));
  assert.match(await text(page.locator('section#sources')), /USD.*(?:MTok|million tokens)/i);
  await keyboardRange(range, 7); await resetFor(root).click();
  near(Number(await range.inputValue()), 30, 0); assert.equal(await select.inputValue(), cost);
  await costReadout(root, rows.at(-1));
  await eventually(async () => chartMatches(await chartSnapshot(figure), rows, 'cost'));
});

async function meterMatches(root, state) {
  const rows = await root.locator('table[data-ctx-meter-table] tr[data-category]').evaluateAll(nodes => nodes.map(n => ({ name: n.dataset.category, text: n.textContent })));
  assert.equal(rows.length, 8); assert.deepEqual(rows.map(r => r.name).sort(), [...categories].sort());
  const used = sum(categories.slice(0, 6).map(c => state[c])), free = state.window - used - state.buffer;
  assert.ok(free >= 0); near(used + free + state.buffer, state.window, 0);
  for (const row of rows) {
    const value = row.name === 'free' ? free : state[row.name], displayed = numbers(row.text);
    assert.equal(displayed.length, 2, `${row.name}: tokens and percentage`);
    near(displayed[0].value, value, 0, `${row.name} tokens`);
    near(displayed[1].value, value / state.window * 100, Math.min(0.501, displayed[1].resolution / 2 + 1e-9), `${row.name} percent`);
    assert.match(row.text, /%/, 'visible percentage unit');
  }
  assert.equal(await root.locator('button[data-ctx-action="add-mcp"]').isEnabled(), !state.installed);
  for (const action of actions.filter(a => a !== 'add-mcp')) assert.equal(await root.locator(`button[data-ctx-action="${action}"]`).isEnabled(), true, `${action} is never rejected`);
  const status = root.locator('[data-ctx-meter-status][role=status]');
  assert.equal(await status.count(), 1);
  if (state.auto) assert.match(await text(status), /auto.*compact|compact.*automatic|automatically.*summari/i, 'autocompact announced');
  if (state.child) {
    const child = root.locator('[data-ctx-child]'); assert.equal(await child.isVisible(), true);
    numberIn(await text(child), state.child, false, 'child investigation stays in child context');
    assert.match(await text(child), /child|subagent|sub-agent/i);
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
test('D4: six actions and mixed sequences in both windows, one-shot MCP, clear, subagent and autocompact', { timeout: 120000 }, async t => {
  const page = await pageFor(t), m = model(await configFor(page)), root = panel(page, panelIds[2]);
  assert.deepEqual(await root.locator('button[data-ctx-action]').evaluateAll(nodes => nodes.map(n => n.dataset.ctxAction)).then(v => v.sort()), [...actions].sort());
  assert.deepEqual(await root.locator('input[type=radio][name=ctx-window]').evaluateAll(nodes => nodes.map(n => n.value).sort()), ['1000000', '200000']);
  assert.ok(m.summary >= 1000 && m.summary <= 2000);
  for (const window of [200000, 1000000]) {
    for (const action of actions) await replay(root, m, window, [action]);
    await replay(root, m, window, ['read-log', 'add-mcp', 'run-tests', 'subagent', 'compact', 'read-log', 'clear', 'compact', 'subagent', 'run-tests']);
    // Enough real actions to cross either capacity; no rejected buttons or clipping.
    const auto = await replay(root, m, window, Array(Math.floor((window - m.buffer - sum(categories.slice(0, 6).map(c => m[c]))) / m.log) + 1).fill('read-log'));
    assert.equal(auto.auto, true, `${window}: threshold really crossed`);
  }
  const switched = await replay(root, m, 1000000, ['add-mcp', ...Array(4).fill('read-log'), 200000, 'clear', 'subagent', 1000000, 'run-tests', 200000]);
  assert.equal(switched.mcp, m.server); // Clear/switch do not uninstall fixed tools.
  // At EXACTLY 170k used, do not compact; the following tests push it over.
  const boundary = await replay(root, m, 200000, ['read-log', ...Array(13).fill('run-tests'), ...Array(10).fill('subagent')]);
  near(sum(categories.slice(0, 6).map(c => boundary[c])), boundary.window - boundary.buffer, 0, 'exact boundary');
  assert.equal(boundary.auto, false, 'threshold is >, not >=');
  await root.locator('button[data-ctx-action="run-tests"]').click();
  await meterMatches(root, budgetOracle(boundary, 'run-tests', m));
  await replay(root, m, 200000, ['clear', 'compact']); // Compact must never expand empty messages.
  await root.locator('button[data-ctx-meter-reset]').click(); await meterMatches(root, initialOracle(m));
});

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
    if (row.length !== 8 || new Set(row.map(p => p.paint)).size !== 8) return false;
    const width = sum(row.map(p => p.width));
    if (!(width > 0) || row.some((p, i) => i && Math.abs(p.x - row[i - 1].x - row[i - 1].width) > 1)) return false;
    // Compare the multiset of widths: label/legend order is an authoring choice.
    const actual = row.map(p => p.width).sort((a, b) => a - b);
    const expected = values.map(value => value / state.window * width).sort((a, b) => a - b);
    return actual.every((value, i) => Math.abs(value - expected[i]) <= 1);
  }), 'eight contiguous, distinctly hatched segments reflect current token proportions');
}
test('D4: meter uses distinct hatch patterns, MCP qualification and hash-bound command review', async t => {
  const page = await pageFor(t), root = panel(page, panelIds[2]), config = await configFor(page), m = model(config);
  let state = initialOracle(m);
  // Include changed messages, a compacted state, and both capacities so a static
  // decorative bar cannot satisfy a dynamically correct table.
  for (const action of ['add-mcp', 'read-log', 'compact', 1000000, 200000]) {
    if (typeof action === 'number') await root.locator(`input[name=ctx-window][value="${action}"]`).check();
    else await root.locator(`button[data-ctx-action="${action}"]`).click();
    state = budgetOracle(state, action, m);
    await eventually(() => hatchedMeterMatches(root, state));
  }
  const copy = await text(root);
  assert.match(copy, /defer.*tool|tool.*discover|tool search/i);
  assert.match(copy, /illustrative/i); assert.match(copy, /simplif/i);
  const review = await reviewEvidence();
  for (const leaf of leaves(config)) assert.ok(review.includes(leaf.source), `source review names ${leaf.source}`);
  assert.match(review, /Claude Code/); assert.match(review, /Codex/);
  // The exact command equivalents are reviewed against dated docs, not guessed
  // by this offline suite or frozen into a test that might encode stale docs.
  assert.match(review, /command|parity|equivalent/i);
});

// Small lexical scanner for the numeric-literal policy. Strings/comments/regex
// are not JavaScript numbers. Template interpolations ARE executable code.
function jsTokens(source) {
  const tokens = []; let i = 0;
  const emit = (type, value) => tokens.push({ type, value });
  function quoted(quote) {
    i++;
    while (i < source.length) { if (source[i] === '\\') i += 2; else if (source[i++] === quote) break; }
  }
  function code(templateExpression = false) {
    let braces = 0;
    while (i < source.length) {
      const c = source[i];
      if (/\s/.test(c)) { i++; continue; }
      if (source.startsWith('//', i)) { i = source.indexOf('\n', i); if (i < 0) i = source.length; continue; }
      if (source.startsWith('/*', i)) { const end = source.indexOf('*/', i + 2); assert.ok(end >= 0); i = end + 2; continue; }
      if (c === '"' || c === "'") { quoted(c); emit('string', ''); continue; }
      if (c === '`') {
        i++; emit('string', '');
        while (i < source.length && source[i] !== '`') {
          if (source[i] === '\\') i += 2;
          else if (source.startsWith('${', i)) { i += 2; code(true); }
          else i++;
        }
        i++; continue;
      }
      // A regex literal follows an operator/delimiter or a return-like keyword.
      const last = tokens.at(-1)?.value;
      if (c === '/' && (!last || /^[=(:,!&|?{;]$/.test(last) || ['return', 'throw', 'case'].includes(last))) {
        i++; let bracket = false;
        while (i < source.length) {
          if (source[i] === '\\') { i += 2; continue; }
          if (source[i] === '[') bracket = true;
          if (source[i] === ']') bracket = false;
          if (source[i++] === '/' && !bracket) break;
        }
        while (/[a-z]/i.test(source[i] ?? '') && i < source.length) i++;
        emit('string', ''); continue;
      }
      const identifier = source.slice(i).match(/^[A-Za-z_$][\w$]*/);
      if (identifier) { emit('id', identifier[0]); i += identifier[0].length; continue; }
      const number = source.slice(i).match(/^(?:0[xX][\da-fA-F_]+|0[bB][01_]+|0[oO][0-7_]+|(?:\d[\d_]*(?:\.[\d_]*)?|\.\d[\d_]*)(?:[eE][+-]?[\d_]+)?)(?:n)?/);
      if (number) { emit('number', number[0]); i += number[0].length; continue; }
      if (c === '}' && templateExpression && braces === 0) { i++; return; }
      if (c === '{') braces++;
      if (c === '}') braces--;
      emit('punct', c); i++;
    }
  }
  code(); return tokens;
}
function checkDomainLiterals(script) {
  const tokens = jsTokens(script), excluded = new Set(); let configs = 0;
  for (let i = 0; i < tokens.length - 3; i++) {
    if (tokens[i].value !== 'const' || tokens[i + 2].value !== '=') continue;
    const name = tokens[i + 1].value;
    if (name !== 'CONFIG' && !/layout/i.test(name)) continue;
    if (name === 'CONFIG') configs++;
    // Exclude only the balanced initializer of CONFIG, or an explicitly named
    // layout OBJECT (geometry). This exception is the agreed design policy.
    let depth = 0, object = false, end = i + 3;
    for (; end < tokens.length; end++) {
      const value = tokens[end].value;
      if (value === '{') object = true;
      if ('({['.includes(value) && value) depth++;
      if (')}]'.includes(value) && value) depth--;
      // Stop at the initializer's closing delimiter even with automatic
      // semicolon insertion; otherwise later code could be excluded as CONFIG.
      if (object && depth === 0 && ')}]'.includes(value) && value) { end++; break; }
      if (depth === 0 && (value === ';' || value === ',')) break;
    }
    assert.ok(object, `${name} initializer is an object`);
    for (let j = i + 3; j < end; j++) excluded.add(j);
  }
  assert.equal(configs, 1, 'exactly one const CONFIG');
  const violations = tokens.filter((token, i) => token.type === 'number' && !excluded.has(i) && Number(token.value.replace(/_|n$/g, '')) >= 100);
  assert.deepEqual(violations, [], 'domain numeric literals >=100 live in CONFIG (named layout objects excluded)');
  assert.ok(!tokens.some((token, i) => token.value === 'getRandomValues' && tokens[i + 1]?.value === '(' ||
    token.value === 'Math' && tokens[i + 1]?.value === '.' && tokens[i + 2]?.value === 'random' && tokens[i + 3]?.value === '('), 'no randomness');
}

async function staticSources(page, constants) {
  const rows = await page.locator('table[data-ctx-sources] tr').evaluateAll(nodes => nodes.filter(n => n.querySelector('td')).map(n => ({
    cells: [...n.children].map(c => c.textContent), links: [...n.querySelectorAll('a[href]')].map(a => a.getAttribute('href')),
  })));
  assert.equal(rows.length, constants.length, 'one static source row per CONFIG leaf');
  const remaining = [...rows];
  for (const leaf of constants) {
    const index = remaining.findIndex(row => row.links.includes(leaf.source) && row.cells.some(c => c.includes(leaf.asOf)) && row.cells.some(c => c.includes(leaf.basis)) && row.cells.some(c => c.includes(leaf.unit)) && row.cells.some(c => numbers(c).some(n => n.value === leaf.value)));
    assert.ok(index >= 0, `static source row equals ${leaf.name}: ${leaf.value} ${leaf.unit}`);
    assert.ok(norm(remaining[index].cells[0]), 'constant has a visible name');
    remaining.splice(index, 1);
  }
}
test('D5: deeply frozen, fully cited CONFIG, exact repository prices and no scattered domain literals', async t => {
  const page = await pageFor(t), config = await configFor(page), constants = leaves(config), m = model(config);
  const frozen = await page.evaluate(() => {
    function visit(object) { return object && Object.isFrozen(object) && Object.values(object).every(v => !v || typeof v !== 'object' || visit(v)); }
    return visit(window.ContextLab.CONFIG);
  });
  assert.equal(frozen, true, 'CONFIG is recursively frozen');
  for (const leaf of constants) {
    assert.ok(typeof leaf.value === 'number' && Number.isFinite(leaf.value), `${leaf.name}: finite value`);
    assert.ok(typeof leaf.unit === 'string' && leaf.unit.trim(), `${leaf.name}: unit`);
    const url = new URL(leaf.source); assert.equal(url.protocol, 'https:');
    assert.match(leaf.asOf, /^\d{4}-\d{2}-\d{2}$/); assert.equal(new Date(leaf.asOf).toISOString().slice(0, 10), leaf.asOf);
    assert.ok(leaf.asOf <= asOf, `${leaf.name}: not a future source`);
    assert.ok(['documented', 'illustrative'].includes(leaf.basis));
    assert.ok(typeof leaf.note === 'string' && leaf.note.trim(), `${leaf.name}: source qualification`);
  }
  assert.deepEqual({ P: m.P, U: m.U, A: m.A, T: m.T }, { P: 4000, U: 200, A: 800, T: 30 });
  assert.deepEqual(categories.filter(c => c !== 'free').map(c => m[c]), [5000, 5000, 0, 3500, 1500, 20000, 30000]);
  assert.deepEqual([m.log, m.tests, m.server, m.compact, m.dispatch, m.summary, m.child], [40000, 6000, 17000, 6000, 200, 1500, 40000]);
  for (const group of ['conversation', 'budget', 'actions']) for (const leaf of leaves(config[group], group)) assert.equal(leaf.basis, 'illustrative', `${leaf.name} is an authored scenario`);
  assert.ok(config.tokens.charsPerToken.value > 0);
  const windows = leaves(config.windows, 'windows');
  for (const size of [200000, 1000000]) assert.ok(windows.some(leaf => leaf.value === size && leaf.basis === 'documented'), `${size}: cited window`);
  const controls = constants.filter(leaf => /control|bound|default/i.test(leaf.name));
  assert.ok(controls.some(leaf => /min/i.test(leaf.name) && leaf.value === 1));
  assert.ok(controls.some(leaf => /max/i.test(leaf.name) && leaf.value === 30));
  assert.ok(controls.some(leaf => /default/i.test(leaf.name) && leaf.value === 30));
  const prices = JSON.parse(await readFile(path.join(repoRoot, 'sessions/01-fundamentals/cursus/demos/effort/prices.json'), 'utf8'));
  const rates = prices.anthropic.models['claude-sonnet-5-5'];
  for (const [name, field] of [['input', 'input'], ['cacheWrite5m', 'cache_write_5m'], ['cacheRead', 'cache_read']]) {
    const leaf = config.pricing[name];
    near(leaf.value, rates[field], 0, `${name}: repository price`);
    assert.equal(leaf.source, prices.anthropic.source); assert.equal(leaf.asOf, prices.as_of); assert.equal(leaf.basis, 'documented');
    assert.match(leaf.unit, /USD.*(?:MTok|million tokens)/i);
  }
  await staticSources(page, constants);
  const html = await readFile(file, 'utf8');
  const specific = html.replace(/<!-- shared-script:begin -->[\s\S]*?<!-- shared-script:end -->/g, '');
  const script = [...specific.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)].filter(m => !/type\s*=\s*["']application\//i.test(m[1])).map(m => m[2]).join('\n');
  checkDomainLiterals(script);
});

test('D2/D3/D4/D5: no-JS numbers equal CONFIG-derived state; both views and answers print', async t => {
  const enhanced = await pageFor(t), config = await configFor(enhanced), m = model(config);
  const page = await pageFor(t, { javaScriptEnabled: false });
  const first = panel(page, panelIds[0]), cost = panel(page, panelIds[1]);
  for (const view of ['chat', 'raw']) assert.equal(await first.locator(`[data-ctx-view="${view}"]`).isVisible(), true, `no-JS ${view}`);
  await segmentContract(first, config.tokens.charsPerToken.value);
  await costTable(cost, costOracle(m)); await costReadout(cost, costOracle(m).at(-1));
  // No-JS controls may be disabled; compare rows without requiring operability.
  const rows = await panel(page, panelIds[2]).locator('table[data-ctx-meter-table] tr[data-category]').evaluateAll(nodes => nodes.map(n => ({ name: n.dataset.category, text: n.textContent })));
  assert.equal(rows.length, 8);
  assert.deepEqual(rows.map(r => r.name).sort(), [...categories].sort(), 'static meter has all eight categories');
  const initial = initialOracle(m), used = sum(categories.slice(0, 6).map(c => initial[c]));
  for (const row of rows) {
    const value = row.name === 'free' ? initial.window - initial.buffer - used : initial[row.name];
    const ns = numbers(row.text); assert.equal(ns.length, 2); near(ns[0].value, value, 0);
    near(ns[1].value, value / initial.window * 100, Math.min(0.501, ns[1].resolution / 2 + 1e-9));
  }
  await staticSources(page, leaves(config));
  assert.equal(await cost.locator('[data-predict-answer]').isVisible(), true);
  for (const button of await cost.locator('[data-predict] button').all()) assert.equal(await button.isEnabled(), false);
  // Hide chat in screen mode first; print must expose both views regardless.
  await panel(enhanced, panelIds[0]).locator('[data-ctx-view-toggle]').click();
  for (const p of [page, enhanced]) {
    await p.emulateMedia({ media: 'print' });
    for (const view of ['chat', 'raw']) assert.equal(await panel(p, panelIds[0]).locator(`[data-ctx-view="${view}"]`).isVisible(), true, `print ${view}`);
    assert.equal(await panel(p, panelIds[1]).locator('[data-predict-answer]').isVisible(), true);
    assert.equal(await panel(p, panelIds[1]).locator('details[data-ctx-cost-table] table').isVisible(), true);
    assert.equal(await p.locator('table[data-ctx-sources]').isVisible(), true);
  }
});

test('A1: plots cite configured sources, context rot is qualitative, and all simulations are visibly labelled', async t => {
  const page = await pageFor(t), config = await configFor(page), urls = new Set(leaves(config).map(leaf => leaf.source));
  for (const id of panelIds) {
    const callout = panel(page, id).locator('.callout[data-illustrative]');
    assert.equal(await callout.count(), 1); assert.equal(await callout.isVisible(), true);
    assert.ok((await text(callout)).includes('Illustrative simulation, not a measurement.'));
  }
  const graphics = await page.locator('svg, canvas').evaluateAll(nodes => nodes.filter(n => !n.closest('[data-prob-chart], [data-predict], [data-stepper], [data-formula]')).map(n => ({
    panel: n.closest('section[data-ctx-panel]')?.dataset.ctxPanel,
    sources: [...(n.closest('figure')?.querySelectorAll('figcaption a[href]') || [])].map(a => a.href),
    caption: n.closest('figure')?.querySelector('figcaption')?.textContent,
  })));
  assert.ok(graphics.length > 0, 'arithmetic chart exists');
  for (const graphic of graphics) {
    assert.ok(graphic.caption?.trim() && graphic.sources.some(url => urls.has(url)), 'every graphic has a configured source in its figcaption');
    assert.ok(['cost-over-turns', 'budget'].includes(graphic.panel), 'no extra performance plot');
  }
  const otherCurves = await chartSnapshot(panel(page, panelIds[2]));
  assert.ok(otherCurves.curves.every(curve => curve.points.length < 30), 'thirty-turn plotted series exist only in panel 2; meter shapes are not curves');
  assert.equal(await panel(page, panelIds[0]).locator('svg, canvas').count(), 0, 'panel 1 is serialization, not a performance plot');
  const rot = await page.locator(`a[href="${chroma}"]`).evaluateAll(nodes => nodes.map(n => ({
    content: (n.closest('.callout, aside') || n.parentElement).textContent,
    links: [...(n.closest('.callout, aside') || n.parentElement).querySelectorAll('a[href]')].map(a => a.href),
  })));
  assert.ok(rot.some(r => r.links.includes(engineering) && /context|recall|degrad/i.test(r.content) && !/\d/.test(r.content.replace(/\d{4}-\d{2}-\d{2}/g, ''))), 'qualitative context-rot callout cites both references, with no numerical recall claims');
  const review = await reviewEvidence();
  assert.ok(review.includes(chroma) && review.includes(engineering));
  assert.match(review, /plot|chart|curve/i);
});

test('A2: shared predict card locks/reveals/scores/resets with keyboard and focus', async t => {
  const page = await pageFor(t), root = panel(page, panelIds[1]).locator('[data-predict]');
  assert.equal(await root.count(), 1);
  assert.equal(await root.locator('fieldset[data-predict-question]').count(), 1);
  assert.equal(await text(root.locator('legend')), 'Message 30 is as long as message 1. Why does it cost more?');
  assert.equal(await root.locator('input[type=radio]').count(), 4);
  assert.equal(await root.locator('input[type=radio][data-correct]').count(), 1);
  const labels = await root.locator('input[type=radio]').evaluateAll(nodes => nodes.map(n => [...n.labels].map(l => l.textContent.trim()).join(' ')));
  assert.ok(labels.every(label => label.length > 10) && new Set(labels).size === 4, 'four distinct, readable choices');
  assert.ok((await text(root.locator('[data-predict-answer]'))).length > 30, 'authored explanation accompanies the answer');
  assert.equal(await root.locator('[data-predict-status][role=status]').count(), 1);
  await initialPredict(root);
  for (const correct of [false, true]) {
    const choice = root.locator(`input[type=radio]${correct ? '[data-correct]' : ':not([data-correct])'}`).first();
    await choice.check();
    const lock = root.locator('button[data-predict-lock]'), reveal = root.locator('button[data-predict-reveal]'), reset = root.locator('button[data-predict-reset]');
    assert.equal(await lock.isEnabled(), true); assert.equal(await reveal.isEnabled(), false);
    await lock.focus(); await lock.press('Enter'); await focused(reveal);
    for (const radio of await root.locator('input[type=radio]').all()) assert.equal(await radio.isEnabled(), false);
    assert.equal(await root.locator('[data-predict-answer]').isVisible(), false);
    await reveal.press('Enter'); await focused(reset);
    assert.equal(await root.locator('[data-predict-answer]').isVisible(), true);
    assert.match(await text(root.locator('[data-predict-result]')), correct ? /^Correct\.$/ : /^Not quite\./);
    await reset.press('Enter'); await focused(root.locator('input[type=radio]').first()); await initialPredict(root);
  }
  // Prose substance belongs to the source review; verify it names this teaching
  // claim, rather than attempting to grade language by an exact answer string.
  const review = await reviewEvidence();
  assert.match(review, /predict|transcript|re.sent/i);
});

test('A3: reduced motion and 390px stress states remain usable without document overflow', async t => {
  const page = await pageFor(t, { reducedMotion: 'reduce', viewport: { width: 390, height: 844 } });
  async function readable() {
    const geometry = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, width: document.documentElement.clientWidth }));
    assert.ok(geometry.scroll <= geometry.width, 'no horizontal document overflow at 390px');
    const motion = await page.locator('section[data-ctx-panel], section[data-ctx-panel] *').evaluateAll(nodes => nodes.flatMap(n => {
      const s = getComputedStyle(n);
      return [...s.animationDuration.split(','), ...s.transitionDuration.split(',')].filter(value => parseFloat(value) > 0.001);
    }));
    assert.deepEqual(motion, [], 'reduced motion disables transitions/animations');
    for (const id of panelIds) assert.equal(await panel(page, id).isVisible(), true);
    assert.equal(await panel(page, panelIds[1]).locator('output[data-ctx-cost-readout]').isVisible(), true);
    assert.equal(await panel(page, panelIds[2]).locator('table[data-ctx-meter-table]').isVisible(), true);
  }
  await readable();
  const cost = panel(page, panelIds[1]), rows = costOracle(model(await configFor(page)));
  await keyboardRange(cost.locator('input[type=range]'), 19); await costReadout(cost, rows[18]);
  await panel(page, panelIds[0]).locator('[data-ctx-view-toggle]').click(); await readable();
  await replay(panel(page, panelIds[2]), model(await configFor(page)), 1000000, ['add-mcp', ...Array(4).fill('read-log'), 200000, 'subagent']);
  await readable();
  await cost.locator('details[data-ctx-cost-table] summary').click(); await readable();
});
