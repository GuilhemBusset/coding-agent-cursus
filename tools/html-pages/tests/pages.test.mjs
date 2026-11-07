import { describe, test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readFile, writeFile } from 'node:fs/promises';
import { availableParallelism } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { spawn } from 'node:child_process';
import { createPage } from '../create-page.mjs';
import { chromium } from '../browser.mjs';

const toolsRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const repoRoot = path.resolve(toolsRoot, '../..');
const artifacts = path.join(repoRoot, 'artifacts/html-pages');
await mkdir(artifacts, { recursive: true });
const scratch = await mkdtemp(path.join(artifacts, 'test-'));

async function check(file, name) {
  const output = path.join(scratch, name);
  const child = spawn(process.execPath, [path.join(toolsRoot, 'check-page.mjs'), file, '--output', output], {
    cwd: repoRoot, stdio: ['ignore', 'pipe', 'pipe'],
  });
  let log = '';
  child.stdout.on('data', chunk => { log += chunk; });
  child.stderr.on('data', chunk => { log += chunk; });
  const code = await new Promise((resolve, reject) => {
    child.on('error', reject);
    child.on('close', resolve);
  });
  const report = JSON.parse(await readFile(path.join(output, 'report.json'), 'utf8'));
  return { code, report, log };
}
const failed = (report, name, scope) => report.checks.some(item => !item.passed && item.name === name && (!scope || item.scope === scope));

