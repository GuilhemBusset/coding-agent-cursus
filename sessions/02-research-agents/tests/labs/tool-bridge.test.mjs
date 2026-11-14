import assert from 'node:assert/strict';
import test from 'node:test';
import { spawnSync } from 'node:child_process';
import { cp, mkdir, mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { Agent } from '@earendil-works/pi-agent-core';
import { BridgeError, callTool, createResearchTools, limits } from '../../exercises/fixed/bridge/bridge.ts';

const session = fileURLToPath(new URL('../../', import.meta.url));
const cases = join(session, 'exercises/cases');
// The suite's launcher activates this session's uv environment; executable paths may contain spaces.
const python = process.env.VIRTUAL_ENV ? join(process.env.VIRTUAL_ENV, process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python') : 'python';
async function bundles() {
  const found = [];
  async function visit(dir) {
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      if (entry.isDirectory()) await visit(join(dir, entry.name));
      else if (entry.name === 'corpus.json') found.push(dir);
    }
  }
  await visit(cases);
  return found.sort();
}

test('real Pi registrations execute read/search/table over every public base and variant', async () => {
  for (const caseRoot of await bundles()) {
    const corpus = JSON.parse(await readFile(join(caseRoot, 'corpus.json'), 'utf8'));
    const tools = createResearchTools({ caseRoot, python, runId: 'bridge-test' });
    const agent = new Agent({ streamFn: () => { throw Error('offline callbacks only'); }, initialState: { tools: [...tools] } });
    assert.deepEqual(agent.state.tools.map(t => t.name), ['read', 'search', 'check_table']);
    const source = corpus.sources[0];
    const read = await tools[0].execute('read-1', { source_id: source.source_id });
    assert.equal(read.isError, false);
    assert.deepEqual(JSON.parse(read.content[0].text), read.details);
    assert.equal(read.details.result.run_id, 'bridge-test');
    assert.equal(read.details.invocation.arguments.start, 0);
    const search = await tools[1].execute('search-1', { query: 'shared cost feasibility correction demand' });
    assert.equal(search.isError, false);
    assert(search.details.result.data.length > 0);
    assert.deepEqual(search.details, (await tools[1].execute('search-1', { query: 'shared cost feasibility correction demand' })).details);
    const table = corpus.sources.find(s => s.path.endsWith('.csv'));
    if (table) {
      const csv = await readFile(join(caseRoot, table.path), 'utf8');
      const pairs = [...new Set(csv.trim().split(/\r?\n/).slice(1).map(line => line.split(',')[3]))];
      const methods = [...new Set(csv.trim().split(/\r?\n/).slice(1).map(line => line.split(',')[4]))];
      const result = await tools[2].execute('table-1', { source_id: table.source_id, method_left: methods[0], method_right: methods[1],
        metric: 'cost', unit: table.units.cost, feasible_only: true, pair_key: 'pair_id', pair_ids: pairs });
      assert.equal(result.isError, false);
      assert(result.details.audit.baseline_total > 0);
      assert.equal(result.details.audit.reduction_percent, result.details.result.data.relative_reduction * 100);
      assert.equal(result.details.audit.pairs.length, result.details.result.data.pairs.length);
    }
    const unknown = await tools[0].execute('bad-1', { source_id: 'DOES-NOT-EXIST' });
    assert.equal(unknown.isError, true);
    assert.deepEqual(unknown.details.result.error, { code: 'not_found', retryable: false });
  }
});

test('UTF-8 JSON and code-point citations survive source and implementation paths containing spaces', async () => {
  const temp = await mkdtemp(join(tmpdir(), 'research bridge spaces '));
  try {
    const exercises = join(temp, 'session with spaces', 'exercises');
    const fixed = join(exercises, 'fixed');
    for (const folder of ['bridge', 'tools', 'corpus']) await cp(join(session, 'exercises/fixed', folder), join(fixed, folder), { recursive: true });
    const root = join(exercises, 'evidence bundle');
    await mkdir(join(root, 'sources'), { recursive: true });
    const raw = 'Début 🚚\r\ne\u0301nergie — coût\r\nfin\n';
    const text = raw.replaceAll('\r\n', '\n').normalize('NFC');
    const codepoints = [...text];
    await writeFile(join(root, 'sources/source with spaces.md'), raw, 'utf8');
    await writeFile(join(root, 'corpus.json'), JSON.stringify({ sources: [{ source_id: 'DOC', path: 'sources/source with spaces.md', passages: [
      { passage_id: 'DOC:P1', start: 0, end: codepoints.length, quote: text },
    ] }] }));
    // Invoke the copied Python dispatcher to exercise its own import resolution independently of cwd.
    const request = { tool: 'read', arguments: { source_id: 'DOC', start: 2, end: codepoints.length }, run_id: 'unicode', tool_call_id: 'read-1' };
    const direct = spawnSync(python, ['-m', 'exercises.fixed.bridge.dispatch', root], { input: JSON.stringify(request), encoding: 'utf8', cwd: join(temp, 'session with spaces'), shell: false });
    assert.equal(direct.status, 0, direct.stderr);
    const expected = JSON.parse(direct.stdout);
    assert.equal(expected.result.data.text, codepoints.slice(2).join(''));
    const config = { caseRoot: root, python, runId: 'unicode' };
    const result = await callTool(config, 'read', request.arguments, 'read-1');
    assert.deepEqual(result, expected);
    assert.deepEqual(result.audit.passage_ids, ['DOC:P1']);
    assert.equal(result.result.data.span.end, codepoints.length);
    const search = await callTool(config, 'search', { query: 'énergie' }, 'search-1');
    assert.equal(search.result.data[0].text, text);
    assert.equal(search.audit.hits[0].passage_id, 'DOC:P1');
    const invalid = await callTool(config, 'read', { source_id: '../reference.json' }, 'bad-1');
    assert.deepEqual(invalid.result.error, { code: 'invalid_input', retryable: false });
    assert.deepEqual(invalid.invocation.arguments, { source_id: '../reference.json' });
  } finally { await rm(temp, { recursive: true, force: true }); }
});

test('protocol bounds, cancellation and missing executable return structured Pi errors', async () => {
  const config = { caseRoot: join(cases, 'c-audit'), python };
  const tool = createResearchTools(config)[1];
  const oversized = await tool.execute('oversized', { query: 'x'.repeat(limits.requestBytes) });
  assert.equal(oversized.isError, true);
  assert.equal(oversized.details.error.code, 'invalid_input');
  const controller = new AbortController(); controller.abort();
  const cancelled = await tool.execute('cancelled', { query: 'cost' }, controller.signal);
  assert.equal(cancelled.details.error.code, 'cancelled');
  const missing = await createResearchTools({ ...config, python: join(session, 'missing-python') })[0].execute('missing', { source_id: 'EV-S13' });
  assert.equal(missing.isError, true);
  assert.equal(missing.details.error.code, 'service_error');
  const bounded = await tool.execute('limit', { query: 'cost', limit: limits.hits + 1 });
  assert.equal(bounded.details.result.error.code, 'invalid_input');
  await assert.rejects(callTool(config, 'shell', { command: 'echo nope' }, 'shell-1'), e => e instanceof BridgeError && e.code === 'invalid_input');
});

test('documented offline inspection prints real schemas and evidence without API access', () => {
  const result = spawnSync(process.execPath, ['exercises/fixed/bridge/inspect.ts', '--case', 'exercises/cases/c-audit'], {
    cwd: session, encoding: 'utf8', shell: false,
  });
  assert.equal(result.status, 0, result.stderr);
  const inspected = JSON.parse(result.stdout);
  assert.deepEqual(Object.keys(inspected.schemas), ['read', 'search', 'check_table']);
  assert.equal(inspected.sample.result.status, 'ok');
  assert(inspected.sample.result.data.length > 0);
});
