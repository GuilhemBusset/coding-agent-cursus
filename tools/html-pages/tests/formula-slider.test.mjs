import test from 'node:test';
import assert from 'node:assert/strict';
import { chromium } from '../browser.mjs';
import { openPage, fixture, count, enabled, textOf, eventually } from './component-helpers.mjs';

async function softmaxOracle(page) {
  const root = page.locator('[data-formula="temperature"]');
  const slider = root.locator('input[type=range][data-formula-input]');
  const temperature = Number(await slider.inputValue());
  assert.ok(temperature > 0);
  const rows = await page.locator('[data-prob-chart] [data-prob-row]').evaluateAll(elements => elements.map(el => ({
    logit: Number(el.getAttribute('data-logit')), hasLogit: el.hasAttribute('data-logit'),
    value: Number(el.getAttribute('data-value')), highlight: el.hasAttribute('data-highlight'),
    text: el.querySelector('[data-prob-value]').textContent.trim(),
  })));
  assert.ok(rows.length >= 2);
  assert.ok(rows.every(row => row.hasLogit && Number.isFinite(row.logit)));
  const max = Math.max(...rows.map(row => row.logit / temperature));
  const weights = rows.map(row => Math.exp(row.logit / temperature - max));
  const total = weights.reduce((a, b) => a + b, 0);
  const expected = weights.map(value => value / total);
  for (let i = 0; i < rows.length; i++) {
    assert.ok(Math.abs(rows[i].value - expected[i]) <= 1e-3, `row ${i}: ${rows[i].value} versus independent softmax ${expected[i]}`);
    assert.equal(rows[i].text, `${(expected[i] * 100).toFixed(1)}%`);
  }
  const highlighted = rows.findIndex(row => row.highlight);
  assert.ok(highlighted >= 0);
  const output = await textOf(root.locator('output[data-formula-output]'));
  assert.ok(output.includes(`T = ${temperature.toFixed(1)}`), output);
  assert.ok(output.includes(`${(expected[highlighted] * 100).toFixed(1)}%`), output);
  assert.equal(await slider.getAttribute('aria-valuetext'), output);
  return output;
}

test('D3: sample temperature formula agrees with independent softmax under real pointer and keyboard input', { timeout: 45000 }, async t => {
  const page = await openPage(t, chromium);
  const root = page.locator('[data-formula="temperature"]');
  await count(root, 1);
  const slider = root.locator('input[type=range][data-formula-input]');
  await enabled(slider);
  assert.ok(await slider.evaluate(el => Array.from(el.labels || []).some(label => label.textContent.trim())), 'slider needs a native label');
  const defaultValue = await slider.evaluate(el => el.defaultValue);
  const readings = [await softmaxOracle(page)];
  await slider.focus();
  await slider.press('Home');
  assert.equal(Number(await slider.inputValue()), Number(await slider.getAttribute('min')));
  readings.push(await eventually(() => softmaxOracle(page)));
  await slider.press('End');
  assert.equal(Number(await slider.inputValue()), Number(await slider.getAttribute('max')));
  readings.push(await eventually(() => softmaxOracle(page)));
  await slider.press('Home');
  await slider.press('ArrowRight');
  const min = Number(await slider.getAttribute('min')), step = Number(await slider.getAttribute('step'));
  assert.ok(Math.abs(Number(await slider.inputValue()) - min - step) < 1e-8);
  readings.push(await eventually(() => softmaxOracle(page)));
  await slider.scrollIntoViewIfNeeded();
  const box = await slider.boundingBox();
  const before = await slider.inputValue();
  await page.mouse.click(box.x + box.width * 0.64, box.y + box.height / 2);
  assert.notEqual(await slider.inputValue(), before, 'track click changes value');
  readings.push(await eventually(() => softmaxOracle(page)));
  assert.ok(new Set(readings).size >= 3, 'live readout must change');
  await root.locator('button[data-formula-reset]').click();
  assert.equal(await slider.inputValue(), defaultValue);
  assert.equal(await eventually(() => softmaxOracle(page)), readings[0]);
});

