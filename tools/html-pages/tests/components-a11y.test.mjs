import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdir, readFile } from 'node:fs/promises';
import path from 'node:path';
import { chromium } from '../browser.mjs';
import { openPage, repoRoot, sample, sizes, read, chooseAll, count, eventually } from './component-helpers.mjs';

const controls = 'button,input,select,textarea,summary,[tabindex="0"],[role="button"],[role="slider"],[role="radio"],[role="tab"]';
const componentPrefix = /\[data-(?:predict|prob|formula|step)|\.prob-bar\b/;
const namedColors = new Set(('aliceblue antiquewhite aqua aquamarine azure beige bisque black blanchedalmond blue blueviolet brown burlywood cadetblue chartreuse chocolate coral cornflowerblue cornsilk crimson cyan darkblue darkcyan darkgoldenrod darkgray darkgrey darkgreen darkkhaki darkmagenta darkolivegreen darkorange darkorchid darkred darksalmon darkseagreen darkslateblue darkslategray darkslategrey darkturquoise darkviolet deeppink deepskyblue dimgray dimgrey dodgerblue firebrick floralwhite forestgreen fuchsia gainsboro ghostwhite gold goldenrod gray grey green greenyellow honeydew hotpink indianred indigo ivory khaki lavender lavenderblush lawngreen lemonchiffon lightblue lightcoral lightcyan lightgoldenrodyellow lightgray lightgrey lightgreen lightpink lightsalmon lightseagreen lightskyblue lightslategray lightslategrey lightsteelblue lightyellow lime limegreen linen magenta maroon mediumaquamarine mediumblue mediumorchid mediumpurple mediumseagreen mediumslateblue mediumspringgreen mediumturquoise mediumvioletred midnightblue mintcream mistyrose moccasin navajowhite navy oldlace olive olivedrab orange orangered orchid palegoldenrod palegreen paleturquoise palevioletred papayawhip peachpuff peru pink plum powderblue purple rebeccapurple red rosybrown royalblue saddlebrown salmon sandybrown seagreen seashell sienna silver skyblue slateblue slategray slategrey snow springgreen steelblue tan teal thistle tomato turquoise violet wheat white whitesmoke yellow yellowgreen').split(' '));

function noColorLiterals(source, label, kind = 'css') {
  const clean = source.replace(/\/\*[\s\S]*?\*\//g, '');
  assert.doesNotMatch(clean, /#[\da-f]{3,8}\b/i, `${label}: hex color`);
  assert.doesNotMatch(clean, /\b(?:rgba?|hsla?|hwb|oklch|oklab|lch|lab|color)\s*\(/i, `${label}: color function`);
  // CSS names count as literals in declaration values, not in selectors, --token names,
  // or var(--red). For JS, inspect string literals rather than variable identifiers.
  const values = kind === 'js'
    ? [...clean.matchAll(/(['"`])((?:\\.|(?!\1)[\s\S])*?)\1/g)].map(m => m[2])
    : [...clean.matchAll(/(?:^|[;{])\s*[-\w]+\s*:\s*([^;}]+)/g)].map(m => m[1]);
  for (let value of values) {
    value = value.replace(/var\(\s*--[\w-]+\s*\)/g, '').replace(/--[\w-]+/g, '');
    if (kind === 'js' && !/^[a-z]+$/i.test(value.trim()) && !/(?:color|fill|stroke|background|border)\s*:/i.test(value)) continue;
    for (const word of value.match(/\b[a-z]+\b/gi) || []) assert.ok(!namedColors.has(word.toLowerCase()), `${label}: literal color ${word}`);
  }
}

function cssRules(source) {
  const clean = source.replace(/\/\*[\s\S]*?\*\//g, match => ' '.repeat(match.length));
  return [...clean.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map(m => ({ selector: m[1], body: m[2], offset: m.index }));
}

test('A3: shared and sample component styles use tokens, with no inline color writes', async t => {
  const theme = await read('tools/html-pages/assets/theme.css');
  const script = await read('tools/html-pages/assets/page.js');
  const html = await readFile(sample, 'utf8');
  const begin = '/* components:begin */', end = '/* components:end */';
  assert.equal(theme.split(begin).length, 2, 'one marked components block');
  assert.equal(theme.split(end).length, 2);
  const start = theme.indexOf(begin) + begin.length, finish = theme.indexOf(end);
  assert.ok(finish > start);
  const block = theme.slice(start, finish);
  noColorLiterals(block, 'components CSS');
  noColorLiterals(script, 'shared JS', 'js');
  assert.doesNotMatch(block, /\b(?:animation|transition)(?:-[\w-]+)?\s*:/i, 'components add no motion');
  assert.match(block, /\.visually-hidden\b/);
  assert.doesNotMatch(script, /(?:setAttribute(?:NS)?\s*\(\s*(?:[^,]+,\s*)?['"](?:fill|stroke|style)['"]|\.style\s*(?:\.\s*(?:color|fill|stroke|cssText)|\[\s*['"](?:color|fill|stroke|cssText)['"]))/i, 'no inline fill/stroke/color writes');
  assert.doesNotMatch(script, /\.style\.setProperty\s*\(\s*['"](?:color|fill|stroke)['"]/i);
  for (const rule of cssRules(theme)) {
    const match = componentPrefix.exec(rule.selector);
    if (!match) continue;
    const pos = rule.offset + match.index;
    assert.ok(pos >= start && pos < finish, `component selector outside block: ${rule.selector.trim()}`);
    for (const declaration of rule.body.matchAll(/\bfont(?:-family)?\s*:\s*([^;}]+)/g)) assert.match(declaration[1], /var\(--[\w-]+\)/);
  }
  const local = html.replace(/<!-- shared-style:begin -->[\s\S]*?<!-- shared-style:end -->/g, '')
    .replace(/<!-- shared-script:begin -->[\s\S]*?<!-- shared-script:end -->/g, '');
  for (const match of local.matchAll(/<style\b[^>]*>([\s\S]*?)<\/style>/gi)) {
    noColorLiterals(match[1], 'sample CSS');
    for (const rule of cssRules(match[1])) if (componentPrefix.test(rule.selector)) {
      for (const declaration of rule.body.matchAll(/\bfont(?:-family)?\s*:\s*([^;}]+)/g)) assert.match(declaration[1], /var\(--[\w-]+\)/);
    }
  }
  for (const match of local.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)) noColorLiterals(match[1], 'sample JS', 'js');
  // Inspect authored SVG before enhancement can replace any of its attributes.
  const page = await openPage(t, chromium, { javaScriptEnabled: false });
  const attributes = await page.locator('svg, svg *').evaluateAll(els => els.flatMap(el =>
    ['fill', 'stroke', 'style'].filter(name => el.hasAttribute(name)).map(name => [name, el.getAttribute(name)])));
  for (const [name, value] of attributes) noColorLiterals(`x { ${name === 'style' ? value : `${name}: ${value}`}; }`, `SVG ${name}`);
});

async function targetsAndFocus(page, state) {
  const targetSizes = await page.locator(controls).evaluateAll(els => els.filter(el => {
    const style = getComputedStyle(el), rect = el.getBoundingClientRect();
    return !el.matches(':disabled') && el.getAttribute('aria-disabled') !== 'true' &&
      style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
  }).map(el => ({ html: el.outerHTML.slice(0, 240), width: el.getBoundingClientRect().width, height: el.getBoundingClientRect().height })));
  assert.ok(targetSizes.length > 0, `${state}: nonempty set of controls`);
  for (const target of targetSizes) {
    assert.ok(target.width >= 44 && target.height >= 44, `${state}: target below 44×44: ${JSON.stringify(target)}`);
  }
  // Move the sequential navigation origin to the body, then use real Tab presses.
  await page.evaluate(() => {
    const prior = document.body.getAttribute('tabindex');
    document.body.tabIndex = -1;
    document.body.focus();
    if (prior === null) document.body.removeAttribute('tabindex'); else document.body.setAttribute('tabindex', prior);
  });
  const seen = new Set();
  let checked = 0, completed = false;
  const limit = await page.locator('*').count() + 20;
  for (let i = 0; i < limit; i++) {
    await page.keyboard.press('Tab');
    const active = await page.evaluate(selector => {
      const el = document.activeElement;
      if (!el || el === document.body || el === document.documentElement) return { body: true };
      const id = Array.from(document.querySelectorAll('*')).indexOf(el);
      if (!el.matches(selector)) return { id, control: false };
      const s = getComputedStyle(el), r = el.getBoundingClientRect();
      const outset = Math.max(0, parseFloat(s.outlineWidth) + parseFloat(s.outlineOffset));
      const box = { left: r.left - outset, top: r.top - outset, right: r.right + outset, bottom: r.bottom + outset };
      const clipping = [];
      for (let parent = el.parentElement; parent; parent = parent.parentElement) {
        const ps = getComputedStyle(parent), p = parent.getBoundingClientRect();
        const left = p.left + parent.clientLeft, top = p.top + parent.clientTop;
        if ((ps.overflowX !== 'visible' && (box.left < left - 0.5 || box.right > left + parent.clientWidth + 0.5)) ||
            (ps.overflowY !== 'visible' && (box.top < top - 0.5 || box.bottom > top + parent.clientHeight + 0.5))) clipping.push(parent.tagName + '.' + parent.className);
      }
      const probe = document.createElement('span'); probe.style.color = 'var(--accent)'; document.body.append(probe);
      const accent = getComputedStyle(probe).color; probe.remove();
      return { id, control: true, html: el.outerHTML.slice(0, 200), visible: el.matches(':focus-visible'),
        style: s.outlineStyle, width: parseFloat(s.outlineWidth), color: s.outlineColor, accent, box, clipping,
        inViewport: box.left >= -0.5 && box.top >= -0.5 && box.right <= innerWidth + 0.5 && box.bottom <= innerHeight + 0.5 };
    }, controls);
    if (active.body) { completed = true; break; }
    if (seen.has(active.id)) { completed = true; break; }
    seen.add(active.id);
    if (!active.control) continue; // Prose links retain their native tab stop but are not targets.
    checked++;
    assert.equal(active.visible, true, `${state}: focus-visible ${active.html}`);
    assert.ok(!['none', 'hidden'].includes(active.style) && active.width >= 2, `${state}: outline ${JSON.stringify(active)}`);
    assert.equal(active.color, active.accent, `${state}: outline follows --accent`);
    assert.deepEqual(active.clipping, [], `${state}: ancestor clips outline ${active.html}`);
    assert.equal(active.inViewport, true, `${state}: outline outside viewport ${JSON.stringify(active)}`);
  }
  assert.ok(completed && checked > 0, `${state}: full nonempty Tab traversal must complete`);
}

for (const viewport of sizes) {
  test(`A3: ${viewport.width}×${viewport.height} strict targets and focus in every interaction state`, { timeout: 180000 }, async t => {
    const page = await openPage(t, chromium, { viewport });
    const out = path.join(repoRoot, 'artifacts/html-pages/components-states');
    await mkdir(out, { recursive: true });
    async function inspect(state) {
      await targetsAndFocus(page, state);
      await page.screenshot({ path: path.join(out, `${viewport.width}-${state}.png`), fullPage: true });
    }
    const roots = page.locator('[data-predict]');
    await count(roots, 2);
    await inspect('initial');
    for (const root of await roots.all()) await chooseAll(root);
    await inspect('chosen');
    for (const root of await roots.all()) await root.locator('[data-predict-lock]').click();
    await inspect('locked');
    for (const root of await roots.all()) await root.locator('[data-predict-reveal]').click();
    await inspect('revealed');
    for (const root of await roots.all()) await root.locator('[data-predict-reset]').click();
    await inspect('reset');
    const stepper = page.locator('[data-stepper]');
    await count(stepper.locator('[data-step]'), 4);
    for (let index = 0; index < 4; index++) {
      if (index > 0) await stepper.locator('[data-step-next]').click();
      assert.equal(await stepper.getAttribute('data-step-current'), String(index));
      await inspect(`step-${index + 1}`);
    }
    const slider = page.locator('[data-formula=temperature] [data-formula-input]');
    for (const [key, state] of [['Home', 'minimum'], ['End', 'maximum']]) {
      await slider.press(key);
      await inspect(`slider-${state}`);
    }
    const noJS = await openPage(t, chromium, { viewport, javaScriptEnabled: false });
    await targetsAndFocus(noJS, 'no-js');
    await noJS.screenshot({ path: path.join(out, `${viewport.width}-no-js.png`), fullPage: true });
  });
}

test('A3: live token overrides recolor bars, track, focus, radio and textual state', async t => {
  const page = await openPage(t, chromium);
  const sentinels = { accent: 'rgb(19, 137, 211)', muted: 'rgb(181, 127, 73)', faint: 'rgb(42, 52, 62)', ink: 'rgb(219, 227, 239)' };
  await page.evaluate(values => {
    for (const [name, value] of Object.entries(values)) document.documentElement.style.setProperty(`--${name}`, value);
  }, sentinels);
  for (const [selector, property, name] of [
    ['[data-prob-row][data-highlight] rect.f-accent', 'fill', 'accent'],
    ['[data-prob-row]:not([data-highlight]) rect.f-muted', 'fill', 'muted'],
    ['[data-prob-row] rect.f-faint', 'fill', 'faint'],
    ['[data-predict] input[type=radio]', 'accentColor', 'accent'],
    ['[data-step-status]', 'color', 'ink'],
  ]) {
    const elements = page.locator(selector);
    assert.ok(await elements.count(), selector);
    for (const element of await elements.all()) assert.equal(await element.evaluate((el, prop) => getComputedStyle(el)[prop], property), sentinels[name], selector);
  }
  for (const correct of [false, true]) {
    for (const root of await page.locator('[data-predict]').all()) {
      await root.locator('[data-predict-reset]').click();
      await chooseAll(root, correct);
      await root.locator('[data-predict-lock]').click();
      await root.locator('[data-predict-reveal]').click();
      for (const result of await root.locator('[data-predict-result]').all()) {
        assert.ok((await result.textContent()).trim());
        assert.equal(await result.evaluate(el => getComputedStyle(el).color), sentinels.ink);
      }
    }
  }
  const slider = page.locator('[data-formula-input]');
  await slider.focus();
  await slider.press('ArrowRight');
  await eventually(async () => assert.equal(await slider.evaluate(el => getComputedStyle(el).outlineColor), sentinels.accent));
  assert.equal(await slider.evaluate(el => el.matches(':focus-visible')), true);
});
