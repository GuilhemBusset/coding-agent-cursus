import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { chromium, browserExecutable, browserLibDirs, withBrowserLibs } from '../browser.mjs';

const libDirs = ['root/usr/lib/x86_64-linux-gnu', 'root/lib/x86_64-linux-gnu'];

// A --dest directory as setup/browser-libs.py leaves it: a `current` pointer and one copy.
async function libsDest(t) {
  const dest = await mkdtemp(path.join(tmpdir(), 'cursus-browser-libs-'));
  t.after(() => rm(dest, { recursive: true, force: true }));
  const copy = path.join(dest, 'libs-0123456789abcdef');
  for (const dir of libDirs) await mkdir(path.join(copy, dir), { recursive: true });
  await writeFile(path.join(copy, 'manifest.json'), JSON.stringify({ lib_dirs: libDirs }));
  await writeFile(path.join(dest, 'current'), 'libs-0123456789abcdef\n');
  return { dest, dirs: libDirs.map(dir => path.join(copy, dir)) };
}

// Sets environment variables for one test (undefined deletes) and restores them afterwards.
function setEnv(t, values) {
  const saved = Object.fromEntries(Object.keys(values).map(name => [name, process.env[name]]));
  const apply = entries => {
    for (const [name, value] of Object.entries(entries)) {
      if (value === undefined) delete process.env[name];
      else process.env[name] = value;
    }
  };
  apply(values);
  t.after(() => apply(saved));
}

// Records launch options instead of starting a browser.
function stubBrowserType() {
  const calls = [];
  const type = {
    name: () => 'chromium',
    executablePath: () => '/stub/chrome',
    launch: async options => { calls.push(['launch', options]); return 'browser'; },
    launchServer: async options => { calls.push(['launchServer', options]); return 'server'; },
    launchPersistentContext: async (userDataDir, options) => { calls.push(['launchPersistentContext', options, userDataDir]); return 'context'; },
  };
  return { calls, type };
}

test('the unpacked libraries reach every browser launch env and never process.env', async t => {
  const { dest, dirs } = await libsDest(t);
  setEnv(t, { CURSUS_BROWSER_LIBS: dest, LD_LIBRARY_PATH: '/host/lib', PWDEBUG: undefined });
  const before = { ...process.env };
  const { calls, type } = stubBrowserType();
  const wrapped = withBrowserLibs(type, options => (options.headless === false ? '/stub/chrome' : '/stub/headless-shell'));
  assert.equal(await wrapped.launch(), 'browser');
  assert.equal(await wrapped.launchServer({ headless: false }), 'server');
  assert.equal(await wrapped.launchPersistentContext('/profile', {}), 'context');
  assert.deepEqual(calls.map(([name]) => name), ['launch', 'launchServer', 'launchPersistentContext']);
  for (const [, options] of calls) {
    assert.equal(options.env.LD_LIBRARY_PATH, [...dirs, '/host/lib'].join(path.delimiter));
    assert.equal(options.env.PATH, process.env.PATH, 'the rest of the environment is passed through');
  }
  assert.deepEqual(calls.map(([, options]) => options.executablePath), ['/stub/headless-shell', '/stub/chrome', '/stub/headless-shell']);
  assert.equal(calls[2][2], '/profile');
  assert.deepEqual({ ...process.env }, before, 'process.env is unchanged');
  assert.equal(process.env.LD_LIBRARY_PATH, '/host/lib');
});

test('a caller env is extended, its options are not mutated, and its executable is kept', async t => {
  const { dest, dirs } = await libsDest(t);
  setEnv(t, { CURSUS_BROWSER_LIBS: dest, LD_LIBRARY_PATH: undefined });
  const { calls, type } = stubBrowserType();
  const wrapped = withBrowserLibs(type, () => '/stub/headless-shell');
  const options = Object.freeze({ env: Object.freeze({ ONLY: '1' }), executablePath: '/mine/chrome' });
  await wrapped.launch(options);
  assert.deepEqual(calls[0][1], { env: { ONLY: '1', LD_LIBRARY_PATH: dirs.join(path.delimiter) }, executablePath: '/mine/chrome' });
  assert.equal(process.env.LD_LIBRARY_PATH, undefined);
});

test('without CURSUS_BROWSER_LIBS the launch options pass through untouched', async t => {
  setEnv(t, { CURSUS_BROWSER_LIBS: undefined });
  const { calls, type } = stubBrowserType();
  const wrapped = withBrowserLibs(type, () => assert.fail('no executable is chosen without libraries'));
  const options = { headless: true };
  await wrapped.launch(options);
  await wrapped.launch();
  assert.equal(calls[0][1], options);
  assert.equal(calls[1][1], undefined);
  assert.equal(wrapped.executablePath(), '/stub/chrome');
});

test('the copy is found from its --dest directory or directly, and a missing one fails clearly', async t => {
  const { dest, dirs } = await libsDest(t);
  assert.deepEqual(browserLibDirs(dest), dirs);
  assert.deepEqual(browserLibDirs(path.join(dest, 'libs-0123456789abcdef')), dirs);
  assert.deepEqual(browserLibDirs(''), []);
  setEnv(t, { CURSUS_BROWSER_LIBS: path.join(dest, 'missing') });
  const { calls, type } = stubBrowserType();
  await assert.rejects(withBrowserLibs(type).launch(), /holds no activated library copy/);
  assert.equal(calls.length, 0);
});

test('the exported chromium is still Playwright\'s, and the chosen executable matches its pick', t => {
  setEnv(t, { PWDEBUG: undefined });
  assert.equal(chromium.name(), 'chromium');
  assert.match(chromium.executablePath(), /chrom/i);
  assert.equal(browserExecutable({ headless: false }), chromium.executablePath());
  assert.match(browserExecutable({}), /headless[-_]shell/);
  assert.equal(browserExecutable({ channel: 'chrome' }), undefined);
  assert.equal(browserExecutable({ executablePath: '/mine/chrome' }), undefined);
});