test('D3: reusable registry supports fractional values and independent/missing formulas', async t => {
  const component = (name, value, output) => `<section data-formula="${name}">
    <label for="${name}">${name} x</label><input id="${name}" type="range" data-formula-input min="-2" max="3" step="0.25" value="${value}" disabled>
    <output data-formula-output for="${name}">${output}</output><button data-formula-reset disabled>Reset</button></section>`;
  const file = await fixture(t, component('linear', 0.5, 'initial linear') + component('square', 1.25, 'initial square') +
    component('unregistered', 1, 'Static fallback'), `window.CursusFormulas = window.CursusFormulas || {};
    window.CursusFormulas.linear = function (x, root) { if (root.getAttribute('data-formula') !== 'linear') throw new Error('wrong root'); return 'y = 2 × ' + x + ' + 1 = ' + (2*x+1); };
    window.CursusFormulas.square = function (x) { return 'q = ' + x + '² = ' + (x*x); };`);
  const page = await openPage(t, chromium, { file });
  const linear = page.locator('[data-formula=linear]'), square = page.locator('[data-formula=square]');
  const input = linear.locator('[data-formula-input]');
  for (const value of [0.5, -1.75, 2.25, 0, 3]) {
    await enabled(input);
    await input.fill(String(value));
    const expected = `y = 2 × ${value} + 1 = ${2 * value + 1}`;
    assert.equal(await textOf(linear.locator('[data-formula-output]')), expected);
    assert.equal(await input.getAttribute('aria-valuetext'), expected);
    assert.equal(await textOf(square.locator('[data-formula-output]')), 'q = 1.25² = 1.5625');
  }
  await square.locator('[data-formula-input]').fill('-0.75');
  assert.equal(await textOf(square.locator('[data-formula-output]')), 'q = -0.75² = 0.5625');
  await linear.locator('[data-formula-reset]').click();
  assert.equal(await input.inputValue(), '0.5');
  assert.equal(await textOf(linear.locator('[data-formula-output]')), 'y = 2 × 0.5 + 1 = 2');
  assert.equal(await textOf(square.locator('[data-formula-output]')), 'q = -0.75² = 0.5625');
  const missing = page.locator('[data-formula=unregistered]');
  await enabled(missing.locator('[data-formula-input]'), false);
  await enabled(missing.locator('[data-formula-reset]'), false);
  assert.equal(await textOf(missing.locator('[data-formula-output]')), 'Static fallback');
});

test('D3: sample static defaults are already accurate without JavaScript', async t => {
  const page = await openPage(t, chromium, { javaScriptEnabled: false });
  const root = page.locator('[data-formula=temperature]');
  await enabled(root.locator('[data-formula-input]'), false);
  await enabled(root.locator('[data-formula-reset]'), false);
  // The authored fallback is not required to carry aria-valuetext, but its math is required.
  const value = Number(await root.locator('[data-formula-input]').inputValue());
  const rows = await page.locator('[data-prob-chart] [data-prob-row]').evaluateAll(els => els.map(el => ({
    logit: Number(el.dataset.logit), value: Number(el.dataset.value), text: el.querySelector('[data-prob-value]').textContent.trim(), highlighted: el.hasAttribute('data-highlight'),
  })));
  assert.ok(rows.length >= 2 && rows.every(row => Number.isFinite(row.logit)));
  const max = Math.max(...rows.map(row => row.logit / value));
  const weights = rows.map(row => Math.exp(row.logit / value - max)), sum = weights.reduce((a, b) => a + b, 0);
  for (let i = 0; i < rows.length; i++) {
    const probability = weights[i] / sum;
    assert.ok(Math.abs(rows[i].value - probability) <= 1e-3);
    assert.equal(rows[i].text, `${(probability * 100).toFixed(1)}%`);
    if (rows[i].highlighted) assert.ok((await textOf(root.locator('[data-formula-output]'))).includes(`${(probability * 100).toFixed(1)}%`));
  }
  assert.ok((await textOf(root.locator('[data-formula-output]'))).includes(`T = ${value.toFixed(1)}`));
});
