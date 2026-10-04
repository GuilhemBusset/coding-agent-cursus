import test from 'node:test';
import assert from 'node:assert/strict';
import { chromium } from '../browser.mjs';
import { openPage, fixture, count, textOf, eventually } from './component-helpers.mjs';

async function rendered(row, value) {
  await eventually(async () => {
    await count(row.locator('svg.prob-bar[aria-hidden=true]'), 1);
    assert.equal(await textOf(row.locator('[data-prob-value]')), `${(value * 100).toFixed(1)}%`);
    const geometry = await row.evaluate(el => {
      const svg = el.querySelector('svg.prob-bar');
      const track = svg.querySelector('rect.f-faint');
      const bar = svg.querySelector('rect.f-accent, rect.f-muted');
      if (!track || !bar) return null;
      return { track: track.getBoundingClientRect().width, bar: bar.getBoundingClientRect().width,
        height: bar.getBoundingClientRect().height, highlighted: bar.classList.contains('f-accent') };
    });
    assert.ok(geometry && geometry.track > 0 && geometry.height > 0);
    assert.ok(Math.abs(geometry.bar / geometry.track - value) < 0.002, JSON.stringify(geometry));
    assert.equal(geometry.highlighted, await row.evaluate(el => el.hasAttribute('data-highlight')));
  }, 'row rendering');
}

async function highlight(row, expected) {
  await eventually(async () => {
    const label = row.locator('[data-prob-label]');
    const weight = await label.evaluate(el => Number(getComputedStyle(el).fontWeight));
    assert.equal(weight >= 700, expected, 'highlight alone uses a bold label');
    await count(label.locator('[data-prob-flag]'), expected ? 1 : 0);
    if (expected) {
      const flag = label.locator('[data-prob-flag]');
      assert.equal(await textOf(flag), '(highlighted)');
      assert.match(await label.ariaSnapshot(), /\(highlighted\)/);
      const hidden = await flag.evaluate(el => {
        const s = getComputedStyle(el), r = el.getBoundingClientRect();
        return s.display !== 'none' && s.visibility !== 'hidden' &&
          (r.width <= 1 && r.height <= 1) &&
          (s.clipPath !== 'none' || s.clip !== 'auto') && s.position === 'absolute';
      });
      assert.equal(hidden, true, 'highlight flag must be visually hidden, not hidden from AT');
    } else assert.doesNotMatch(await label.ariaSnapshot(), /\(highlighted\)/);
  });
}

test('D2: sample chart exposes labels, values, proportional SVG bars and non-color highlight', async t => {
  const page = await openPage(t, chromium);
  const chart = page.locator('ol[data-prob-chart]');
  await count(chart, 1);
  assert.ok(await chart.locator('..').locator('figcaption').count(), 'chart is in a captioned figure');
  assert.equal(await chart.locator('..').evaluate(el => el.tagName), 'FIGURE');
  const rows = chart.locator('li[data-prob-row]');
  assert.ok(await rows.count() >= 2);
  await count(chart.locator('[data-prob-row][data-highlight]'), 1);
  for (const row of await rows.all()) {
    assert.ok(await textOf(row.locator('[data-prob-label]')));
    await rendered(row, Number(await row.getAttribute('data-value')));
    await highlight(row, await row.evaluate(el => el.hasAttribute('data-highlight')));
  }
});

test('D2: mutations cover boundaries, fractions, moving highlights and row-local invalidation', { timeout: 60000 }, async t => {
  const chart = id => `<figure><figcaption>${id}</figcaption><ol id="${id}" data-prob-chart>
    <li data-prob-row data-value="0.375" data-highlight><span data-prob-label>Alpha</span> <span data-prob-value>37.5%</span></li>
    <li data-prob-row data-value="0.625"><span data-prob-label>Beta</span> <span data-prob-value>62.5%</span></li></ol></figure>`;
  const page = await openPage(t, chromium, { file: await fixture(t, chart('a') + chart('b')) });
  const first = page.locator('#a [data-prob-row]').first();
  const second = page.locator('#a [data-prob-row]').nth(1);
  for (const value of [0, 1, 0.173, 0.806]) {
    await first.evaluate((el, v) => el.setAttribute('data-value', v), String(value));
    await rendered(first, value);
    await rendered(second, 0.625);
  }
  await first.evaluate(el => el.removeAttribute('data-highlight'));
  await second.evaluate(el => el.setAttribute('data-highlight', ''));
  await highlight(first, false);
  await highlight(second, true);
  await rendered(first, 0.806);
  await rendered(second, 0.625);
  for (const invalid of ['NaN', 'Infinity', '-0.01', '1.01', 'banana']) {
    await first.evaluate((el, value) => el.setAttribute('data-value', value), invalid);
    // This deliberately waits on just the invalid row. Other rows must retain their bars.
    await eventually(async () => {
      await count(first.locator('svg.prob-bar'), 0);
      assert.equal(await textOf(first.locator('[data-prob-value]')), 'n/a');
    });
    await count(page.locator('svg.prob-bar'), 3);
    await rendered(second, 0.625);
    await rendered(page.locator('#b [data-prob-row]').first(), 0.375);
    await first.evaluate(el => el.setAttribute('data-value', '0.243'));
    await rendered(first, 0.243);
  }
  const colors = await page.locator('#a').evaluate(el => {
    const resolve = token => { const probe = document.createElement('span'); probe.style.color = `var(${token})`; el.append(probe); const c = getComputedStyle(probe).color; probe.remove(); return c; };
    return ['accent', 'muted', 'faint'].map(name => ({ name, expected: resolve(`--${name}`),
      actual: Array.from(el.querySelectorAll(`rect.f-${name}`)).map(rect => getComputedStyle(rect).fill) }));
  });
  for (const { name, expected, actual } of colors) { assert.ok(actual.length, name); for (const fill of actual) assert.equal(fill, expected); }
});

test('D2: no-JS chart retains authored labels and numeric values', async t => {
  const page = await openPage(t, chromium, { javaScriptEnabled: false });
  const rows = page.locator('ol[data-prob-chart] [data-prob-row]');
  assert.ok(await rows.count() >= 2);
  for (const row of await rows.all()) {
    assert.equal(await row.locator('[data-prob-label]').isVisible(), true);
    assert.equal(await row.locator('[data-prob-value]').isVisible(), true);
    assert.equal(await textOf(row.locator('[data-prob-value]')), `${(Number(await row.getAttribute('data-value')) * 100).toFixed(1)}%`);
  }
});
