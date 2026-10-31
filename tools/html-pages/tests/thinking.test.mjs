import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdir, readFile, realpath, stat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { chromium } from '../browser.mjs';
import { openPage, repoRoot, count, eventually, assertCollected } from './component-helpers.mjs';

// The Act II deck tells one story: a puzzle one pass cannot solve at a glance, then five
// questions answered in order, one per part. A strip of the five questions sits on every slide
// with the current one highlighted and earlier answers filled in; the close lists all five. These
// are structural floors next to check-page and a person's review of the prose; the planner recipe
// on #repo-model is run in a browser by thinking-planner.test.mjs.
const cursus = path.join(repoRoot, 'sessions/01-fundamentals/cursus');
const file = path.join(cursus, '02-thinking.html');
const artifacts = path.join(repoRoot, 'artifacts/html-pages/thinking');
const viewports = [
  { width: 1440, height: 900 },
  { width: 1280, height: 720 },
  { width: 390, height: 844 },
];
const order = ['loop', 'cot-depth', 'search', 'rlvr', 'effort-demo', 'overthinking', 'cot-faithfulness',
  'addition-36-59', 'world-models', 'kepler', 'repo-model', 'wrap'];
const questions = ['How does it think?', 'Is it right?', 'How much thinking?', 'Trust what it wrote?', 'What does it know?'];
const answers = ['It writes.', 'Only a check can say.', 'A dial; more can hurt.', 'A lead, not evidence.', 'A picture to keep fed.'];
// Each part's slides, in order, and the activity linked from a slide's face, if any.
const parts = [
  { id: 'cot-depth', part: 1 },
  { id: 'search', part: 2, activity: 'labs/test-time-compute.html#best-of-n' },
  { id: 'rlvr', part: 2, activity: 'labs/test-time-compute.html#sharpen-or-expand' },
  { id: 'effort-demo', part: 3, activity: 'demos/effort/README.md' },
  { id: 'overthinking', part: 3, activity: 'labs/test-time-compute.html#effort-dial' },
  { id: 'cot-faithfulness', part: 4 },
  { id: 'addition-36-59', part: 4 },
  { id: 'world-models', part: 5 },
  { id: 'kepler', part: 5, activity: 'labs/world-model.html#kepler' },
  { id: 'repo-model', part: 5, activity: 'labs/world-model.html#planner' },
];
// Research claims keep a short source on the face; the rest of the sources sit in the notes.
const cited = ['cot-depth', 'search', 'rlvr', 'overthinking', 'cot-faithfulness', 'addition-36-59', 'world-models', 'kepler'];
// About 30 to 45 words on a face. Exact quotations, formulas and tables are content, not prose.
const faceWords = 48;
const norm = value => value.normalize('NFKC').replace(/[‘’]/g, "'")
  .replace(/[−–]/g, '-').replace(/\s+/g, ' ').trim().toLowerCase();
