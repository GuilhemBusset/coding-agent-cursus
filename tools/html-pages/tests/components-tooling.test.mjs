import test from 'node:test';
import assert from 'node:assert/strict';
import { copyFile, mkdir, readFile, writeFile } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { createPage } from '../create-page.mjs';
import { repoRoot, sample, read, scratch, assertCollected } from './component-helpers.mjs';
import { completePass } from './run-suite.mjs';
import { discoverSuites, testsDir } from './suites.mjs';

// A child runner is a new runner, not a worker of this runner's binary IPC protocol.
const childEnv = { ...process.env };
delete childEnv.NODE_TEST_CONTEXT;
delete childEnv.NODE_TEST_WORKER_ID;

test('D5: npm --prefix setup test runs the discovery runner, which collects this suite', async () => {
  await assertCollected('components-tooling');
});

test('D5: the npm runner runs every suite it discovers, and picks up a newly added one', async t => {
  // The real runner and discovery module, copied next to fixture suites: they list their own directory.
  const dir = await scratch(t);
  for (const name of ['run-all.mjs', 'suites.mjs']) await copyFile(path.join(testsDir, name), path.join(dir, name));
  const suite = name => `import test from 'node:test'; test('suite ${name}', () => {});\n`;
  const boom = "throw new Error('not a suite: must never run');\n";
  await writeFile(path.join(dir, 'alpha.test.mjs'), suite('alpha'));
  await writeFile(path.join(dir, 'helper.mjs'), boom);
  await writeFile(path.join(dir, 'alpha.test.mjs.bak'), boom);
  await mkdir(path.join(dir, 'nested'));
  await writeFile(path.join(dir, 'nested', 'deep.test.mjs'), boom);
  await mkdir(path.join(dir, 'folder.test.mjs'));
  const run = () => {
    const result = spawnSync(process.execPath, [path.join(dir, 'run-all.mjs'), '--test-reporter=tap'],
      { cwd: dir, encoding: 'utf8', timeout: 30000, env: childEnv });
    assert.ifError(result.error);
    return { ...result, ran: [...result.stdout.matchAll(/^ok \d+ - suite (\w+)$/gm)].map(match => match[1]).sort() };
  };
  const files = names => names.map(name => path.join(dir, `${name}.test.mjs`));

  assert.deepEqual(discoverSuites(dir), files(['alpha']));
  let result = run();
  assert.equal(result.status, 0, result.stdout + result.stderr);
  assert.deepEqual(result.ran, ['alpha']);
  assert.ok(completePass(result.stdout, result.status), 'one complete passing run');

  await writeFile(path.join(dir, 'beta.test.mjs'), suite('beta'));
  assert.deepEqual(discoverSuites(dir), files(['alpha', 'beta']));
  result = run();
  assert.equal(result.status, 0, result.stdout + result.stderr);
  assert.deepEqual(result.ran, ['alpha', 'beta'], 'a new suite is collected without registering it anywhere');

  await writeFile(path.join(dir, 'gamma.test.mjs'), "import test from 'node:test'; test('suite gamma', () => { throw Error('deliberate'); });\n");
  result = run();
  assert.equal(result.status, 1, 'a failing discovered suite fails npm test');
  assert.deepEqual(result.ran, ['alpha', 'beta']);
  assert.match(result.stdout, /^not ok \d+ - suite gamma$/m);
});

// The component suites exercise page.js through the sample page, so it must carry the current
// assets; new pages start from them.
test('D5: every generator kind and the sample embed the current shared style and script', async t => {
  const dir = await scratch(t);
  const style = await read('tools/html-pages/assets/theme.css'), script = await read('tools/html-pages/assets/page.js');
  for (const kind of ['page', 'deck', 'lab']) {
    const out = path.join(dir, `${kind}.html`);
    await createPage({ kind, title: 'Shared component provenance', out });
    const html = await readFile(out, 'utf8');
    assert.ok(html.includes(style), `${kind}: exact CSS snapshot`);
    assert.ok(html.includes(script), `${kind}: exact JS snapshot`);
  }
  const html = await readFile(sample, 'utf8');
  assert.ok(html.includes(style), 'sample: exact CSS snapshot');
  assert.ok(html.includes(script), 'sample: exact JS snapshot');
});

test('D5: suite runner rejects empty, skipped, todo, cancelled and failing evidence', async t => {
  const good = 'TAP version 13\nok 1 - example\n1..1\n# tests 1\n# suites 0\n# pass 1\n# fail 0\n# cancelled 0\n# skipped 0\n# todo 0\n';
  assert.equal(completePass(good, 0), true);
  assert.equal(completePass(good, 1), false);
  assert.equal(completePass('', 0), false);
  assert.equal(completePass(good.replace('# tests 1', '# tests 0').replace('# pass 1', '# pass 0'), 0), false);
  for (const name of ['fail', 'cancelled', 'skipped', 'todo']) assert.equal(completePass(good.replace(`# ${name} 0`, `# ${name} 1`), 0), false);
  for (const directive of ['SKIP', 'TODO']) assert.equal(completePass(good.replace('ok 1 - example', `ok 1 - example # ${directive}`), 0), false);
  const dir = await scratch(t);
  // The command line applies that accounting: a passing suite passes, a skipped one is rejected.
  for (const [name, source, expected] of [
    ['pass', "import test from 'node:test'; test('real test', () => {});", 0],
    ['skip', "import test from 'node:test'; test.skip('not evidence', () => {});", 1],
  ]) {
    const file = path.join(dir, `${name}.mjs`);
    await writeFile(file, source);
    const result = spawnSync(process.execPath, [path.join(repoRoot, 'tools/html-pages/tests/run-suite.mjs'), file], { encoding: 'utf8', timeout: 15000, env: childEnv });
    assert.ifError(result.error);
    assert.equal(result.status, expected, result.stdout + result.stderr);
  }
});
