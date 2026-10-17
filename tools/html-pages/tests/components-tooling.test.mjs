import test from 'node:test';
import assert from 'node:assert/strict';
import { copyFile, mkdir, readdir, readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { chromium } from '../browser.mjs';
import { createPage } from '../create-page.mjs';
import { repoRoot, sample, read, suites, scratch, openPage, count, assertCollected } from './component-helpers.mjs';
import { completePass } from './run-suite.mjs';
import { discoverSuites, testsDir } from './suites.mjs';

// A child runner is a new runner, not a worker of this runner's binary IPC protocol.
const childEnv = { ...process.env };
delete childEnv.NODE_TEST_CONTEXT;
delete childEnv.NODE_TEST_WORKER_ID;

test('D5: npm collects all Node suites using the unchanged pinned browser dependencies', async () => {
  const pkg = JSON.parse(await read('setup/package.json'));
  // The test script runs the discovery runner with no filter; discovery is the directory listing.
  await assertCollected('components-tooling');
  const present = (await readdir(testsDir, { withFileTypes: true }))
    .filter(entry => entry.isFile() && entry.name.endsWith('.test.mjs')).map(entry => path.join(testsDir, entry.name));
  assert.ok(present.length > 1, 'the suites in tools/html-pages/tests are found');
  assert.deepEqual(discoverSuites(), present.sort(), 'discovery yields exactly the *.test.mjs files present');
  assert.deepEqual(suites, present.map(file => path.basename(file, '.test.mjs')), 'component-helpers suites come from the directory');
  assert.equal(pkg.devDependencies.playwright, '1.63.0');
  assert.equal(pkg.devDependencies['@axe-core/playwright'], '4.13.0');
  for (const file of present) {
    const source = await readFile(file, 'utf8');
    assert.match(source, /import\s+[^;]+\s+from\s+['"]node:test['"]/, file);
    assert.match(source, /import\s+[^;]+\s+from\s+['"]\.\.\/browser\.mjs['"]/, file);
  }
  async function visit(dir) {
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      assert.ok(!entry.name.endsWith('.py'), `Python adapter not allowed: ${entry.name}`);
      if (entry.isDirectory()) await visit(path.join(dir, entry.name));
    }
  }
  await visit(path.join(repoRoot, 'tools/html-pages/tests'));
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

test('D5: every generator kind embeds shared components, and the sample has current snapshot hashes', async t => {
  const dir = await scratch(t);
  const style = await read('tools/html-pages/assets/theme.css'), script = await read('tools/html-pages/assets/page.js');
  for (const kind of ['page', 'deck', 'lab']) {
    const out = path.join(dir, `${kind}.html`);
    await createPage({ kind, title: 'Shared component provenance', out });
    const html = await readFile(out, 'utf8');
    assert.ok(html.includes(style), `${kind}: exact CSS snapshot`);
    assert.ok(html.includes(script), `${kind}: exact JS snapshot`);
    assert.match(html, /\/\* components:begin \*\/[\s\S]+?\/\* components:end \*\//);
    for (const fn of ['enhancePredict', 'enhanceProbChart', 'enhanceFormula', 'enhanceStepper']) assert.match(html, new RegExp(`function\\s+${fn}\\s*\\(`));
  }
  const page = await openPage(t, chromium, { javaScriptEnabled: false });
  for (const [name, asset] of [['theme', style], ['script', script]]) {
    const meta = page.locator(`meta[name="cursus-${name}-sha256"]`);
    await count(meta, 1);
    assert.equal(await meta.getAttribute('content'), createHash('sha256').update(asset).digest('hex'));
  }
  const html = await readFile(sample, 'utf8');
  assert.ok(html.includes(style));
  assert.ok(html.includes(script));
  assert.equal(await page.locator('html').getAttribute('data-page-kind'), 'page');
  assert.equal(await page.locator('html').getAttribute('data-design-system'), 'cursus');
  assert.equal(await page.locator('[data-lab], [data-reset]').count(), 0);
  const reserved = await page.locator('*').evaluateAll(els => els.flatMap(el => Array.from(el.attributes).map(a => a.name)).filter(name => name.startsWith('data-budget')));
  assert.deepEqual(reserved, []);
  assert.match(await page.locator('body').innerText(), /illustrative/i);
});

test('D5: guide records the attribute contracts, events, fallback and keyboard scope', async () => {
  const guide = await read('tools/html-pages/GUIDE.md');
  const section = guide.match(/^## Interaction components\s*\n([\s\S]*?)(?=^## |$(?![\s\S]))/m)?.[1];
  assert.ok(section, 'Interaction components section');
  for (const name of ['data-predict', 'data-predict-question', 'data-correct', 'data-predict-answer', 'data-predict-result',
    'data-predict-lock', 'data-predict-reveal', 'data-predict-reset', 'data-predict-status',
    'data-prob-chart', 'data-prob-row', 'data-value', 'data-highlight', 'data-prob-label', 'data-prob-value',
    'data-formula', 'data-formula-input', 'data-formula-output', 'data-formula-reset', 'CursusFormulas',
    'data-stepper', 'data-step', 'data-step-stage', 'data-step-controls', 'data-step-prev', 'data-step-next',
    'data-step-reset', 'data-step-status', 'data-step-current', 'cursus:step', 'data-budget', 'data-reset', 'data-lab']) {
    assert.ok(section.includes(name), `document ${name}`);
  }
  assert.match(section, /DOMContentLoaded/);
  assert.match(section, /print/i);
  assert.match(section, /(?:no[- ](?:JS|JavaScript)|without JavaScript)/i);
  assert.match(section, /keyboard/i);
  assert.match(section, /stage/i);
  assert.match(section, /(?:modifier|modified|shift|ctrl)/i);
  assert.match(section, /detail\.index/);
  assert.match(section, /components\.html/);
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
  for (const [name, source, expected] of [
    ['pass', "import test from 'node:test'; test('real test', () => {});", 0],
    ['skip', "import test from 'node:test'; test.skip('not evidence', () => {});", 1],
    ['todo', "import test from 'node:test'; test.todo('not evidence');", 1],
    ['fail', "import test from 'node:test'; test('bad', () => { throw Error('deliberate failure'); });", 1],
  ]) {
    const file = path.join(dir, `${name}.mjs`);
    await writeFile(file, source);
    const result = spawnSync(process.execPath, [path.join(repoRoot, 'tools/html-pages/tests/run-suite.mjs'), file], { encoding: 'utf8', timeout: 15000, env: childEnv });
    assert.ifError(result.error);
    assert.equal(result.status, expected, result.stdout + result.stderr);
  }
});