const words = text => (text.match(/[\p{L}\p{N}]+(?:['.\-/][\p{L}\p{N}]+)*/gu) || []).length;
const topic = (page, id) => page.locator(`section[data-slide]#${id}`);
const slides = page => page.locator('main[data-deck] section[data-slide]');
const notes = slide => slide.locator('details.speaker-notes');
const notesText = async slide => norm(await notes(slide).evaluate(el => {
  const copy = el.cloneNode(true);
  copy.querySelector('summary')?.remove();
  return copy.textContent;
}));
// The student-facing face: no notes, no decorative graph, no text that only screen readers get.
async function face(slide, extra = []) {
  return norm(await slide.evaluate((el, extra) => {
    const copy = el.cloneNode(true);
    copy.querySelectorAll(['details.speaker-notes', 'script', 'svg', '[hidden]', '[aria-hidden="true"]',
      '.visually-hidden', ...extra].join(', ')).forEach(node => node.remove());
    return copy.textContent;
  }, extra));
}
async function pageFor(t, options = {}) {
  return openPage(t, chromium, { file, ...options });
}
async function idsOf(page) {
  return slides(page).evaluateAll(els => els.map(el => el.id));
}
async function activeSlide(page, id) {
  await eventually(async () => {
    assert.equal(decodeURIComponent(new URL(page.url()).hash.slice(1)), id);
    assert.equal(await page.locator('section[data-slide]').evaluateAll((els, id) => {
      const target = els.find(el => el.id === id);
      return !!target && target.checkVisibility();
    }, id), true, `#${id} is visible`);
    if (await page.locator('html').getAttribute('data-deck-paged') !== null) {
      assert.deepEqual(await slides(page).evaluateAll(els => els.filter(el => el.checkVisibility()).map(el => el.id)), [id]);
    }
  }, `return to slide ${id}`);
}
async function goTo(page, id) {
  await page.evaluate(id => { location.hash = encodeURIComponent(id); }, id);
  await activeSlide(page, id);
}
async function noHorizontalOverflow(page, disclosure) {
  const problems = await disclosure.evaluate(el => {
    const result = [];
    if (document.documentElement.scrollWidth > innerWidth + 1) result.push('document');
    for (const node of [el, ...el.querySelectorAll('*')]) {
      if (!(node instanceof HTMLElement) || !node.checkVisibility()) continue;
      const css = getComputedStyle(node);
      if (css.position === 'absolute' && node.classList.contains('visually-hidden')) continue;
      if (node.clientWidth && node.scrollWidth > node.clientWidth + 1) result.push(node.tagName);
    }
    return result;
  });
  assert.deepEqual(problems, [], 'open notes have no horizontal overflow');
}

test('D1: authored deck, one collapsed disclosure per slide, and no minutes anywhere', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  assert.equal(await page.locator('html').getAttribute('data-page-kind'), 'deck');
  assert.equal(await page.locator('html').getAttribute('data-design-system'), 'cursus');
  await count(page.locator('main[data-deck]'), 1);
  await count(page.locator('main[data-deck] nav[data-deck-nav]'), 1);
  await count(page.locator('script[src], script[type="module"]'), 0);
  const ids = await idsOf(page);
  assert.equal(new Set(ids).size, ids.length, 'slide ids are unique');
  await count(page.locator('details.speaker-notes'), ids.length);
  for (const slide of await slides(page).all()) {
    assert.equal(await slide.isVisible(), true, 'no-JS readers can read every slide');
    const disclosure = notes(slide);
    await count(disclosure, 1);
    assert.equal(await disclosure.evaluate(el => el.open), false, 'notes are authored collapsed');
    assert.equal(norm(await disclosure.locator(':scope > summary').textContent()), 'speaker notes');
    const talk = await notesText(slide);
    assert.ok(talk.split(/\s+/).filter(Boolean).length >= 40, 'notes carry the talk track the instructor reads aloud');
    assert.match(talk, /^goal: /, 'notes open with what students should leave with');
    assert.match(talk, /transition: |talk track: /, 'notes say what to present');
  }
  // Timing lives in the run of show, not in the deck.
  await count(page.locator('[data-minutes]'), 0);
  const text = await page.locator('body').evaluate(el => el.textContent);
  assert.doesNotMatch(text, /\bminutes?\b|\b\d+\s?min\b/i, 'no minutes on slides or in notes');
  assert.match(norm(await page.locator('.masthead').innerText()), /act ii/);
  await assertCollected('thinking');
});

test('D1: slide faces are sparse and carry no recording artefacts', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  await count(page.locator('footer'), 0);
  for (const slide of await slides(page).all()) {
    const id = await slide.getAttribute('id');
    assert.doesNotMatch(await face(slide), /\brecorded\b|fixtures\/|\.json\b|\b20\d\d-\d\d-\d\d\b/, `#${id}: no provenance on the face`);
    await count(slide.locator('.drive'), 0);
    await count(slide.locator('h2'), 1);
    const body = await face(slide, ['h2', '.eyebrow', '.cite', '[role="img"]', 'table', 'blockquote', '.law .f']);
    assert.ok(words(body) <= faceWords, `#${id}: ${words(body)} words on the face (at most ${faceWords})`);
  }
  assert.deepEqual(await page.locator('main .cite').evaluateAll(els => els.map(el => el.closest('section').id)), cited,
    'a short source only where the slide makes a research claim');
  for (const source of await page.locator('main .cite').all()) {
    await count(source.locator('a[href^="https://"]'), 1);
    assert.match(norm(await source.textContent()), /^source: .+, 20\d\d\.$/, 'author, title, link, year');
  }
});

test('D2: the act opens on the puzzle and keeps to its order', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  assert.deepEqual(await idsOf(page), order);
});

test('D2: the opening strip lists the five questions, unanswered, each linking its part', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  const slide = topic(page, 'loop');
  const strip = slide.locator('svg.spine');
  await count(strip, 1);
  assert.equal(await strip.getAttribute('role'), null, 'the overview is navigation, not an image');
  assert.deepEqual(await strip.locator('.q .t').allTextContents(), questions.map((q, i) => `${i + 1} · ${q}`));
  assert.deepEqual(await strip.locator('.q').evaluateAll(els => els.map(el => el.classList.contains('all'))), questions.map(() => true));
  const links = await strip.locator('a').evaluateAll(els => els.map(el => el.getAttribute('href')));
  assert.deepEqual(links, [1, 2, 3, 4, 5].map(n => `#${parts.find(p => p.part === n).id}`), 'each question opens its part');
  await count(slide.locator('figure.spine-wrap figcaption.visually-hidden'), 1);
});

