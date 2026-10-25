import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import path from 'node:path';
import { chromium } from '../browser.mjs';
import { openPage, repoRoot, count, enabled, focused, textOf, eventually, assertCollected } from './component-helpers.mjs';

// Issue 26: public deck/component contracts, not page-specific JS internals.
// check-page supplies accessibility, print, offline assets and generic layout checks.
// Required PR evidence complements these floors: D1/D2 prose review, A1's complete
// claim/source/date table (including code and revealed answers), screenshot review,
// and the documented control-focus caveat for deck keys.
const decks = {
  opening: path.join(repoRoot, 'sessions/01-fundamentals/cursus/00-opening.html'),
  close: path.join(repoRoot, 'sessions/01-fundamentals/cursus/99-close.html'),
};
const viewports = [{ width: 1440, height: 900 }, { width: 1280, height: 720 }];
const artifacts = path.join(repoRoot, 'artifacts/html-pages/opening-close');
const normalize = value => value.normalize('NFKC').replace(/[‘’]/g, "'")
  .replace(/[−–]/g, '-').replace(/\s+/g, ' ').trim().toLowerCase();
const topic = (page, id) => page.locator(`section[data-slide][id^="${id}"]`);
const topicText = async (page, id) => normalize((await topic(page, id).allTextContents()).join(' '));
// The opening's slides, in order. Its launch (#cold-open) and return (#cold-open-result) share
// a prefix, so opening assertions select one slide by its exact id instead of topic().
const openingSlides = ['title', 'cold-open', 'cursus-arc', 'discovery', 'how-we-work', 'cold-open-result', 'discipline'];
const openingSlide = (page, id) => page.locator(`section[data-slide][id="${id}"]`);
// What the room reads: a slide's text, always without its speaker notes, optionally without
// other parts. Counting words joins text nodes with spaces, so a label and its value stay two words.
const onSlide = async (page, id, { joiner = '', without = [] } = {}) => normalize(await openingSlide(page, id).evaluate((el, { joiner, without }) => {
  const copy = el.cloneNode(true);
  copy.querySelectorAll(['details.notes', ...without].join(', ')).forEach(node => node.remove());
  const walker = document.createTreeWalker(copy, NodeFilter.SHOW_TEXT);
  const parts = [];
  while (walker.nextNode()) parts.push(walker.currentNode.data);
  return parts.join(joiner);
}, { joiner, without }));
const words = text => (text.match(/[\p{L}\p{N}]+(?:['.\-/][\p{L}\p{N}]+)*/gu) || []).length;
// Sparse slides, body words only: not the headline, the source line, the poll's buttons and
// status, or the title slide's byline. Eyebrows, labels and the revealed answer count.
// The densest slide, #cursus-arc, has 42.
const notBody = ['h2', '.cite', '.predict-actions', '[data-predict-status]', '.byline'];
const openingBodyCeiling = 45;

async function deckContract(page) {
  assert.equal(await page.locator('html').getAttribute('data-page-kind'), 'deck');
  assert.equal(await page.locator('html').getAttribute('data-design-system'), 'cursus');
  await count(page.locator('main[data-deck]'), 1);
  await count(page.locator('main[data-deck] nav[data-deck-nav]'), 1);
  await count(page.locator('script[src], script[type="module"]'), 0);
  const ids = await page.locator('main[data-deck] section[data-slide]').evaluateAll(els => els.map(el => el.id));
  assert.ok(ids.length > 1 && ids.every(Boolean), 'a deck has multiple named slides');
  assert.equal(new Set(ids).size, ids.length, 'slide ids are unique');
  await count(page.locator('[data-slide]'), ids.length);
  return ids;
}

async function codePath(slides, expected) {
  assert.ok((await slides.locator('code').allTextContents()).some(text => text.includes(expected)),
    `${expected} is shown as code`);
  for (const link of await slides.locator('a[href]').all()) {
    assert.ok(!(await link.getAttribute('href')).includes(expected) && !(await textOf(link)).includes(expected),
      `${expected} is a future-content slot, not a link`);
  }
}

// Run against authored, no-JS DOM: answers must be readable before enhancement.
async function predictContract(page) {
  const names = new Set();
  const roots = await page.locator('[data-predict]').all();
  assert.ok(roots.length > 0, 'at least one predict-and-reveal root');
  for (const root of roots) {
    await count(root.locator('[data-predict]'), 0);
    assert.ok(await root.evaluate(el => Boolean(el.closest('section[data-slide]'))));
    for (const action of ['lock', 'reveal', 'reset']) {
      const button = root.locator(`button[data-predict-${action}]`);
      await count(button, 1);
      await enabled(button, false);
    }
    await count(root.locator('[data-predict-status][role="status"]'), 1);
    const questions = await root.locator('fieldset[data-predict-question]').all();
    assert.ok(questions.length > 0);
    await count(root.locator('[data-predict-question]'), questions.length);
    for (const question of questions) {
      await count(question.locator('legend'), 1);
      assert.ok((await textOf(question.locator('legend'))).length > 0);
      const radios = await question.locator('input[type="radio"]').all();
      assert.ok(radios.length >= 2, 'every question offers a choice');
      const name = await radios[0].getAttribute('name');
      assert.ok(name && !names.has(name), 'each question has a nonempty name unique across the deck');
      names.add(name);
      for (const radio of radios) {
        assert.equal(await radio.getAttribute('name'), name);
        assert.ok(await radio.evaluate(el => [...el.labels].some(label => label.innerText.trim())),
          'every radio has a readable native label');
      }
      await count(question.locator('input[type="radio"][data-correct]'), 1);
      await count(question.locator('[data-predict-result]'), 1);
      assert.equal(await textOf(question.locator('[data-predict-result]')), '');
      const answer = question.locator('[data-predict-answer]');
      await count(answer, 1);
      assert.ok((await textOf(answer)).length > 10, 'authored answer explains the result');
      assert.equal(await answer.isVisible(), true, 'no-JS readers can see the answer');
    }
  }
}

test('D1: opening slides, presenter and goal, launch and return, cursus, format and discipline', async t => {
  const page = await openPage(t, chromium, { file: decks.opening, javaScriptEnabled: false });
  assert.deepEqual(await deckContract(page), openingSlides, 'the opening slides, in order');
  const title = await onSlide(page, 'title');
  for (const phrase of ['guilhem busset', 'sr sdm', 'amazon', 'transportation network design',
    'give you all the tools and knowledge to become an effective research or applied scientist']) {
    assert.ok(title.includes(phrase), `the title slide shows ${phrase}`);
  }
  const launch = await onSlide(page, 'cold-open');
  for (const pattern of [/highs/, /certificate/]) assert.match(launch, pattern);
  await codePath(openingSlide(page, 'cold-open'), 'cursus/demos/cold-open/');
  const sessions = (await openingSlide(page, 'cursus-arc').locator('ol > li').allTextContents()).map(normalize);
  const arc = [/fundamentals/, /research agents/, /remote agents/, /deploying/, /arena/];
  assert.equal(sessions.length, arc.length, 'one step per session');
  arc.forEach((pattern, i) => assert.match(sessions[i], pattern, `session ${i + 1} of the cursus`));
  const work = await onSlide(page, 'how-we-work');
  for (const pattern of [/explain/, /show/, /discuss/, /interrupt any time/]) assert.match(work, pattern);
  await predictContract(page);
  const result = openingSlide(page, 'cold-open-result');
  await count(result.locator('[data-predict]'), 1);
  await count(result.locator('fieldset[data-predict-question]'), 1);
  assert.match(normalize(await result.locator('input[data-correct]').evaluate(el => [...el.labels].map(l => l.textContent).join(' '))),
    /mix/, 'the correct choice is a mix of both');
  const answer = normalize(await textOf(result.locator('[data-predict-answer]')));
  for (const pattern of [/20 tables/, /20 chairs/, /1400/, /zero gap/]) assert.match(answer, pattern);
  assert.ok((await onSlide(page, 'discipline')).includes(
    "never raise an agent's autonomy past your ability to verify the solution, not just the code"));
  // Removed by the owner: none of it returns, anywhere in the document (masthead, slides,
  // speaker notes, footer and title).
  const whole = normalize(await page.evaluate(() => {
    const copy = document.documentElement.cloneNode(true);
    copy.querySelectorAll('script, style').forEach(node => node.remove());
    return copy.textContent;
  }));
  for (const pattern of [/\bmetr\b/, /\bslower\b/, /jagged/, /invisible edge/, /map of the day/, /\bact (?:i|ii|iii|iv|v)\b/, /sticky/]) {
    assert.doesNotMatch(whole, pattern);
  }
  for (const id of openingSlides) {
    const notes = await openingSlide(page, id).evaluate(el => [...el.children].filter(child => child.matches('details.notes'))
      .map(details => [...details.children].filter(child => child.tagName !== 'SUMMARY').map(child => child.textContent).join(' ').trim()));
    assert.ok(notes.length === 1 && notes[0].length > 0, `#${id} carries its explanation in speaker notes`);
    const n = words(await onSlide(page, id, { joiner: ' ', without: notBody }));
    assert.ok(n <= openingBodyCeiling, `#${id}: ${n} body words (at most ${openingBodyCeiling})`);
  }
});

test('D2: five valid exit questions, homework for either agent and Session 2', async t => {
  const page = await openPage(t, chromium, { file: decks.close, javaScriptEnabled: false });
  await deckContract(page);
  const ticket = topic(page, 'exit-ticket');
  assert.ok(await ticket.count() > 0);
  await count(ticket.locator('fieldset[data-predict-question]'), 5);
  await count(page.locator('[data-predict-question]'), 5);
  assert.equal(await ticket.locator('[data-predict]').count(), await page.locator('[data-predict]').count(),
    'all close-deck predict roots belong to the exit ticket');
  await predictContract(page);
  const homework = await topicText(page, 'homework');
  for (const phrase of ['/turn-in 01', '$turn-in 01', 'homework/s01/', 'p01', 'sampling, not retrieval', 'fork']) {
    assert.ok(homework.includes(phrase), `homework includes ${phrase}`);
  }
  await codePath(topic(page, 'homework'), 'exercises/home.html');
  await codePath(topic(page, 'homework'), 'exercises/homework-p01/');
  const next = await topicText(page, 'session-2');
  for (const pattern of [/session 2/, /skills?/, /sub[- ]?agents?/, /literature review/]) assert.match(next, pattern);
});

async function activeSlide(page, id) {
  await eventually(async () => {
    const state = await page.evaluate(() => ({
      hash: decodeURIComponent(location.hash.slice(1)),
      visible: [...document.querySelectorAll('[data-slide]')].filter(el => el.checkVisibility()).map(el => el.id),
    }));
    assert.deepEqual(state, { hash: id, visible: [id] });
  }, `active slide ${id}`);
}

async function goTo(page, id) {
  await page.evaluate(id => { location.hash = encodeURIComponent(id); }, id);
  await activeSlide(page, id);
}

async function blurToBody(page) {
  await page.evaluate(() => document.activeElement?.blur());
  await focused(page.locator('body'));
}

async function tabTo(page, target) {
  assert.equal(await target.isVisible(), true);
  await enabled(target);
  const limit = 2 * await page.locator('a[href], button, input, select, textarea, summary, [tabindex]').count() + 4;
  for (let i = 0; i < limit; i++) {
    if (await target.evaluate(el => el === document.activeElement)) return;
    await page.keyboard.press('Tab');
  }
  assert.fail('keyboard Tab order must reach the requested control');
}

async function initial(root) {
  await enabled(root.locator('[data-predict-lock]'), false);
  await enabled(root.locator('[data-predict-reveal]'), false);
  await enabled(root.locator('[data-predict-reset]'));
  await count(root.locator('input:checked'), 0);
  for (const radio of await root.locator('input[type="radio"]').all()) await enabled(radio);
  for (const answer of await root.locator('[data-predict-answer]').all()) assert.equal(await answer.isVisible(), false);
  for (const result of await root.locator('[data-predict-result]').all()) assert.equal(await textOf(result), '');
  assert.match(await textOf(root.locator('[data-predict-status]')), /^Choose .+, then lock in\.$/);
}

async function keyboardReveal(page, root, correctFor) {
  await initial(root);
  const questions = await root.locator('fieldset[data-predict-question]').all();
  const expected = [];
  for (let i = 0; i < questions.length; i++) {
    const question = questions[i];
    const radios = question.locator('input[type="radio"]');
    const flags = await radios.evaluateAll(els => els.map(el => el.hasAttribute('data-correct')));
    const correct = correctFor(i);
    expected.push(correct);
    const index = flags.findIndex(flag => flag === correct);
    assert.ok(index >= 0);
    // Focus the preceding choice and use a native arrow key, including wraparound.
    // Never set checked or dispatch a synthetic change event from the test.
    await radios.nth((index + flags.length - 1) % flags.length).focus();
    await page.keyboard.press('ArrowRight');
    assert.equal(await radios.nth(index).isChecked(), true);
    await count(question.locator('input:checked'), 1);
    await enabled(root.locator('[data-predict-lock]'), i === questions.length - 1);
    await enabled(root.locator('[data-predict-reveal]'), false);
  }
  const lock = root.locator('[data-predict-lock]');
  const reveal = root.locator('[data-predict-reveal]');
  const reset = root.locator('[data-predict-reset]');
  await tabTo(page, lock);
  await page.keyboard.press('Enter');
  await enabled(lock, false);
  await enabled(reveal);
  await focused(reveal);
  for (const radio of await root.locator('input[type="radio"]').all()) await enabled(radio, false);
  for (const answer of await root.locator('[data-predict-answer]').all()) assert.equal(await answer.isVisible(), false);
  await page.keyboard.press('Enter');
  await enabled(reveal, false);
  await focused(reset);
  for (let i = 0; i < questions.length; i++) {
    const question = questions[i];
    const label = await question.locator('input[data-correct]').evaluate(el => [...el.labels].map(l => l.textContent.trim()).join(' '));
    assert.equal(await textOf(question.locator('[data-predict-result]')),
      expected[i] ? 'Correct.' : `Not quite. The answer is ${label}.`);
    assert.equal(await question.locator('[data-predict-answer]').isVisible(), true);
  }
  assert.equal(await textOf(root.locator('[data-predict-status]')),
    `Revealed: ${expected.filter(Boolean).length} of ${questions.length} correct.`);
}

async function resetByKeyboard(page, root) {
  await tabTo(page, root.locator('[data-predict-reset]'));
  await page.keyboard.press('Enter');
  await focused(root.locator('input[type="radio"]').first());
  await initial(root);
}

async function revealedFits(page, slide) {
  const problems = await slide.evaluate(el => {
    const problems = [];
    for (const node of [el, document.querySelector('nav[data-deck-nav]'), ...el.querySelectorAll('*')]) {
      if (!(node instanceof HTMLElement) || !node.checkVisibility()) continue;
      const style = getComputedStyle(node);
      if (style.position === 'absolute' && node.classList.contains('visually-hidden')) continue;
      const r = node.getBoundingClientRect();
      const label = node.id || node.tagName;
      if (r.width && r.height && (r.left < -1 || r.top < -1 || r.right > innerWidth + 1 || r.bottom > innerHeight + 1)) {
        problems.push(`${label} extends beyond viewport`);
      }
      // Inline text has no client box. Check all real boxes, so an inner scrolling
      // wrapper cannot conceal an overfull slide from the slide's own scrollHeight.
      if (node.clientWidth > 0 && node.clientHeight > 0 &&
          (node.scrollHeight > node.clientHeight + 1 || node.scrollWidth > node.clientWidth + 1)) {
        problems.push(`${label} clips or scrolls content`);
      }
    }
    return problems;
  });
  assert.deepEqual(problems, [], 'revealed slide and navigation fit without internal scrolling');
}

for (const [name, file] of Object.entries(decks)) {
  const criterion = name === 'opening' ? 'D1' : 'D2';
  for (const viewport of viewports) {
    test(`${criterion}: ${name} keyboard predict/reveal/reset at ${viewport.width}x${viewport.height}`, { timeout: 120000 }, async t => {
      const page = await openPage(t, chromium, { file, viewport });
      await deckContract(page);
      const slides = page.locator('section[data-slide]').filter({ has: page.locator('[data-predict]') });
      assert.ok(await slides.count() > 0);
      await mkdir(artifacts, { recursive: true });
      for (let s = 0; s < await slides.count(); s++) {
        const slide = slides.nth(s);
        const id = await slide.getAttribute('id');
        await goTo(page, id);
        const roots = await slide.locator('[data-predict]').all();
        // Both extremes plus per-question mixed results prevent a constant score
        // or copying one question's result to the whole ticket from passing.
        for (const [round, outcome] of [() => true, () => false, i => i % 2 === 0].entries()) {
          for (const root of roots) await keyboardReveal(page, root, outcome);
          await activeSlide(page, id); // Radio arrow keys must not navigate the deck.
          await revealedFits(page, slide); // All roots on this slide are revealed together.
          await page.screenshot({ path: path.join(artifacts, `${name}-${viewport.width}x${viewport.height}-slide-${s + 1}-round-${round + 1}.png`) });
          for (const root of roots) await resetByKeyboard(page, root);
        }
      }
    });
  }
}

const quantitative = /\d|\b(?:percent|per cent|half|twice|double)\b/i;
const date = /\b\d{4}-\d{2}-\d{2}\b|\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?[\s-]+(?:\d{1,2}(?:st|nd|rd|th)?[,]?[\s-]+)?\d{4}\b/i;

test('A1: every quantitative slide has a dated source, including no-JS answers', async t => {
  for (const [name, file] of Object.entries(decks)) {
    const page = await openPage(t, chromium, { file, javaScriptEnabled: false });
    await deckContract(page);
    for (const answer of await page.locator('[data-predict-answer]').all()) assert.equal(await answer.isVisible(), true);
    for (const slide of await page.locator('[data-slide]').all()) {
      // The cold-open return's numbers solve the problem on screen, and the room checks them by
      // hand; they are not an external figure, so the owner dropped its answer-key line.
      if (name === 'opening' && await slide.getAttribute('id') === 'cold-open-result') continue;
      const text = await slide.evaluate(el => {
        const copy = el.cloneNode(true);
        copy.querySelectorAll('code, .cite, script').forEach(node => node.remove());
        return copy.textContent.replace(/\s+/g, ' ');
      });
      if (!quantitative.test(text)) continue;
      const citations = await slide.locator('.cite').all();
      let datedSource = false;
      for (const citation of citations) {
        if (!await citation.isVisible() || !date.test(await textOf(citation))) continue;
        for (const source of await citation.locator('a[href], cite, code').all()) {
          if (await source.isVisible() && (await textOf(source)).length > 0) datedSource = true;
        }
      }
      assert.ok(datedSource, `${name} #${await slide.getAttribute('id')}: numbers require a .cite containing a source and date`);
    }
    if (name === 'opening') {
      const links = await openingSlide(page, 'discovery').locator('.cite a[href]').evaluateAll(els => els.map(el => el.href));
      assert.ok(links.includes('https://arxiv.org/abs/2511.02864'), 'discovery cites the AlphaEvolve paper on arXiv');
    }
  }
});

test('A2: npm --prefix setup test collects the acceptance suite', async () => {
  await assertCollected('opening-close');
});

for (const [name, file] of Object.entries(decks)) {
  test(`A2: ${name} keyboard navigation and both post-poll navigation paths`, { timeout: 120000 }, async t => {
    const page = await openPage(t, chromium, { file });
    const ids = await deckContract(page);
    await goTo(page, ids[0]);
    for (let i = 1; i < ids.length; i++) {
      await blurToBody(page);
      await page.keyboard.press('ArrowRight');
      await activeSlide(page, ids[i]);
    }
    await blurToBody(page);
    await page.keyboard.press('Home');
    await activeSlide(page, ids[0]);
    const root = (name === 'opening' ? openingSlide(page, 'cold-open-result') : topic(page, 'exit-ticket')).locator('[data-predict]').first();
    const pollId = await root.evaluate(el => el.closest('[data-slide]').id);
    const index = ids.indexOf(pollId);
    assert.ok(index >= 0 && index < ids.length - 1, 'predict slide has a following slide');
    for (const route of ['tab', 'blur']) {
      await goTo(page, pollId);
      await keyboardReveal(page, root, i => i % 2 === 0);
      // Shared page.js intentionally ignores deck keys on a focused control.
      await page.keyboard.press('ArrowRight');
      await activeSlide(page, pollId);
      if (route === 'tab') {
        await tabTo(page, page.locator('button[data-next]'));
        await page.keyboard.press('Enter');
      } else {
        await blurToBody(page);
        await page.keyboard.press('ArrowRight');
      }
      await activeSlide(page, ids[index + 1]);
      await goTo(page, pollId);
      await resetByKeyboard(page, root);
    }
  });
}
