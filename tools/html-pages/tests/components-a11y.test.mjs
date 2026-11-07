import test from 'node:test';
import assert from 'node:assert/strict';
import { chromium } from '../browser.mjs';
import { openPage, sizes, chooseAll, count } from './component-helpers.mjs';

const controls = 'button,input,select,textarea,summary,[tabindex="0"],[role="button"],[role="slider"],[role="radio"],[role="tab"]';

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
      return { id, control: true, html: el.outerHTML.slice(0, 200), visible: el.matches(':focus-visible'),
        style: s.outlineStyle, width: parseFloat(s.outlineWidth), box, clipping,
        inViewport: box.left >= -0.5 && box.top >= -0.5 && box.right <= innerWidth + 0.5 && box.bottom <= innerHeight + 0.5 };
    }, controls);
    if (active.body) { completed = true; break; }
    if (seen.has(active.id)) { completed = true; break; }
    seen.add(active.id);
    if (!active.control) continue; // Prose links retain their native tab stop but are not targets.
    checked++;
    assert.equal(active.visible, true, `${state}: focus-visible ${active.html}`);
    assert.ok(!['none', 'hidden'].includes(active.style) && active.width >= 2, `${state}: outline ${JSON.stringify(active)}`);
    assert.deepEqual(active.clipping, [], `${state}: ancestor clips outline ${active.html}`);
    assert.equal(active.inViewport, true, `${state}: outline outside viewport ${JSON.stringify(active)}`);
  }
  assert.ok(completed && checked > 0, `${state}: full nonempty Tab traversal must complete`);
}

// One viewport, the phone: targets matter most there and outlines have the least room; focus
// styles do not change with the width. One state per set of enabled controls. check-page runs axe
// on every teaching page.
test('A3: every enabled control is a 44×44 target with a visible, unclipped focus outline', { timeout: 60000 }, async t => {
  const viewport = sizes[2];
  const page = await openPage(t, chromium, { viewport });
  const roots = page.locator('[data-predict]');
  await count(roots, 2);
  await targetsAndFocus(page, 'initial');
  for (const root of await roots.all()) await chooseAll(root);
  await targetsAndFocus(page, 'chosen');
  for (const root of await roots.all()) await root.locator('[data-predict-lock]').click();
  await targetsAndFocus(page, 'locked');
  for (const root of await roots.all()) await root.locator('[data-predict-reveal]').click();
  await targetsAndFocus(page, 'revealed');
  const stepper = page.locator('[data-stepper]');
  await stepper.locator('[data-step-next]').click();
  assert.equal(await stepper.getAttribute('data-step-current'), '1');
  await targetsAndFocus(page, 'step-2');
  const slider = page.locator('[data-formula=temperature] [data-formula-input]');
  for (const [key, state] of [['Home', 'minimum'], ['End', 'maximum']]) {
    await slider.press(key);
    await targetsAndFocus(page, `slider-${state}`);
  }
  await targetsAndFocus(await openPage(t, chromium, { viewport, javaScriptEnabled: false }), 'no-js');
});