test('D2: each part repeats the strip, with earlier answers filled in and its own question highlighted', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  const geometry = el => [...el.querySelectorAll('rect, path')].map(node => node.getAttribute('x') + node.getAttribute('d'));
  const reference = await topic(page, 'loop').locator('svg.spine').evaluate(geometry);
  await count(page.locator('svg.spine [id]'), 0);
  for (const { id, part } of [...parts, { id: 'wrap', part: 6 }]) {
    const slide = topic(page, id);
    const strip = slide.locator('svg.spine');
    await count(strip, 1);
    assert.deepEqual(await strip.evaluate(geometry), reference, `${id}: the copy has the same geometry`);
    assert.equal(await strip.getAttribute('role'), 'img');
    assert.match(norm(await strip.getAttribute('aria-label')), part > 5 ? /all five answered/ : new RegExp(`highlighted: question ${part}`));
    await count(strip.locator('a'), 0);
    const states = await strip.locator('.q').evaluateAll(els => els.map(el => ['done', 'now', 'next'].find(name => el.classList.contains(name))));
    assert.deepEqual(states, [1, 2, 3, 4, 5].map(n => n < part ? 'done' : n === part ? 'now' : 'next'), `${id}: part ${part}`);
    // Answers show once their part is done: the strip fills in as the story goes.
    const shown = await strip.locator('.q').evaluateAll(els => els.map(el => getComputedStyle(el.querySelector('.a')).visibility));
    assert.deepEqual(shown, [1, 2, 3, 4, 5].map(n => n < part ? 'visible' : 'hidden'), `${id}: answers so far`);
    assert.deepEqual(await strip.locator('.q .a').allTextContents(), answers);
    const wrap = slide.locator('.spine-wrap');
    assert.equal(await wrap.getAttribute('role'), 'region');
    assert.equal(await wrap.getAttribute('tabindex'), '0');
    assert.ok(await wrap.getAttribute('aria-label'), 'the scrolling wrapper is labelled');
    // The eyebrow names the same part and question as the strip.
    if (part <= 5) assert.ok(norm(await slide.locator(':scope > .eyebrow').textContent()).startsWith(norm(`Part ${part} · ${questions[part - 1]}`)),
      `${id}: the eyebrow names part ${part}`);
  }
});

test('D2: the close shows the strip fully answered, and one habit per answer', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  const close = topic(page, 'wrap');
  const habits = close.locator('ol.answers > li');
  await count(habits, 5);
  const labels = await habits.locator('.q').allTextContents();
  labels.forEach((label, i) => assert.ok(label.startsWith(`${i + 1} · `), `habit ${i + 1} is numbered like its question`));
  assert.ok((await habits.locator('strong').allTextContents()).every(text => text.trim().length > 0));
  // The closing headline answers the opening one.
  assert.match(norm(await topic(page, 'loop').locator('h2').textContent()), /glance/);
  assert.match(norm(await close.locator('h2').textContent()), /glance/);
});