// Each check runs check-page.mjs in its own process and browser, so several run at once.
describe('page starters and checker', { concurrency: Math.max(1, Math.min(4, Math.floor(availableParallelism() / 2))) }, () => {
  // First: its broken navigation waits out each slide change, so it is the longest.
  test('checker rejects broken deck navigation, overflow, fallback, motion and print', { timeout: 120000 }, async () => {
    const out = path.join(scratch, 'broken-deck.html');
    await createPage({ kind: 'deck', title: 'Broken deck fixture', out });
    let html = await readFile(out, 'utf8');
    html = html.replace("window.addEventListener('hashchange', readLocation);", '')
      .replace("window.addEventListener('popstate', readLocation);", '')
      .replace('</head>', `<style>
        #define h2 { min-height: 1100px; }
        .masthead { transition: color 1s !important; }
        @media print { [data-slide] { display:none !important; } }
        </style><noscript><style>[data-slide]{display:none!important}</style></noscript></head>`);
    await writeFile(out, html);
    const { code, report } = await check(out, 'broken-deck-review');
    assert.equal(code, 1);
    for (const name of [
      'active slide and hash', 'slide content fits without internal scrolling',
      'deck fallback and initially hidden navigation', 'motion suppressed (10ms threshold)',
      'all deck slides readable and navigation hidden',
    ]) assert.ok(failed(report, name), `Did not catch ${name}`);
  });

  test('generator escapes titles and refuses to overwrite authored content', async () => {
    const out = path.join(scratch, 'title with spaces.html');
    await createPage({ kind: 'page', title: '</title><script>alert("x")</script> & $&', out });
    const before = await readFile(out, 'utf8');
    assert.ok(before.includes('&lt;/title&gt;&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; &amp; $&'));
    await assert.rejects(createPage({ kind: 'lab', title: 'Replacement', out }), { code: 'EEXIST' });
    assert.equal(await readFile(out, 'utf8'), before);
    await assert.rejects(createPage({ kind: '../page', title: 'Bad kind', out }));
  });

  for (const [kind, title] of Object.entries({
    page: 'Define the solve contract', deck: 'Make the change reviewable', lab: 'Context is a budget',
  })) {
    test(`${kind} starter passes the checker straight from disk`, { timeout: 120000 }, async () => {
      const out = path.join(scratch, `${kind}.html`);
      await createPage({ kind, title, out });
      const { code, report, log } = await check(out, `${kind}-review`);
      const failures = report.checks.filter(item => !item.passed);
      assert.equal(code, 0, `${log}\n${JSON.stringify(failures, null, 2)}\n${JSON.stringify(report.events, null, 2)}`);
    });
  }

  test('checker rejects broken delivery, layout, runtime, tooling imports and accessibility', { timeout: 120000 }, async () => {
    const out = path.join(scratch, 'broken.html');
    const tooling = path.relative(scratch, path.join(toolsRoot, 'assets/page.js')).split(path.sep).join('/');
    await writeFile(out, `<!doctype html><html lang="en" data-page-kind="page" data-design-system="cursus">
      <head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Broken fixture</title>
      <style>body{background:#0a1013;color:#e3ece7}main{width:2000px}</style></head>
      <body><main><h1>Broken delivery</h1><button></button><a href="missing.html">Missing page</a>
      <img src="https://example.invalid/remote.png" alt="Remote dependency">
      <img src="missing.png" alt="Missing local asset"></main>
      <script src="${tooling}"></script>
      <script>throw new Error('Intentional fixture error');</script></body></html>`);
    const { code, report } = await check(out, 'broken-review');
    assert.equal(code, 1);
    for (const name of ['no horizontal document overflow', 'local assets and same-document fragments', 'axe serious/critical',
      'runtime assets stay inside session and outside repo tools']) {
      assert.ok(failed(report, name), `Did not catch ${name}`);
    }
    for (const type of ['pageerror', 'remote-request', 'failed-local-resource', 'out-of-scope-runtime-asset']) {
      assert.ok(report.events.some(event => event.type === type), `Did not catch ${type}`);
    }
  });

  test('deck anchors, scrollable code, boundary focus, and unpaging on a small viewport', { timeout: 30000 }, async () => {
    const out = path.join(scratch, 'deck-controls.html');
    await createPage({ kind: 'deck', title: 'Keyboard review', out });
    const html = (await readFile(out, 'utf8')).replace('<h2 id="verify-title">',
      '<pre id="wide-code" tabindex="0" aria-label="Wide example"><code>' + 'value '.repeat(200) + '</code></pre><h2 id="verify-title">');
    await writeFile(out, html);
    const browser = await chromium.launch();
    try {
      const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
      await page.goto(pathToFileURL(out).href);
      await page.evaluate(() => { location.hash = 'verify-title'; });
      await page.waitForFunction(() => !document.getElementById('verify').hidden);
      await page.evaluate(() => { location.hash = 'content'; });
      await page.waitForTimeout(50);
      assert.equal(await page.locator('#verify').isVisible(), true, 'skip link must keep current slide');
      await page.locator('#wide-code').focus();
      const oldScroll = await page.locator('#wide-code').evaluate(el => el.scrollLeft);
      await page.keyboard.press('ArrowRight');
      await page.waitForTimeout(150);
      assert.equal(await page.locator('#verify').isVisible(), true, 'code arrow must not turn slide');
      assert.ok(await page.locator('#wide-code').evaluate(el => el.scrollLeft) > oldScroll, 'focused code can scroll');
      await page.locator('[data-next]').click();
      assert.equal(await page.locator('[data-prev]').evaluate(el => el === document.activeElement), true,
        'last slide keeps focus on an enabled control');
      await page.setViewportSize({ width: 900, height: 500 });
      await page.waitForFunction(() => !document.documentElement.hasAttribute('data-deck-paged'));
      assert.equal(await page.locator('[data-slide]:visible').count(), 3);
    } finally { await browser.close(); }
  });

  test('checker rejects edited shared blocks and a wrong lab computation', { timeout: 120000 }, async () => {
    const out = path.join(scratch, 'drift.html');
    await createPage({ kind: 'lab', title: 'Drift fixture', out });
    const html = await readFile(out, 'utf8');
    await writeFile(out, html.replace('--accent: #3EC3A9', '--accent: #FF00FF')
      .replace('var consumed = fixed + context;', 'var consumed = fixed + context + 100;'));
    const { code, report } = await check(out, 'drift-review');
    assert.equal(code, 1);
    assert.ok(report.checks.some(item => !item.passed && /budget.*(numeric|invariant|arithmetic)/i.test(item.name)), 'Must catch wrong displayed arithmetic');
    assert.ok(failed(report, 'theme snapshot integrity'));
    assert.ok(failed(report, 'script snapshot integrity'));
  });

  test('checker catches an accessibility failure and a tall-screen overflow on one slide of a deck', { timeout: 120000 }, async () => {
    const out = path.join(scratch, 'slide-a11y-deck.html');
    await createPage({ kind: 'deck', title: 'Slide accessibility fixture', out });
    const html = await readFile(out, 'utf8');
    // On the third slide, hidden while slide 1 is active: a nameless button, and a heading that
    // overflows only in the layout decks use on taller screens (desktop, not laptop).
    const broken = html.replace(/(<section id="review" data-slide[^>]*>)/, '$1<button></button>')
      .replace('</head>', '<style>@media screen and (min-width: 800px) and (min-height: 821px) { #review h2 { min-height: 1100px; } }</style></head>');
    assert.notEqual(broken, html, 'the deck template still has a #review slide');
    await writeFile(out, broken);
    const { code, report } = await check(out, 'slide-a11y-review');
    assert.equal(code, 1);
    assert.ok(failed(report, 'axe serious/critical', 'laptop/slide-3'), 'per-slide axe at laptop catches it');
    assert.ok(failed(report, 'axe serious/critical', 'mobile'), 'the mobile run, with every slide shown, catches it');
    assert.ok(failed(report, 'slide content fits without internal scrolling', 'desktop/slide-3'), 'every slide is fitted at desktop too');
  });
});
