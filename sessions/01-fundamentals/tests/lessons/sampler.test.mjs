import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from '../../../../tools/html-pages/browser.mjs';
import { openPage, repoRoot, eventually } from '../../../../tools/html-pages/tests/component-helpers.mjs';

// Act I deck: what would break in front of the room. The tokens, IDs, probabilities and quotes on the
// slides are the recorded fixtures', and a lab opened from its slide comes back to that slide.
// check-page covers the rest of every deck: layout, accessibility, navigation, links, no-JS and print.
const cursus = path.join(repoRoot, 'sessions/01-fundamentals/cursus');
const file = path.join(cursus, '01-sampler.html');
const piece = text => text.replace(/ /g, '␣');
const quoteNorm = value => value.replace(/\s+/g, ' ').trim();
const json = async relative => JSON.parse(await readFile(path.join(cursus, relative), 'utf8'));

test('Act I deck', async t => {
  const page = await openPage(t, chromium, { file });
  const topic = id => page.locator(`section[data-slide]#${id}`);
  const onFace = id => topic(id).evaluate(el => {
    const copy = el.cloneNode(true);
    copy.querySelectorAll('details.speaker-notes').forEach(node => node.remove());
    return copy.textContent;
  });
  const chips = id => topic(id).locator('[data-token-id]').evaluateAll(els => els.map(el => ({
    id: Number(el.dataset.tokenId), text: el.querySelector('code').textContent, shown: el.querySelector('.id').textContent })));
  const fixture = await json('fixtures/next_token.json');
  const item = fixture.prompts.find(prompt => prompt.id === 'factual-everyone-knows');
  assert.ok(item, 'the running example is the factual-everyone-knows prompt');
  const chip = token => ({ id: token.id, text: piece(token.text), shown: String(token.id) });

  await t.test('the token IDs on the tokenize, embed, sample and append slides are the recorded ones', async () => {
    const prompt = item.prompt_tokens.map(chip);
    assert.deepEqual(await chips('tokenize'), prompt);
    assert.deepEqual(await topic('embed').locator('.matrix .id').evaluateAll(els => els.map(el => Number(el.textContent))),
      item.prompt_tokens.map(token => token.id), 'one embedding row per recorded ID');
    assert.equal(item.top[0].text, item.expect, 'the drawn token is the most likely one');
    assert.deepEqual(await chips('sample'), [chip(item.top[0])]);
    assert.deepEqual(await chips('append'), [...prompt, chip(item.top[0])]);
    const strawberry = fixture.prompts.find(prompt => prompt.prompt === ' strawberry');
    assert.equal(strawberry?.prompt_tokens.length, 1, 'the fixture holds the leading-space strawberry prompt');
    assert.match(await onFace('strawberry'), new RegExp(`\\b${strawberry.prompt_tokens[0].id}\\b`));
  });

  await t.test('the logits slide shows the recorded top-5 probabilities', async () => {
    const rows = await topic('logits').locator('[data-prob-row]').evaluateAll(els => els.map(el => ({
      label: el.querySelector('[data-prob-label] code').textContent, value: Number(el.dataset.value) })));
    assert.equal(rows.length, 5);
    rows.forEach((row, i) => {
      const top = item.top[i];
      assert.equal(row.label, piece(top.text));
      assert.ok(Math.abs(row.value - Math.exp(top.logit - item.logsumexp)) < 5e-4, `${top.text}: recorded probability`);
    });
  });

  await t.test('the base and assistant quotes are verbatim from the base_vs_instruct fixture', async () => {
    const recorded = (await json('fixtures/base_vs_instruct.json')).items.find(entry => entry.id === 'factual');
    const quotes = await topic('weights').locator('[data-fixture-id="factual"] blockquote').evaluateAll(els =>
      els.map(el => [...el.querySelectorAll('p')].map(p => p.textContent).join(' ')));
    const [question, ...answers] = quotes.map(quoteNorm);
    assert.equal(question, quoteNorm(recorded.prompt), 'the shared question is the recorded prompt');
    const sources = { base: quoteNorm(recorded.base.text), instruct: quoteNorm(recorded.instruct.text) };
    for (const answer of answers) {
      assert.ok(Object.values(sources).some(source => source.includes(answer)), `a contiguous recorded excerpt: ${answer}`);
    }
    for (const [model, source] of Object.entries(sources)) {
      assert.ok(answers.some(answer => source.includes(answer)), `an excerpt of the ${model} model`);
    }
  });

  // Last: it navigates away from the deck.
  await t.test('a lab opened from its slide comes back to that slide with Back', async () => {
    await page.evaluate(() => { location.hash = 'tokenize'; });
    await eventually(async () => assert.equal(await topic('tokenize').isVisible(), true));
    const lab = path.join(cursus, 'labs/tokenizer.html');
    await Promise.all([
      page.waitForURL(url => url.protocol === 'file:' && fileURLToPath(url) === lab),
      topic('tokenize').locator(':scope > :not(details) a[href="labs/tokenizer.html"]').click(),
    ]);
    await page.goBack();
    await eventually(async () => {
      assert.equal(decodeURIComponent(new URL(page.url()).hash.slice(1)), 'tokenize');
      assert.deepEqual(await page.locator('section[data-slide]').evaluateAll(els => els.filter(el => el.checkVisibility()).map(el => el.id)), ['tokenize']);
    }, 'back on #tokenize');
  });
});