test('D3: the running example is the effort demo’s real puzzle and recorded reply', async t => {
  const results = JSON.parse(await readFile(path.join(cursus, 'demos/effort/recorded/results.json'), 'utf8'));
  const low = results.runs.find(run => run.cli === 'claude' && run.effort === 'low');
  const prompt = await readFile(path.join(cursus, 'demos/effort/prompt.txt'), 'utf8');
  const parcels = [...prompt.matchAll(/^\| ([A-H]) \| (\d+) \| (\d+) \|$/gm)].map(m => [m[1], Number(m[2]), Number(m[3])]);
  assert.equal(parcels.length, 8, 'the prompt lists eight parcels');
  const page = await pageFor(t, { javaScriptEnabled: false });
  const opener = topic(page, 'loop');
  const shown = await opener.locator('table.parcels').evaluate(el => {
    const rows = [...el.querySelectorAll('tr')].map(tr => [...tr.cells].map(cell => cell.textContent.trim()));
    return rows[0].slice(1).map((name, i) => [name, Number(rows[1][i + 1]), Number(rows[2][i + 1])]);
  });
  assert.deepEqual(shown, parcels, 'the opener shows the prompt’s parcels');
  assert.match(await face(opener), new RegExp(`\\b${results.puzzle.capacity} kg\\b`));
  assert.doesNotMatch(await face(opener), new RegExp(`\\b${results.puzzle.optimum}\\b`), 'the opener does not give the answer away');
  // Part 1 quotes the recorded reply verbatim, and counts its hidden thinking.
  const raw = await readFile(path.join(cursus, 'demos/effort/recorded/raw/claude-low.jsonl'), 'utf8');
  const reply = raw.split('\n').filter(Boolean).map(line => JSON.parse(line)).filter(event => event.type === 'assistant')
    .flatMap(event => event.message.content).filter(part => part.type === 'text').map(part => part.text.replace(/\*\*/g, '')).join('\n');
  const lines = await topic(page, 'cot-depth').locator('.reply blockquote p').allTextContents();
  assert.ok(lines.length >= 3, 'several lines of the reply');
  for (const line of lines) assert.ok(reply.includes(line.replace(/\s+/g, ' ').trim()), `quoted from the recording: ${line}`);
  assert.match(await face(topic(page, 'cot-depth')), new RegExp(`\\b${low.tokens.thinking} tokens\\b`), 'the thinking count is the recorded one');
  // The recorded rows are the fallback, read from the notes when the live run cannot go.
  const talk = await notesText(topic(page, 'effort-demo'));
  for (const run of results.runs) {
    assert.ok(talk.includes(`${run.model}, ${run.effort}: ${run.tokens.output} output tokens`), `${run.model} ${run.effort} is in the notes`);
    assert.ok(talk.includes(`$${run.cost_usd.toFixed(4)}`), `${run.model} ${run.effort} cost is in the notes`);
  }
  assert.match(talk, /uv run --offline effort\.py replay/);
  assert.match(talk, /as of 2026-10-18/, 'the vendor effort settings keep their as-of date');
  assert.match(talk, new RegExp(`${results.puzzle.optimum} eur`), 'the check’s answer is in the notes');
});

test('D4: the act keeps its promises to Act I and the close', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  // Act I: the System 1 label is a metaphor; RL with verifiable rewards is Act II's.
  const depth = await notesText(topic(page, 'cot-depth'));
  assert.match(depth, /system 2/);
  assert.match(depth, /kahneman/);
  assert.match(await face(topic(page, 'cot-depth')), /chain of thought/);
  assert.match(await notesText(topic(page, 'rlvr')), /verifiable rewards/);
  // The close's exit ticket: an exact check beats a vote.
  const search = await face(topic(page, 'search'));
  assert.match(search, /answer key/);
  assert.match(search, /vote/);
  assert.match(await face(topic(page, 'rlvr')), /contested/);
  assert.match(await face(topic(page, 'cot-faithfulness')), /contested/);
  // Act V returns to injection; Act III adds a check on every turn.
  assert.match(await notesText(topic(page, 'cot-faithfulness')), /act v/);
  assert.match(await notesText(topic(page, 'wrap')), /every turn/);
});

