import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import path from 'node:path';
import { chromium } from '../browser.mjs';
import { openPage, repoRoot, read, suites, count, enabled, focused, textOf, eventually } from './component-helpers.mjs';

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

test('D1: opening topics, canonical discipline, poll and teaching structure', async t => {
  const page = await openPage(t, chromium, { file: decks.opening, javaScriptEnabled: false });
  await deckContract(page);
  for (const id of ['title', 'cold-open', 'metr-poll', 'metr-follow-up', 'jagged-frontier', 'discipline', 'day-map', 'how-we-work']) {
    assert.ok(await topic(page, id).count() > 0, `missing topic ${id}`);
  }
  assert.ok((await topicText(page, 'discipline')).includes(
    "never raise an agent's autonomy past your ability to verify the solution, not just the code"));
  const cold = await topicText(page, 'cold-open');
  assert.match(cold, /highs|certificate/);
  await codePath(topic(page, 'cold-open'), 'cursus/demos/cold-open/');
  await predictContract(page);
  const poll = topic(page, 'metr-poll');
  await count(poll.locator('[data-predict]'), 1);
  await count(poll.locator('fieldset[data-predict-question]'), 1);
  const pollText = await topicText(page, 'metr-poll');
  assert.match(pollText, /24\s*%/);
  assert.match(pollText, /19\s*%/);
  const followUp = await topicText(page, 'metr-follow-up');
  for (const pattern of [/2026/, /-\s*18\s*%/, /-\s*4\s*%/, /selection|opt[- ]?out/]) assert.match(followUp, pattern);
  const timeline = topic(page, 'day-map').locator('ol');
  assert.ok(await timeline.count() > 0, 'day map is an ordered timeline');
  const rows = (await timeline.locator('li').allTextContents()).map(normalize);
  let previous = -1;
  for (const pattern of [/\bopening\b/, /\bact i\b/, /\bact ii\b/, /\bact iii\b/, /\bact iv\b/, /\bact v\b/, /\bclose\b/]) {
    const index = rows.findIndex((text, i) => i > previous && pattern.test(text));
    assert.ok(index > previous, `timeline contains ${pattern} in order`);
    previous = index;
  }
  const work = await topicText(page, 'how-we-work');
  for (const pattern of [/watch/, /predict/, /drive/, /sticky/, /pair/]) assert.match(work, pattern);
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
      for (const [id, url] of [
        ['metr-poll', 'https://metr.org/blog/2025-07-10-early-2025-ai-experienced-os-dev-study/'],
        ['metr-follow-up', 'https://metr.org/blog/2026-02-24-uplift-update/'],
      ]) {
        const links = await topic(page, id).locator('.cite a[href]').evaluateAll(els => els.map(el => el.href.replace(/\/$/, '')));
        assert.ok(links.includes(url.replace(/\/$/, '')), `${id} cites its METR source`);
      }
      const frontier = topic(page, 'jagged-frontier').locator('.cite');
      const sources = normalize((await frontier.allTextContents()).join(' ') + ' ' +
        (await frontier.locator('a[href]').evaluateAll(els => els.map(el => el.href))).join(' '));
      assert.match(sources, /10\.1287\/orsc\.2025\.21838|4573321|(?:hbs|working paper)[\s\S]*24-013/,
        'jagged frontier cites the journal DOI or the identified working paper');
    }
  }
});

test('A2: acceptance suite is registered in both durable suite lists', async () => {
  assert.ok(suites.includes('opening-close'), 'register opening-close in component-helpers.mjs');
  const pkg = JSON.parse(await read('setup/package.json'));
  assert.ok(pkg.scripts.test.split(/\s+/).includes('../tools/html-pages/tests/opening-close.test.mjs'),
    'register opening-close.test.mjs in the explicit npm test command');
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
    const root = topic(page, name === 'opening' ? 'metr-poll' : 'exit-ticket').locator('[data-predict]').first();
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
