#!/usr/bin/env node
// Dependencies and browser installation: setup/README.md.
import { mkdir, mkdtemp, readFile, realpath, stat, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const usage = 'Usage: node tools/html-pages/check-page.mjs <html-file> [--output <directory>]';
const args = process.argv.slice(2);
if (!args[0] || args[0].startsWith('--') ||
    !(args.length === 1 || (args.length === 3 && args[1] === '--output' && args[2]))) {
  console.error(usage);
  process.exit(2);
}
let file;
try {
  if (!['.html', '.htm'].includes(path.extname(args[0]).toLowerCase())) throw new Error('Input must have a .html or .htm extension');
  file = await realpath(args[0]);
  if (!(await stat(file)).isFile()) throw new Error('Input must be a regular file');
} catch (error) {
  console.error(`Invalid HTML file: ${error.message}`);
  process.exit(2);
}

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const relativeFile = path.relative(repoRoot, file);
const pathHash = createHash('sha256').update(relativeFile).digest('hex').slice(0, 12);
const stamp = new Date().toISOString().replace(/[:.]/g, '-');
let output = path.resolve(args[2] ?? path.join(repoRoot, 'artifacts/html-pages', `${path.basename(file, path.extname(file))}-${pathHash}-${stamp}`));
const parts = relativeFile.split(path.sep);
const assetRoot = parts[0] === 'sessions' && parts.length > 2 ? path.join(repoRoot, ...parts.slice(0, 2)) : path.dirname(file);
const within = (root, target) => { const rel = path.relative(root, target); return !path.isAbsolute(rel) && rel !== '..' && !rel.startsWith(`..${path.sep}`); };
async function assetAllowed(target) {
  const lexical = fileURLToPath(target), actual = await realpath(lexical);
  return [lexical, actual].every(p => within(assetRoot, p) &&
    !['tools', 'setup'].some(dir => within(path.join(repoRoot, dir), p)));
}
const url = pathToFileURL(file).href;
const report = {
  file, relativeFile, url, output, assetRoot, colorScheme: 'light', startedAt: new Date().toISOString(), checks: [], events: [], screenshots: [],
  limits: [
    'Perform manual task-specific interaction testing and visual inspection, especially for unmarked labs.',
    'Axe detects only automated accessibility issues; only serious/critical violations fail this checker.',
    'No-JS checks verify visible text and slide availability, not semantic equivalence or useful task completion.',
    'Reduced-motion checks sample running animations and computed styles; delayed, canvas and custom JS motion need manual review.',
    'Print uses emulated print media and beforeprint/afterprint events; screenshots do not verify physical pagination or printer margins.',
    'Network and runtime checks cover only requests/events observed during this run; links are not crawled.',
    'Effective backgrounds composite computed solid colors; gradients, images, overlays and canvas still require visual inspection.',
  ],
};
const check = (scope, name, passed, details) => report.checks.push({ scope, name, passed: Boolean(passed), ...(details === undefined ? {} : { details }) });
const remote = value => /^(https?|wss?|ftp):/i.test(value);
let browser;

async function checkSnapshots(page) {
  const source = await readFile(file, 'utf8');
  for (const [name, tag] of [['theme', 'style'], ['script', 'script']]) {
    const marker = `shared-${tag}`;
    const blocks = [...source.matchAll(new RegExp(`<!-- ${marker}:begin -->\\s*<${tag}[^>]*>([\\s\\S]*?)<\/${tag}>\\s*<!-- ${marker}:end -->`, 'g'))];
    const hashes = await page.locator(`meta[name="cursus-${name}-sha256"]`).evaluateAll(items => items.map(el => el.content));
    const actual = blocks.length === 1 ? createHash('sha256').update(blocks[0][1]).digest('hex') : null;
    check('source', `${name} snapshot integrity`, blocks.length === 1 && hashes.length === 1 && actual === hashes[0], { recorded: hashes, actual, blocks: blocks.length });
  }
}

// All contexts remain on real file URLs. Routing supplements offline mode and records attempts.
async function openContext(viewport, scope, options = {}) {
  const context = await browser.newContext({ viewport, colorScheme: 'light', offline: true, serviceWorkers: 'block', ...options });
  const event = (type, details) => report.events.push({ scope, type, ...details });
  await context.route('**/*', async route => {
    const target = route.request().url();
    if (remote(target)) return route.abort('blockedbyclient');
    if (target.startsWith('file:') && target.split(/[?#]/)[0] !== url) {
      try {
        if (!await assetAllowed(target)) {
          event('out-of-scope-runtime-asset', { url: target });
          return route.abort('blockedbyclient');
        }
      } catch { /* Missing local files are reported by requestfailed and the asset audit. */ }
    }
    await route.continue();
  });
  context.on('request', request => {
    if (remote(request.url())) event('remote-request', { url: request.url() });
  });
  context.on('requestfailed', request => {
    if (request.url().startsWith('file:')) event('failed-local-resource', { url: request.url(), error: request.failure()?.errorText });
  });
  // WebSockets are not governed by HTTP routing/offline consistently across Chromium versions.
  if (context.routeWebSocket) await context.routeWebSocket(/.*/, socket => {
    event('remote-request', { url: socket.url(), transport: 'websocket' });
    socket.close();
  });
  context.on('page', page => {
    page.on('pageerror', error => event('pageerror', { message: error.message }));
    page.on('console', message => {
      if (message.type() === 'error') event('console-error', { message: message.text() });
    });
    page.setDefaultTimeout(4000);
    page.setDefaultNavigationTimeout(15000);
  });
  const page = await context.newPage();
  await page.goto(url, { waitUntil: 'load' });
  await page.waitForTimeout(200);
  return { context, page };
}

async function screenshot(page, name) {
  // Audits can focus scrollable regions; capture the initial view consistently.
  await page.evaluate(() => {
    window.scrollTo(0, 0);
    document.querySelectorAll('[data-slide]').forEach(el => { el.scrollTop = 0; });
  });
  for (const fullPage of [false, true]) {
    const target = path.join(output, `${name}${fullPage ? '' : '-viewport'}.png`);
    await page.screenshot({ path: target, fullPage, animations: 'disabled', timeout: 15000 });
    report.screenshots.push(target);
  }
}

async function inspect(page, scope) {
  const result = await page.evaluate(() => {
    const visible = el => {
      const s = getComputedStyle(el);
      return !el.closest('[hidden],[inert]') && s.visibility !== 'hidden' && s.display !== 'none' && el.getClientRects().length > 0;
    };
    const html = document.documentElement;
    const body = document.body;
    const canvas = document.createElement('canvas'); canvas.width = canvas.height = 1;
    const ctx = canvas.getContext('2d');
    const rgba = color => { ctx.clearRect(0, 0, 1, 1); ctx.fillStyle = color; ctx.fillRect(0, 0, 1, 1); return [...ctx.getImageData(0, 0, 1, 1).data]; };
    const background = el => {
      const colors = []; for (; el; el = el.parentElement) colors.unshift(getComputedStyle(el).backgroundColor);
      ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, 1, 1);
      for (const color of colors) { ctx.fillStyle = color; ctx.fillRect(0, 0, 1, 1); }
      const rgb = [...ctx.getImageData(0, 0, 1, 1).data].slice(0, 3);
      const linear = rgb.map(v => { v /= 255; return v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; });
      return { colors, rgb, luminance: linear[0] * .2126 + linear[1] * .7152 + linear[2] * .0722 };
    };
    // Add approved future palettes; keep older ones valid for historical snapshots.
    const palettes = [{ '--paper': '#0A1013', '--sheet': '#111B1F', '--ink': '#E3ECE7', '--accent': '#3EC3A9', '--amber': '#E4A94A', '--red': '#F07A70' }];
    const surfaces = [html, body, ...document.querySelectorAll('.shell')].filter(Boolean);
    const tokens = palettes.map(expected => surfaces.flatMap(el => Object.entries(expected).map(([token, wanted]) => {
      const actual = getComputedStyle(el).getPropertyValue(token).trim();
      return { element: el.tagName + (el.className ? `.${el.className}` : ''), token, actual, expected: wanted,
        passed: Boolean(actual) && CSS.supports('color', actual) && String(rgba(actual)) === String(rgba(wanted)) };
    })));
    const slides = [...document.querySelectorAll('[data-deck] [data-slide]')];
    const comments = [], walker = document.createTreeWalker(document, NodeFilter.SHOW_COMMENT);
    while (walker.nextNode()) {
      const text = walker.currentNode.textContent.trim();
      if (/snapshot|(?:theme|script|style).*(?:version|sha256|hash)|shared-(?:style|script):begin/i.test(text)) comments.push({ comment: text.slice(0, 2000) });
    }
    return {
      lang: html.lang.trim(), title: document.title.trim(), viewport: document.querySelector('meta[name="viewport"]')?.content ?? '',
      kind: html.dataset.pageKind, design: html.dataset.designSystem,
      background: background(body ?? html), shells: [...document.querySelectorAll('.shell')].filter(visible).map(background), tokens,
      snapshots: comments.concat([...document.querySelectorAll('meta[name],html,style,script')].flatMap(el => [...el.attributes]
        .filter(a => /theme|script|snapshot|version|sha256/i.test(a.name === 'name' ? a.value : a.name))
        .map(a => ({ tag: el.tagName, attribute: a.name, value: a.value, content: el.getAttribute('content') })))),
      overflow: Math.max(html.scrollWidth, body?.scrollWidth ?? 0) - html.clientWidth,
      text: body?.innerText.trim().length ?? 0,
      brokenImages: [...document.images].filter(el => visible(el) && el.complete && !el.naturalWidth && (el.src || el.srcset)).map(el => el.currentSrc || el.src),
      assets: [...document.querySelectorAll('[src],link[href],a[href],object[data]')].map(el => ({
        tag: el.tagName, runtime: el.hasAttribute('src') || el.matches('link[rel~="stylesheet"],object[data]'),
        value: el.getAttribute('src') ?? el.getAttribute('href') ?? el.getAttribute('data'),
      })).filter(item => item.value).map(item => ({ ...item, resolved: new URL(item.value, document.baseURI).href })),
      ids: [...document.querySelectorAll('[id]')].map(el => el.id),
      deck: { roots: document.querySelectorAll('[data-deck]').length, slides: slides.map(el => ({ id: el.id, visible: visible(el), text: el.innerText.trim().length })),
        navCount: document.querySelectorAll('nav[data-deck-nav]').length,
        navVisible: [...document.querySelectorAll('nav[data-deck-nav]')].some(visible) },
    };
  });
  check(scope, 'html contract', ['page', 'deck', 'lab'].includes(result.kind) && result.design === 'cursus', { kind: result.kind, design: result.design });
  check(scope, 'document language', result.lang.length > 0);
  check(scope, 'document title', result.title.length > 0);
  check(scope, 'responsive viewport', /width\s*=\s*device-width/i.test(result.viewport), result.viewport);
  report.snapshots ??= result.snapshots;
  check(scope, 'dark palette tokens', result.tokens.some(palette => palette.every(t => t.passed)), result.tokens);
  check(scope, 'dark computed background', result.background.luminance < .25, result.background);
  check(scope, 'dark effective shell backgrounds', result.shells.every(s => s.luminance < .25), result.shells);
  check(scope, 'no horizontal document overflow', result.overflow <= 1, { pixels: result.overflow });
  check(scope, 'visible document text', result.text > 0);
  check(scope, 'loaded visible images', !result.brokenImages.length, result.brokenImages);
  const broken = [], escaped = [];
  for (const asset of result.assets) {
    const target = new URL(asset.resolved);
    if (target.protocol !== 'file:') continue;
    try {
      const assetPath = fileURLToPath(target);
      await stat(assetPath);
      if (asset.runtime && !await assetAllowed(target)) escaped.push(asset);
      if (assetPath === file && target.hash && target.hash !== '#') {
        const id = decodeURIComponent(target.hash.slice(1));
        if (!result.ids.includes(id)) broken.push({ ...asset, error: `Missing fragment ${id}` });
      }
    } catch (error) { broken.push({ ...asset, error: error.message }); }
  }
  check(scope, 'local assets and same-document fragments', !broken.length, broken);
  check(scope, 'runtime assets stay inside session and outside repo tools', !escaped.length, escaped);
  if (result.kind === 'deck' || result.deck.roots) {
    const ids = result.deck.slides.map(slide => slide.id);
    check(scope, 'deck structure', result.deck.roots === 1 && ids.length > 0 && ids.every(Boolean) && new Set(ids).size === ids.length && result.deck.navCount === 1, result.deck);
  }
  return result;
}

async function axeCheck(page, scope, AxeBuilder) {
  const results = await new AxeBuilder({ page }).analyze();
  const violations = results.violations.filter(v => ['serious', 'critical'].includes(v.impact));
  check(scope, 'axe serious/critical', !violations.length, violations.map(v => ({
    id: v.id, impact: v.impact, description: v.description, helpUrl: v.helpUrl,
    nodes: v.nodes.map(n => ({ target: n.target, summary: n.failureSummary })),
  })));
}

async function deckState(page, scope, id) {
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(100);
  const state = await page.evaluate(() => ({
    hash: decodeURIComponent(location.hash.slice(1)),
    slides: [...document.querySelectorAll('[data-deck] [data-slide]')].filter(el => {
      const s = getComputedStyle(el);
      return !el.hidden && s.display !== 'none' && s.visibility !== 'hidden' && el.getClientRects().length;
    }).map(el => el.id),
    bounds: [...document.querySelectorAll('[data-deck] [data-slide],nav[data-deck-nav]')].filter(el => el.checkVisibility()).map(el => {
      const r = el.getBoundingClientRect();
      return { id: el.id || 'deck-nav', x: r.x, y: r.y, width: r.width, height: r.height,
        contentFits: el.scrollHeight <= el.clientHeight + 1 && el.scrollWidth <= el.clientWidth + 1,
        fits: r.width > 0 && r.height > 0 && r.left >= -1 && r.top >= -1 && r.right <= innerWidth + 1 && r.bottom <= innerHeight + 1 };
    }),
    status: document.querySelector('[data-slide-status]')?.textContent.trim(),
  }));
  check(scope, 'active slide and hash', state.hash === id && state.slides.length === 1 && state.slides[0] === id && Boolean(state.status), state);
  check(scope, 'active slide and navigation fit viewport', state.bounds.length === 2 && state.bounds.every(b => b.fits), state.bounds);
  check(scope, 'slide content fits without internal scrolling', state.bounds.every(b => b.contentFits), state.bounds);
}

async function testDeck(page, scope, slides, AxeBuilder) {
  const next = page.locator('button[data-next]');
  const prev = page.locator('button[data-prev]');
  const controls = await next.count() === 1 && await prev.count() === 1 && await page.locator('[data-slide-status]').count() === 1;
  check(scope, 'deck controls', controls);
  if (!slides.length || slides.some(s => !s.id)) return;
  const navigate = async id => { await page.evaluate(id => { location.hash = id; }, id); await page.waitForTimeout(100); };
  await navigate(slides[0].id);
  if (controls && slides.length > 1) {
    const originalStatus = await page.locator('[data-slide-status]').textContent();
    await next.click();
    await deckState(page, `${scope}/next`, slides[1].id);
    check(scope, 'slide status updates', (await page.locator('[data-slide-status]').textContent()) !== originalStatus);
    await prev.click();
    await deckState(page, `${scope}/prev`, slides[0].id);
    await navigate(slides[1].id);
    await deckState(page, `${scope}/hash`, slides[1].id);
    await page.goBack();
    await deckState(page, `${scope}/back`, slides[0].id);
    await page.goForward();
    await deckState(page, `${scope}/forward`, slides[1].id);
    // Navigation buttons intentionally keep focus after clicks; shortcuts must be tested outside them.
    await page.evaluate(() => document.activeElement?.blur());
    for (const [key, id] of [['Home', slides[0].id], ['ArrowRight', slides[1].id],
      ['ArrowLeft', slides[0].id], ['End', slides.at(-1).id]]) {
      await page.keyboard.press(key);
      await deckState(page, `${scope}/keyboard-${key}`, id);
    }
  }
  for (const [index, slide] of slides.entries()) {
    await navigate(slide.id);
    const slideScope = `${scope}/slide-${index + 1}`;
    await deckState(page, slideScope, slide.id);
    await inspect(page, slideScope);
    await axeCheck(page, slideScope, AxeBuilder);
    await screenshot(page, `${scope}-slide-${String(index + 1).padStart(2, '0')}`);
  }
}

async function testLab(page, scope) {
  const range = page.locator('input[type="range"][data-budget]');
  const value = page.locator('output[data-budget-output]');
  const reset = page.locator('[data-reset]');
  const any = await page.locator('[data-budget],[data-budget-output],[data-reset]').count();
  if (!any) return;
  const valid = await range.count() === 1 && await value.count() === 1 && await reset.count() === 1;
  check(scope, 'budget lab markers', valid);
  if (!valid) return;
  const initial = await range.inputValue();
  const initialOutput = await value.textContent();
  const hasMetrics = await page.locator('[data-budget-used],[data-budget-remaining],[data-budget-meter]').count() > 0;
  async function invariant(stage) {
    const state = await range.evaluate(el => {
      const root = el.closest('[data-lab]') ?? document;
      const number = text => Number(text?.replaceAll(',', '').trim() ?? NaN);
      const meter = root.querySelector('[data-budget-meter]');
      return {
        budget: Number(el.value), min: Number(el.min || 0), max: Number(el.max || 100),
        output: number(root.querySelector('[data-budget-output]')?.textContent),
        total: number(root.getAttribute?.('data-budget-total')),
        fixed: number(root.getAttribute?.('data-budget-fixed')),
        used: number(root.querySelector('[data-budget-used]')?.textContent),
        remaining: number(root.querySelector('[data-budget-remaining]')?.textContent),
        meter: meter?.value, meterMin: meter?.min, meterMax: meter?.max,
      };
    });
    const near = (a, b) => Number.isFinite(a) && Number.isFinite(b) && Math.abs(a - b) < 1e-7;
    check(`${scope}/${stage}`, 'numeric budget output', near(state.output, state.budget), state);
    if (stage === 'Home' || stage === 'End') check(`${scope}/${stage}`, 'budget endpoint', near(state.budget, stage === 'Home' ? state.min : state.max), state);
    if (hasMetrics) check(`${scope}/${stage}`, 'budget used/remaining/meter invariant',
      state.total > 0 && state.fixed >= 0 && state.remaining >= 0 &&
      near(state.used, state.fixed + state.budget) && near(state.used + state.remaining, state.total) &&
      near(state.meter, state.used) && near(state.meterMin, 0) && near(state.meterMax, state.total), state);
  }
  await invariant('initial');
  let changed = false;
  for (const key of ['Home', 'End']) {
    await range.focus();
    await range.press(key);
    await page.waitForTimeout(100);
    changed ||= await range.inputValue() !== initial && await value.textContent() !== initialOutput;
    await invariant(key);
  }
  check(scope, 'budget changes output', changed);
  await reset.click();
  await page.waitForTimeout(100);
  check(scope, 'budget reset restores value and output', await range.inputValue() === initial && await value.textContent() === initialOutput);
  await invariant('reset');
}

async function testPrint(page) {
  const before = await page.locator('details').evaluateAll(items => items.map(el => el.open));
  await page.emulateMedia({ media: 'print' });
  await page.evaluate(() => window.dispatchEvent(new Event('beforeprint')));
  await page.waitForTimeout(100);
  const state = await page.evaluate(() => {
    const visible = el => el.checkVisibility({ checkVisibilityCSS: true, checkOpacity: true }) && el.getClientRects().length > 0;
    return {
      slides: [...document.querySelectorAll('[data-deck] [data-slide]')].map(el => ({ id: el.id, visible: visible(el) && el.innerText.trim().length > 0 })),
      navVisible: [...document.querySelectorAll('nav[data-deck-nav]')].some(visible),
      details: [...document.querySelectorAll('details')].map(el => ({
        open: el.open,
        visible: visible(el) && [...el.children].filter(child => child.tagName !== 'SUMMARY').every(visible) &&
          (el.open || getComputedStyle(el, '::details-content').contentVisibility === 'visible'),
      })),
    };
  });
  check('print', 'all deck slides readable and navigation hidden', state.slides.every(s => s.visible) && !state.navVisible, state.slides);
  check('print', 'disclosure contents visible including initially closed details', state.details.every(d => d.visible), { initiallyOpen: before, details: state.details });
  await screenshot(page, 'print');
  await page.evaluate(() => window.dispatchEvent(new Event('afterprint')));
  await page.emulateMedia({ media: 'screen' });
  await page.waitForTimeout(100);
  const after = await page.locator('details').evaluateAll(items => items.map(el => el.open));
  check('print', 'disclosure state restored', JSON.stringify(before) === JSON.stringify(after), { before, after });
}

try {
  if (args[2]) await mkdir(output, { recursive: true });
  else {
    await mkdir(path.dirname(output), { recursive: true });
    output = await mkdtemp(`${output}-`); // Atomic suffix also isolates simultaneous runs in the same millisecond.
    report.output = output;
  }
  const { chromium, AxeBuilder } = await import('./browser.mjs');
  browser = await chromium.launch();
  const viewports = { desktop: { width: 1440, height: 900 }, laptop: { width: 1280, height: 720 }, mobile: { width: 390, height: 844 } };
  for (const [scope, viewport] of Object.entries(viewports)) {
    let context;
    try {
      const opened = await openContext(viewport, scope);
      context = opened.context;
      const page = opened.page;
      if (scope === 'desktop') await checkSnapshots(page);
      const result = await inspect(page, scope);
      await axeCheck(page, scope, AxeBuilder);
      await screenshot(page, scope);
      if (result.deck.roots) {
        if (scope === 'mobile') {
          check(scope, 'all slides readable and navigation hidden', result.deck.slides.every(s => s.visible && s.text > 0) && !result.deck.navVisible, result.deck);
        } else {
          check(scope, 'desktop deck presentation', result.deck.navVisible && result.deck.slides.filter(s => s.visible).length === 1, result.deck);
          await testDeck(page, scope, result.deck.slides, AxeBuilder);
        }
      }
      await testLab(page, scope);
    } catch (error) { check(scope, 'browser checks completed', false, error.message); }
    finally { await context?.close(); }
  }
  for (const mode of ['no-js', 'reduced-motion', 'print']) {
    let context;
    try {
      const opened = await openContext(viewports.desktop, mode, mode === 'no-js' ? { javaScriptEnabled: false } : mode === 'reduced-motion' ? { reducedMotion: 'reduce' } : {});
      context = opened.context;
      const page = opened.page;
      if (mode === 'print') {
        await testPrint(page);
        continue;
      }
      const result = await inspect(page, mode);
      if (mode === 'no-js' && result.deck.roots) {
        check(mode, 'deck fallback and initially hidden navigation', result.deck.slides.every(s => s.visible && s.text > 0) && !result.deck.navVisible && await page.locator('nav[data-deck-nav][hidden]').count() === 1, result.deck);
      }
      if (mode === 'reduced-motion') {
        const motion = await page.evaluate(() => ({
          matches: matchMedia('(prefers-reduced-motion: reduce)').matches,
          animations: document.getAnimations().filter(a => a.playState === 'running' && Number(a.effect?.getTiming().duration) > 10).length,
          elements: [...document.querySelectorAll('*')].filter(el => {
            if (!el.getClientRects().length) return false;
            const s = getComputedStyle(el);
            const long = value => value.split(',').some(v => parseFloat(v) * (v.trim().endsWith('ms') ? 1 : 1000) > 10);
            return s.scrollBehavior === 'smooth' || long(s.transitionDuration) || (s.animationName !== 'none' && long(s.animationDuration));
          }).slice(0, 20).map(el => ({ tag: el.tagName, id: el.id })),
        }));
        check(mode, 'motion suppressed (10ms threshold)', motion.matches && motion.animations === 0 && !motion.elements.length, motion);
      }
      await screenshot(page, mode);
    } catch (error) { check(mode, 'fallback checks completed', false, error.message); }
    finally { await context?.close(); }
  }
} catch (error) {
  check('setup', 'checker ready', false, `${error.message}\nRequires playwright, @axe-core/playwright and Playwright Chromium.`);
  const reason = error.message.match(/error while loading shared libraries:[^\n]+/)?.[0] ?? error.message.split('\n')[0];
  console.error(`Checker setup failed: ${reason}\nSetup: node setup/html-pages.mjs (from ${repoRoot}). Diagnose: npm --prefix setup run doctor. Full details are in report.json.`);
  if (/shared libraries|missing dependencies/i.test(error.message)) console.error('Linux system libraries are missing. Use node setup/html-pages.mjs --with-system-deps through your environment’s normal permission process.');
} finally {
  try { await browser?.close(); }
  catch (error) { check('runtime', 'browser closed', false, error.message); }
  check('runtime', 'no browser errors or blocked/failed requests', report.events.length === 0, report.events.length);
  report.passed = report.checks.every(item => item.passed);
  report.finishedAt = new Date().toISOString();
  try {
    await mkdir(output, { recursive: true });
    await writeFile(path.join(output, 'report.json'), `${JSON.stringify(report, null, 2)}\n`);
    console.log(`${report.passed ? 'PASS' : 'FAIL'}: ${report.checks.filter(c => !c.passed).length} failed checks; ${path.join(output, 'report.json')}`);
  } catch (error) {
    console.error(`Cannot write report: ${error.message}`);
    report.passed = false;
  }
  process.exitCode = report.passed ? 0 : 1;
}