async function localLinks(page) {
  const links = [];
  const root = await realpath(cursus);
  for (const link of await page.locator('a[href]').all()) {
    const href = await link.getAttribute('href');
    assert.ok(!/(?:^|\/)(?:tokenizer|attention|next-token|tiny-lm|context|agent-loop)\.html(?:[?#]|$)/.test(href),
      `other acts’ labs belong to their acts: ${href}`);
    if (/^https?:/i.test(href)) continue; // citations are links, never runtime dependencies
    if (href.startsWith('#')) {
      await count(page.locator(`[id="${decodeURIComponent(href.slice(1))}"]`), 1);
      continue;
    }
    assert.ok(!/^(?:[a-z][a-z\d+.-]*:|\/)/i.test(href), `local link must be relative: ${href}`);
    const url = new URL(href, pathToFileURL(file));
    const target = await realpath(fileURLToPath(url));
    const relative = path.relative(root, target);
    assert.ok(relative !== '..' && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative),
      `local target stays in cursus: ${href}`);
    assert.equal((await stat(target)).isFile(), true, `local target exists: ${href}`);
    if (url.hash) {
      const fragment = decodeURIComponent(url.hash.slice(1));
      const source = await readFile(target, 'utf8');
      assert.equal(await page.evaluate(({ source, fragment }) =>
        !!new DOMParser().parseFromString(source, 'text/html').getElementById(fragment), { source, fragment }), true,
      `fragment exists: ${href}`);
    }
    links.push({ href, ...await link.evaluate(el => ({
      slide: el.closest('section[data-slide]')?.id ?? null,
      inNotes: !!el.closest('details.speaker-notes'),
    })) });
  }
  return links;
}

test('D5: relative links resolve and each lab or demo is linked from its own slide', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  const links = await localLinks(page);
  for (const part of parts.filter(part => part.activity)) {
    assert.ok(links.some(link => !link.inNotes && link.slide === part.id && link.href === part.activity),
      `${part.activity} is linked from the face of #${part.id}`);
  }
});

test('D5: the labs load offline and Back restores their originating slides', { timeout: 120000 }, async t => {
  const page = await pageFor(t);
  for (const part of parts.filter(part => part.activity?.startsWith('labs/'))) {
    await goTo(page, part.id);
    const anchor = topic(page, part.id).locator(`:scope > :not(details) a[href=${JSON.stringify(part.activity)}]`).first();
    assert.ok(['', null, '_self'].includes(await anchor.getAttribute('target')), 'activity can return with browser Back');
    const destination = path.join(cursus, part.activity.split('#')[0]);
    await Promise.all([
      page.waitForURL(url => url.protocol === 'file:' && fileURLToPath(url) === destination),
      anchor.click(),
    ]);
    assert.equal(await page.locator('html').getAttribute('data-page-kind'), 'lab');
    assert.ok((await page.locator('body').innerText()).trim().length > 0, 'lab is readable offline');
    await page.goBack();
    await activeSlide(page, part.id);
  }
});

test('D5: a question on the opening strip opens its part', async t => {
  const page = await pageFor(t, { viewport: viewports[0] });
  await goTo(page, 'loop');
  await topic(page, 'loop').locator('svg.spine a[href="#search"]').click();
  await activeSlide(page, 'search');
});

for (const viewport of viewports.slice(0, 2)) {
  test(`D1: every slide fits ${viewport.width}×${viewport.height} without internal scrolling`, { timeout: 120000 }, async t => {
    const page = await pageFor(t, { viewport });
    await mkdir(artifacts, { recursive: true });
    for (const id of await idsOf(page)) {
      await goTo(page, id);
      const problems = await topic(page, id).evaluate(el => {
        const result = [];
        for (const node of [el, document.querySelector('nav[data-deck-nav]'), ...el.querySelectorAll('*')]) {
          if (!(node instanceof HTMLElement) || !node.checkVisibility()) continue;
          if (getComputedStyle(node).position === 'absolute' && node.classList.contains('visually-hidden')) continue;
          const r = node.getBoundingClientRect();
          const label = node.id || node.className || node.tagName;
          if (r.width && r.height && (r.left < -1 || r.top < -1 || r.right > innerWidth + 1 || r.bottom > innerHeight + 1)) result.push(`${label} extends beyond viewport`);
          if (node.clientWidth > 0 && node.clientHeight > 0 &&
            (node.scrollHeight > node.clientHeight + 1 || node.scrollWidth > node.clientWidth + 1)) result.push(`${label} scrolls`);
        }
        return result;
      });
      assert.deepEqual(problems, [], `#${id} fits without internal scrolling`);
      const title = await topic(page, id).locator('h2').evaluate(el => {
        const line = parseFloat(getComputedStyle(el).lineHeight) || parseFloat(getComputedStyle(el).fontSize) * 1.3;
        return el.getBoundingClientRect().height / line;
      });
      assert.ok(title < 1.5, `#${id}: the headline is one line`);
      await page.screenshot({ path: path.join(artifacts, `${viewport.width}-${id}.png`) });
    }
  });
}

for (const viewport of viewports) {
  test(`D1: every disclosure works by keyboard at ${viewport.width}×${viewport.height}, including long notes`, { timeout: 120000 }, async t => {
    const page = await pageFor(t, { viewport });
    const ids = await idsOf(page);
    for (const [index, id] of ids.entries()) {
      await goTo(page, id);
      const disclosure = notes(slides(page).nth(index));
      const summary = disclosure.locator(':scope > summary');
      assert.equal(await disclosure.evaluate(el => el.open), false);
      await summary.focus();
      // Alternate native activation paths; Enter alone must not mask broken Space.
      const key = index % 2 ? 'Space' : 'Enter';
      await page.keyboard.press(key);
      await eventually(async () => assert.equal(await disclosure.evaluate(el => el.open), true));
      await activeSlide(page, id); // Deck keys must not hijack native summaries.
      assert.equal(await summary.evaluate(el => el === document.activeElement), true);
      await noHorizontalOverflow(page, disclosure);
      await page.keyboard.press(key);
      await eventually(async () => assert.equal(await disclosure.evaluate(el => el.open), false));
      await activeSlide(page, id);
    }
    // The longest notes, the effort demo's, scroll inside the details rather than clip the talk track.
    await goTo(page, 'effort-demo');
    const disclosure = notes(topic(page, 'effort-demo'));
    await disclosure.locator(':scope > summary').focus();
    await page.keyboard.press('Enter');
    await disclosure.evaluate(el => {
      const body = el.querySelector('.notes-body');
      for (let i = 0; i < 40; i++) body.append(body.querySelector('p').cloneNode(true));
    });
    await noHorizontalOverflow(page, disclosure);
    const scrolling = await disclosure.locator('.notes-body').evaluate(node => {
      node.scrollTop = node.scrollHeight;
      return node.scrollTop > 0 && node.scrollTop + node.clientHeight >= node.scrollHeight - 2;
    });
    assert.ok(scrolling, 'long notes scroll to their end inside the details element');
  });
}

async function highlightsInView(page) {
  for (const part of parts) {
    const wrap = topic(page, part.id).locator('.spine-wrap');
    await eventually(async () => {
      const state = await wrap.evaluate(el => {
        const now = el.querySelector('.q.now').getBoundingClientRect();
        const frame = el.getBoundingClientRect();
        return { scrolls: el.scrollWidth > el.clientWidth, visible: now.left >= frame.left - 1 && now.right <= frame.right + 1 };
      });
      assert.deepEqual(state, { scrolls: true, visible: true }, `${part.id}: current question in view`);
    }, `${part.id}: current question in view`);
  }
}

test('D1: on a phone the strip scrolls sideways, starting at the current question', async t => {
  await highlightsInView(await pageFor(t, { viewport: viewports[2] }));
});

test('D1: after a wide page is narrowed, each strip scrolls to its current question', async t => {
  const page = await pageFor(t, { viewport: viewports[0] });
  await goTo(page, 'kepler');
  await page.setViewportSize(viewports[2]);
  await highlightsInView(page);
});

test('D1: print reveals all talk tracks without scroll clipping', async t => {
  const page = await pageFor(t);
  await page.emulateMedia({ media: 'print' });
  await eventually(async () => {
    for (const slide of await slides(page).all()) {
      assert.equal(await slide.isVisible(), true, 'all slides print');
      const result = await notes(slide).evaluate(el => {
        const children = [...el.children].filter(node => node.tagName !== 'SUMMARY');
        const readable = children.length ? children.every(node => node.checkVisibility()) : el.open;
        const clipped = [el, ...el.querySelectorAll('*')].some(node => node.clientHeight > 0 &&
          node.scrollHeight > node.clientHeight + 1 && /auto|scroll|hidden|clip/.test(getComputedStyle(node).overflowY));
        return { readable, clipped };
      });
      assert.deepEqual(result, { readable: true, clipped: false }, 'print contains the full note body');
    }
  });
});
