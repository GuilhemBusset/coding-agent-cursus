import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdir, readFile, realpath, stat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { chromium } from '../browser.mjs';
import { openPage, repoRoot, count, eventually, focused, assertCollected } from './component-helpers.mjs';

// The Act II deck tells one story: a puzzle one pass cannot solve at a glance, then five
// questions answered in order, one per part. Its mechanism, the spine, sits on every slide: each
// question is a numbered badge pinned on the part it asks about, the current part is lit and the
// answered badges are filled; the close opens each badge into a habit. Five slides carry a control
// (the van, the bet and its check, the waffles, "Ask it how", the planner's frames): each works by
// pointer and keyboard without taking the deck's keys, and its slide reads without JS and in print.
// These are structural floors next to check-page and a person's review of the prose; the planner
// recipe on #repo-model is run in a browser by thinking-planner.test.mjs.
const cursus = path.join(repoRoot, 'sessions/01-fundamentals/cursus');
const file = path.join(cursus, '02-thinking.html');
const lab = path.join(cursus, 'labs/world-model.html');
const artifacts = path.join(repoRoot, 'artifacts/html-pages/thinking');
const viewports = [
  { width: 1440, height: 900 },
  { width: 1280, height: 720 },
  { width: 390, height: 844 },
];
const order = ['loop', 'cot-depth', 'search', 'rlvr', 'effort-demo', 'overthinking', 'cot-faithfulness',
  'addition-36-59', 'world-models', 'kepler', 'repo-model', 'wrap'];
const questions = ['How does it think?', 'Is it right?', 'How much thinking?', 'Trust what it wrote?', 'What does it know?'];
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
const cited = ['search', 'rlvr', 'overthinking', 'cot-faithfulness', 'addition-36-59', 'world-models', 'kepler'];
// About 30 to 45 words of prose on a face: text a student reads as text. Not counted: the headline,
// eyebrow and source; the spine, the same on every slide; pictures (SVG, or role="img", whose labels
// belong to the picture and whose equivalent is the aria-label); text only assistive tech gets;
// quotations, tables and #kepler's formulas, which are content; and controls with their group labels
// (the parcels, the bet chips, Reveal, Reset, Step).
const faceWords = 48;
const notProse = ['h2', '.eyebrow', '.cite', '.spine-wrap', '[role="img"]', 'table', 'blockquote', '.kep-f', 'button', '[role="group"]'];
const norm = value => value.normalize('NFKC').replace(/[‘’]/g, "'")
  .replace(/[−–]/g, '-').replace(/\s+/g, ' ').trim().toLowerCase();
const words = text => (text.match(/[\p{L}\p{N}]+(?:['.\-/][\p{L}\p{N}]+)*/gu) || []).length;
const sum = values => values.reduce((a, b) => a + b, 0);
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
// The effort demo's puzzle, from its prompt, and every load: each parcel goes whole or stays behind.
async function puzzle() {
  const prompt = await readFile(path.join(cursus, 'demos/effort/prompt.txt'), 'utf8');
  const capacity = Number(prompt.match(/capacity of (\d+) kg/)?.[1]);
  const parcels = [...prompt.matchAll(/^\| ([A-H]) \| (\d+) \| (\d+) \|$/gm)].map(m => ({ name: m[1], kg: Number(m[2]), eur: Number(m[3]) }));
  assert.equal(parcels.length, 8, 'the prompt lists eight parcels');
  const loads = Array.from({ length: 2 ** parcels.length }, (_, mask) => {
    const chosen = parcels.filter((_, i) => mask & (1 << i));
    return { names: chosen.map(p => p.name), kg: sum(chosen.map(p => p.kg)), eur: sum(chosen.map(p => p.eur)) };
  });
  const fit = loads.filter(load => load.kg <= capacity).sort((a, b) => b.eur - a.eur);
  // Loading by value per kg, the room's usual shortcut, which misses the best load.
  const greedy = { names: [], kg: 0, eur: 0 };
  for (const p of [...parcels].sort((a, b) => b.eur / b.kg - a.eur / a.kg)) {
    if (greedy.kg + p.kg <= capacity) Object.assign(greedy, { names: [...greedy.names, p.name], kg: greedy.kg + p.kg, eur: greedy.eur + p.eur });
  }
  const weigh = names => {
    const chosen = parcels.filter(p => names.includes(p.name));
    return { kg: sum(chosen.map(p => p.kg)), eur: sum(chosen.map(p => p.eur)) };
  };
  return { capacity, parcels, loads, fit, best: fit[0], runnerUp: fit[1], greedy, weigh };
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

// Run in the page, so self-contained. One copy of the spine as a viewer sees it: each badge's state
// by its number, how many parts are lit, the answer shown, and whether the verdict shows.
function readSpine(svg) {
  const state = el => ['all', 'done', 'now', 'next'].find(name => el.classList.contains(name));
  const badges = [...svg.querySelectorAll('.badge')];
  const answer = [...svg.querySelectorAll('.node')].find(node => node.querySelector('.t')?.textContent === 'Answer');
  return {
    badges: Object.fromEntries(badges.map(badge => [badge.querySelector('.n').textContent, state(badge)])),
    lit: svg.querySelectorAll(':is(.node, .track, .stack).now').length,
    answer: [...answer.querySelectorAll('.s')].filter(s => getComputedStyle(s).visibility === 'visible').map(s => s.textContent),
    verdict: getComputedStyle(svg.querySelector('.verdict')).visibility === 'visible',
  };
}
// The drawn shapes of a copy, without the close's habits: copies differ only in their classes.
function geometry(svg) {
  return [...svg.querySelectorAll('rect, path, circle')].filter(el => !el.closest('.habits'))
    .map(el => ['x', 'y', 'width', 'height', 'd', 'cx', 'cy', 'r'].map(name => el.getAttribute(name) ?? '').join(' '));
}
// Per waffle, the cells drawn like the legend's "says so" key.
async function filled(page) {
  return topic(page, 'cot-faithfulness').locator('[data-cf-chart]').evaluate(chart => {
    const on = getComputedStyle(chart.querySelector('.cf-head i.on')).backgroundColor;
    return [...chart.querySelectorAll('.cf-waffle')].map(waffle =>
      [...waffle.children].filter(cell => getComputedStyle(cell).backgroundColor === on).length);
  });
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
    const id = await slide.getAttribute('id');
    assert.equal(await slide.isVisible(), true, 'no-JS readers can read every slide');
    const disclosure = notes(slide);
    await count(disclosure, 1);
    assert.equal(await disclosure.evaluate(el => el.open), false, 'notes are authored collapsed');
    assert.equal(norm(await disclosure.locator(':scope > summary').textContent()), 'speaker notes');
    // The sampler's format: a talk track read aloud, not a plan of the slide.
    const talk = await notesText(slide);
    assert.ok(words(talk) >= 40, `#${id}: notes carry the talk track the instructor reads aloud`);
    assert.doesNotMatch(talk, /\b(?:goal|driving):/, `#${id}: no Goal or Driving labels`);
    assert.match(talk, /^(?:talk track|predict question)\b/, `#${id}: notes open on the talk track, or the predict question asked first`);
    assert.match(talk, /\btalk track: /, `#${id}: a talk track`);
    assert.match(talk, /\btransition\b[^.:]*: /, `#${id}: a transition`);
    assert.ok((talk.match(/background for you, not for the slides/g) || []).length <= 1, `#${id}: at most one background line`);
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
    const body = await face(slide, notProse);
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

test('D2: the opening spine is the overview: every badge unanswered, each part linking its slide', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  const slide = topic(page, 'loop');
  const spine = slide.locator('svg.spine');
  await count(spine, 1);
  assert.equal(await spine.getAttribute('role'), null, 'the overview is navigation, not an image');
  const links = await spine.locator('a').evaluateAll(els => els.map(el => [el.getAttribute('href'), el.getAttribute('aria-label')]));
  assert.deepEqual(links, questions.map((question, i) => [`#${parts.find(p => p.part === i + 1).id}`, `Part ${i + 1} · ${question}`]),
    'each part opens its first slide, in question order');
  // A link wraps the part its question is pinned on.
  assert.deepEqual(await spine.locator('a').evaluateAll(els => els.map(el => el.querySelector('.badge .n')?.textContent)), ['1', '2', '3', '4', '5']);
  assert.deepEqual(await spine.evaluate(readSpine), {
    badges: { 1: 'all', 2: 'all', 3: 'all', 4: 'all', 5: 'all' }, lit: 0, answer: ['? EUR'], verdict: false,
  }, 'nothing answered yet, and no spoiler for the puzzle');
  await count(slide.locator('figure.spine-wrap figcaption.visually-hidden'), 1);
});

test('D2: every other slide repeats the spine as an image, its question current and its part lit', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  const reference = await topic(page, 'loop').locator('svg.spine').evaluate(geometry);
  await count(page.locator('svg.spine [id]'), 0);
  const labels = [];
  for (const { id, part } of [...parts, { id: 'wrap', part: 6 }]) {
    const slide = topic(page, id);
    const spine = slide.locator('svg.spine');
    await count(spine, 1);
    assert.deepEqual(await spine.evaluate(geometry), reference, `${id}: the copy has the same geometry`);
    assert.equal(await spine.getAttribute('role'), 'img');
    const label = norm(await spine.getAttribute('aria-label'));
    assert.match(label, part > 5 ? /all five questions answered/ : new RegExp(`highlighted: question ${part}\\b`));
    labels.push(label);
    await count(spine.locator('a'), 0);
    const seen = await spine.evaluate(readSpine);
    const badge = n => part > 5 || n === part ? 'now' : n < part ? 'done' : 'next';
    assert.deepEqual(seen.badges, Object.fromEntries([1, 2, 3, 4, 5].map(n => [n, badge(n)])), `${id}: answered up to question ${part}`);
    if (part <= 5) assert.ok(seen.lit > 0, `${id}: the parts question ${part} is about are lit`);
    // The model's reply states 229 on #cot-depth. The check's ✓ waits for #effort-demo's reveal, so it
    // cannot answer the room's "Right this time?" bet; it shows from the next slide on.
    assert.deepEqual(seen.answer, ['229 EUR'], `${id}: the answer`);
    assert.equal(seen.verdict, order.indexOf(id) > order.indexOf('effort-demo'), `${id}: the check's verdict`);
    const wrap = slide.locator('.spine-wrap');
    assert.equal(await wrap.getAttribute('role'), 'region');
    assert.equal(await wrap.getAttribute('tabindex'), '0');
    assert.ok(await wrap.getAttribute('aria-label'), 'the scrolling wrapper is labelled');
    // The eyebrow names the same part and question as the badge.
    if (part <= 5) assert.ok(norm(await slide.locator(':scope > .eyebrow').textContent()).startsWith(norm(`Part ${part} · ${questions[part - 1]}`)),
      `${id}: the eyebrow names part ${part}`);
  }
  assert.equal(new Set(labels).size, labels.length, 'each copy describes its own slide');
});

test('D2: the close opens the five badges into five habits', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  const close = topic(page, 'wrap');
  const habits = await close.locator('svg.spine').evaluate(svg => {
    const inside = (box, el) => {
      const b = el.getBBox(), x = b.x + b.width / 2, y = b.y + b.height / 2;
      return x >= box.x && x <= box.x + box.width && y >= box.y && y <= box.y + box.height;
    };
    return [...svg.querySelectorAll('.habits .pill')].map(pill => {
      const box = pill.getBBox();
      const numbers = [...svg.querySelectorAll('.habits .bn')].filter(el => inside(box, el)).map(el => el.textContent);
      const big = [...svg.querySelectorAll('.habits .big')].find(el => inside(box, el));
      const badge = [...svg.querySelectorAll('.badge')].find(el => el.querySelector('.n').textContent === numbers[0]);
      return {
        numbers,
        habit: [...svg.querySelectorAll('.habits .habit')].filter(el => inside(box, el)).map(el => el.textContent.trim()).join(' '),
        // The pill hangs from its badge on the spine.
        fromBadge: !!big && !!badge && big.getAttribute('cx') === badge.querySelector('circle').getAttribute('cx'),
      };
    });
  });
  assert.equal(habits.length, 5, 'five habits');
  assert.deepEqual(habits.map(habit => habit.numbers.length), [1, 1, 1, 1, 1], 'each habit carries one number');
  assert.deepEqual(habits.map(habit => habit.numbers[0]).sort(), ['1', '2', '3', '4', '5']);
  for (const habit of habits) {
    assert.ok(words(habit.habit) > 0 && words(habit.habit) <= 6, `habit ${habit.numbers[0]} is a short phrase: ${habit.habit}`);
    assert.ok(habit.fromBadge, `habit ${habit.numbers[0]} opens from badge ${habit.numbers[0]}`);
  }
  // The closing headline answers the opening one.
  assert.match(norm(await topic(page, 'loop').locator('h2').textContent()), /glance/);
  assert.match(norm(await close.locator('h2').textContent()), /glance/);
});

test('D3: the running example is the effort demo’s real puzzle and recorded reply', async t => {
  const results = JSON.parse(await readFile(path.join(cursus, 'demos/effort/recorded/results.json'), 'utf8'));
  const low = results.runs.find(run => run.cli === 'claude' && run.effort === 'low');
  const { capacity, parcels, best } = await puzzle();
  assert.equal(capacity, results.puzzle.capacity);
  assert.equal(best.eur, results.puzzle.optimum, 'trying every load agrees with the recorded check');
  const page = await pageFor(t, { javaScriptEnabled: false });
  const opener = topic(page, 'loop');
  const shown = await opener.locator('table.parcels').evaluate(el => {
    const rows = [...el.querySelectorAll('tr')].map(tr => [...tr.cells].map(cell => cell.textContent.trim()));
    return rows[0].slice(1).map((name, i) => [name, Number(rows[1][i + 1]), Number(rows[2][i + 1])]);
  });
  assert.deepEqual(shown, parcels.map(p => [p.name, p.kg, p.eur]), 'the table for assistive tech holds the prompt’s parcels');
  // The parcels on the shelf: their data, and the letter and numbers drawn on each.
  const shelf = await opener.locator('[data-van-parcel]').evaluateAll(els => els.map(el => ({
    data: [el.dataset.vanParcel, Number(el.dataset.kg), Number(el.dataset.eur)],
    drawn: [el.textContent.trim()[0], ...(el.textContent.match(/\d+/g) || []).map(Number)],
  })));
  assert.deepEqual(shelf.map(parcel => parcel.data), parcels.map(p => [p.name, p.kg, p.eur]), 'the shelf holds the prompt’s parcels');
  assert.deepEqual(shelf.map(parcel => parcel.drawn), parcels.map(p => [p.name, p.kg, p.eur]), 'each parcel shows its weight and value');
  assert.equal(Number(await opener.locator('[data-van]').getAttribute('data-capacity')), capacity);
  assert.match(await face(opener), new RegExp(`\\b${capacity} kg\\b`));
  assert.doesNotMatch(await face(opener), new RegExp(`\\b${best.eur}\\b`), 'the opener does not give the answer away');
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

test('D3: the check on #effort-demo plots every load of the puzzle and labels the three that matter', async t => {
  const { capacity, loads, best, runnerUp, greedy } = await puzzle();
  assert.equal(loads.length, 256);
  const page = await pageFor(t, { javaScriptEnabled: false });
  const drawn = await topic(page, 'effort-demo').locator('svg.eff-plot').evaluate(svg => {
    const inset = svg.querySelector('.eff-inset').getBBox();
    const inInset = (x, y) => x >= inset.x && x <= inset.x + inset.width && y >= inset.y && y <= inset.y + inset.height;
    const dots = [...svg.querySelectorAll('.eff-fit circle, .eff-over circle')]
      .map(c => ({ x: c.cx.baseVal.value, y: c.cy.baseVal.value, fit: !!c.closest('.eff-fit') }))
      .filter(dot => !inInset(dot.x, dot.y));
    const subs = big => {
      const result = [];
      for (let el = big.nextElementSibling; el?.classList.contains('eff-sub'); el = el.nextElementSibling) result.push(el.textContent);
      return result.join(' ');
    };
    return {
      dots,
      limit: Number(svg.querySelector('.eff-frame .eff-limit').getAttribute('d').match(/^M([\d.]+)/)[1]),
      counts: [...svg.querySelectorAll('.eff-count')].map(el => el.textContent),
      verdict: svg.querySelector('.eff-verdict')?.textContent,
      labels: Object.fromEntries([...svg.querySelectorAll('.eff-big')].map(big => [big.textContent, subs(big)])),
    };
  });
  // Linear axes, read off the plot's own extremes: the empty load and the full one.
  const xs = drawn.dots.map(dot => dot.x), ys = drawn.dots.map(dot => dot.y);
  const x0 = Math.min(...xs), sx = (Math.max(...xs) - x0) / Math.max(...loads.map(load => load.kg));
  const y0 = Math.max(...ys), sy = (y0 - Math.min(...ys)) / Math.max(...loads.map(load => load.eur));
  const at = (kg, eur) => ({ x: x0 + kg * sx, y: y0 - eur * sy });
  // Loads with the same weight and value share one dot.
  const positions = new Map(loads.map(load => [`${load.kg},${load.eur}`, { ...at(load.kg, load.eur), fit: load.kg <= capacity }]));
  assert.equal(drawn.dots.length, positions.size, `one dot per distinct load: ${positions.size} of the 256`);
  for (const [key, expected] of positions) {
    assert.ok(drawn.dots.some(dot => Math.abs(dot.x - expected.x) < 0.15 && Math.abs(dot.y - expected.y) < 0.15 && dot.fit === expected.fit),
      `the load at ${key} is drawn, ${expected.fit ? 'filled' : 'hollow'}`);
  }
  assert.ok(Math.abs(drawn.limit - at(capacity, 0).x) < 0.15, `the limit line sits at ${capacity} kg`);
  const fitting = loads.filter(load => load.kg <= capacity).length;
  assert.deepEqual(drawn.counts.map(norm), [`● ${fitting} fit`, `○ ${loads.length - fitting} over`]);
  // The reveal settles the room's "Right this time?" bet against the check, not against a recording.
  assert.equal(norm(drawn.verdict ?? ''), `✓ right if it said ${best.eur}`);
  const label = load => norm(drawn.labels[String(load.eur)] ?? '');
  assert.match(label(best), new RegExp(`^${best.names.join(' ')} · ${best.kg} kg\\b`, 'i'), 'the best load');
  assert.match(label(runnerUp), new RegExp(`^${runnerUp.names.join(' ')} · ${runnerUp.kg} kg\\b`, 'i'), 'the load that fills the van, worse');
  assert.equal(runnerUp.kg, capacity, 'the runner-up fills the van exactly');
  assert.match(label(greedy), new RegExp(`^${greedy.names.join(' ')}\\b`, 'i'), 'the load by value per kg, in loading order');
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
  // The grey line is the best of three vote and reward-model methods, not a majority vote alone.
  const grey = norm(await topic(page, 'search').locator('.bon-name.vote').textContent());
  assert.match(grey, /vote/);
  assert.match(grey, /scoring|reward/, 'the grey line names the scoring models too');
  assert.match(await face(topic(page, 'rlvr')), /contested/);
  assert.match(await face(topic(page, 'cot-faithfulness')), /contested/);
  // Overthinking is a warning, not an average: the tasks were built to find it.
  assert.match(await face(topic(page, 'overthinking')), /built to find/);
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

test('D5: a part on the opening spine opens its slide', async t => {
  const page = await pageFor(t, { viewport: viewports[0] });
  await goTo(page, 'loop');
  await topic(page, 'loop').locator('svg.spine a[href="#search"]').click();
  await activeSlide(page, 'search');
});

test('D6: the charts draw the papers’ numbers', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  // Brown et al.: the answer key keeps climbing, the vote or scoring model barely moves. Each
  // printed number is the one its dot is placed by.
  const tracks = await topic(page, 'search').locator('.bon-track').evaluateAll(els => els.map(el => ({
    pick: el.classList.contains('key') ? 'key' : 'vote',
    at: [el.style.getPropertyValue('--a'), el.style.getPropertyValue('--b')].map(Number),
    printed: [...el.querySelectorAll('.bon-v')].map(v => v.textContent.trim()),
  })));
  assert.deepEqual(tracks, [
    { pick: 'key', at: [82.9, 98.4], printed: ['82.9%', '98.4%'] },
    { pick: 'vote', at: [40.5, 41.4], printed: ['40.5%', '41.4%'] },
  ]);
  // DeepSeek-R1-Zero on AIME 2024, before and after RL.
  const rl = await topic(page, 'rlvr').locator('.rl-bell').evaluate(el => ({
    at: [...el.querySelectorAll('.rl-dot')].map(dot => Number(dot.style.getPropertyValue('--v'))),
    printed: [...el.querySelectorAll('.rl-pt b')].map(b => b.textContent.trim()),
  }));
  assert.deepEqual(rl, { at: [15.6, 77.9], printed: ['15.6%', '77.9%'] });
  // Chen et al.: per 100 answers the hint changed, how many traces say so. Filled without JS.
  await count(topic(page, 'cot-faithfulness').locator('.cf-waffle'), 2);
  assert.deepEqual(await topic(page, 'cot-faithfulness').locator('.cf-waffle').evaluateAll(els => els.map(el => el.children.length)), [100, 100]);
  assert.deepEqual(await filled(page), [25, 39]);
  assert.deepEqual(await topic(page, 'cot-faithfulness').locator('.cf-say, .cf-v').evaluateAll(els =>
    els.filter(el => el.checkVisibility()).map(el => el.textContent.trim())), ['25', 'say so', '75', '39', 'say so', '61']);
  // Vafa et al.: Newton's law against the five laws recovered from the model's forces, all different.
  const kepler = topic(page, 'kepler');
  assert.equal(norm(await kepler.locator('.kep-newton .kep-f').textContent()), norm('F ∝ m₁m₂ / r²'));
  const recovered = (await kepler.locator('.kep-galaxies li .kep-f').allTextContents()).map(norm);
  assert.equal(recovered.length, 5, 'five galaxy samples');
  assert.equal(new Set(recovered).size, 5, 'a different law for each');
  assert.equal(recovered[0], norm('F ∝ (sin(1/sin(r − 0.24)) + 1.45) · 1/(1/r + m₂)'), 'galaxy 1, verbatim');
  assert.ok(recovered.every(law => law.startsWith('f ∝ ') && law !== norm('F ∝ m₁m₂ / r²')), 'none is Newton’s');
});

test('D6: #repo-model’s frames are the planner lab’s own runs at its defaults', { timeout: 60000 }, async t => {
  const page = await pageFor(t);
  const baked = await page.evaluate(() => {
    const parse = s => s.trim().split(/\s+/).map(p => p.split(',').map(Number));
    const circle = el => el && [el.cx.baseVal.value, el.cy.baseVal.value, el.r.baseVal.value];
    const runs = {};
    for (const svg of document.querySelectorAll('#repo-model svg[data-rm-run]')) {
      runs[svg.dataset.rmRun] = {
        scene: { obstacle: circle(svg.querySelector('.rm-obstacle')), goal: circle(svg.querySelector('.rm-goal')), start: circle(svg.querySelector('.rm-start')) },
        frames: [...svg.querySelectorAll('[data-rm-frame]')].map(g => ({
          k: Number(g.dataset.rmFrame), says: g.dataset.rmSays,
          lines: [...g.querySelectorAll('polyline[data-rm-world]')].map(line => ({ world: parse(line.dataset.rmWorld), drawn: parse(line.getAttribute('points')) })),
          predicted: parse(g.querySelector('.rm-predicted').dataset.rmWorld),
          path: parse(g.querySelector('.rm-path').dataset.rmWorld),
          hit: !!g.querySelector('.rm-x'), goal: !!g.querySelector('.rm-check'),
          obs: g.querySelectorAll('.rm-obs').length,
        })),
      };
    }
    const tile = document.querySelector('#world-models .wm3-imagined');
    return { runs, tile: tile && { world: parse(tile.dataset.world), drawn: parse(tile.getAttribute('points')) } };
  });
  await page.goto(pathToFileURL(lab).href);
  await page.waitForFunction(() => window.WorldModel);
  const ks = baked.runs.open.frames.map(f => f.k);
  // The lab's two runs, stepped in lockstep as its own view does, read at each baked step.
  const live = await page.evaluate(ks => {
    const W = window.WorldModel, cfg = W.config, c = W.createComparison(cfg.seed, cfg.error.demonstration);
    const r3 = v => Math.round(v * 1000) / 1000, pts = l => l.map(p => [r3(p[0]), r3(p[1])]);
    const frames = {};
    for (let k = 0; k <= Math.max(...ks); k++) {
      if (k) { c.open.step(); c.closed.step(); }
      if (!ks.includes(k)) continue;
      frames[k] = {};
      for (const name of ['open', 'closed']) {
        const run = c[name], rec = run.records, planId = rec.length && name === 'closed' ? rec[rec.length - 1].planId : 0;
        frames[k][name] = { path: pts([cfg.world.start].concat(rec.map(r => r.nextState))), predicted: pts(run.plans[planId].predictedPath), outcome: run.outcome };
      }
    }
    const circle = c => [c.center[0], c.center[1], c.radius];
    return { frames, seed: cfg.seed, error: cfg.error.demonstration, finalOutcomes: [c.open.outcome, c.closed.outcome],
      scene: { obstacle: circle(cfg.world.obstacle), goal: circle(cfg.world.goal), start: cfg.world.start.slice(0, 2) } };
  }, ks);
  assert.equal(live.seed, 20261011);
  assert.equal(live.error, 0.5);
  assert.deepEqual(live.finalOutcomes, ['hit obstacle', 'reached goal'], 'the lab still tells the same story at its defaults');
  // One uniform scale per picture, read off its own lines: every drawn point is its world point.
  function scale(pairs, uniform = true) {
    const fit = axis => {
      const w = pairs.map(([world]) => world[axis]), d = pairs.map(([, drawn]) => drawn[axis]);
      const s = (Math.max(...d) - Math.min(...d)) / (Math.max(...w) - Math.min(...w));
      return { s, o: Math.min(...d) - s * Math.min(...w) };
    };
    const [x, y] = [fit(0), fit(1)];
    if (uniform) assert.ok(Math.abs(x.s - y.s) < 5e-3 * x.s, 'the field is not stretched');
    return p => [x.o + x.s * p[0], y.o + y.s * p[1]];
  }
  const near = (a, b, label) => assert.ok(Math.abs(a[0] - b[0]) < 0.15 && Math.abs(a[1] - b[1]) < 0.15, `${label}: drawn ${a}, expected ${b}`);
  for (const name of ['open', 'closed']) {
    const { frames, scene } = baked.runs[name];
    const map = scale(frames.flatMap(f => f.lines.flatMap(line => line.world.map((p, i) => [p, line.drawn[i]]))));
    for (const f of frames) {
      for (const line of f.lines) {
        assert.equal(line.drawn.length, line.world.length);
        line.world.forEach((p, i) => near(line.drawn[i], map(p), `${name} step ${f.k}`));
      }
    }
    const s = map([1, 0])[0] - map([0, 0])[0];
    for (const shape of ['obstacle', 'goal']) {
      near(scene[shape], map(live.scene[shape]), `${name}: the ${shape}`);
      assert.ok(Math.abs(scene[shape][2] - live.scene[shape][2] * s) < 0.15, `${name}: the ${shape}’s size`);
    }
    near(scene.start, map(live.scene.start), `${name}: the start`);
    for (const f of frames) {
      const l = live.frames[f.k][name];
      assert.deepEqual(f.path, l.path, `${name} step ${f.k}: path`);
      assert.deepEqual(f.predicted, l.predicted, `${name} step ${f.k}: predicted path`);
      assert.equal(f.hit, l.outcome === 'hit obstacle', `${name} step ${f.k}: ✗ iff hit`);
      assert.equal(f.goal, l.outcome === 'reached goal', `${name} step ${f.k}: ✓ iff goal`);
      if (name === 'closed') assert.equal(f.obs, f.path.length - 1, `closed step ${f.k}: one observation per executed step`);
      assert.match(f.says, new RegExp(`^Step ${f.k}\\b`), `step ${f.k}: the status names the step`);
    }
  }
  // #world-models' simulator tile imagines the planner's step-0 plan.
  assert.deepEqual(baked.tile.world, live.frames[0].open.predicted, 'world-models tile 2 draws the step-0 plan');
  const map = scale(baked.tile.world.map((p, i) => [p, baked.tile.drawn[i]]), false);
  baked.tile.world.forEach((p, i) => near(baked.tile.drawn[i], map(p), 'world-models tile 2'));
});

// The slide controls. A pointer press hands focus back to the slide, so a clicker or the arrow keys
// still turn it; a key press on a focused control acts on the control and leaves the deck where it is.
async function stillTurns(page, id) {
  await page.keyboard.press('ArrowRight');
  await activeSlide(page, order[order.indexOf(id) + 1]);
  await goTo(page, id);
}
async function press(page, id, control, key = 'Space') {
  await control.focus();
  await page.keyboard.press(key);
  await activeSlide(page, id);
}
async function bigEnough(slide) {
  const small = await slide.evaluate(el => [...el.querySelectorAll('button')]
    .filter(button => !button.closest('details') && button.checkVisibility())
    .map(button => ({ name: button.textContent.trim(), ...button.getBoundingClientRect().toJSON() }))
    .filter(box => box.width < 43.5 || box.height < 43.5).map(box => `${box.name}: ${box.width}×${box.height}`));
  assert.deepEqual(small, [], 'every control is at least 44 × 44 px');
}

for (const viewport of viewports.slice(0, 2)) {
  const size = `${viewport.width}×${viewport.height}`;

  test(`D7: the van loads, sums and spills over, by pointer and keyboard, at ${size}`, async t => {
    const { capacity, weigh } = await puzzle();
    const page = await pageFor(t, { viewport });
    await goTo(page, 'loop');
    const slide = topic(page, 'loop');
    const parcel = name => slide.locator(`[data-van-parcel="${name}"]`);
    const van = () => slide.evaluate(el => {
      const shown = node => node.checkVisibility() ? node.textContent.trim() : null;
      return {
        said: el.querySelector('[data-van-readout]').textContent.replace(/\s+/g, ' ').trim(),
        free: shown(el.querySelector('[data-van-free]')),
        over: shown(el.querySelector('[data-van-over]')),
        red: el.querySelector('[data-van-bay]').hasAttribute('data-over') && el.querySelector('[data-van-readout]').classList.contains('is-over'),
        loaded: [...el.querySelectorAll('[data-van-block]')].map(block => block.dataset.vanBlock),
        pressed: [...el.querySelectorAll('[data-van-parcel][aria-pressed="true"]')].map(button => button.dataset.vanParcel),
      };
    });
    // What the van shows for a load: the readout, as seen and as announced, and the bay.
    const expect = names => {
      const { kg, eur } = weigh(names), over = kg - capacity;
      return {
        said: `${kg} kg · ${eur} EUR in the van${names.length ? `: ${names.join(', ')}; ${over > 0 ? `${over} kg over the limit` : `${-over} kg free`}` : ''}`,
        free: over <= -7 ? `${-over} kg free` : null, over: over > 0 ? `${over} kg over` : null, red: over > 0, loaded: names, pressed: [...names].sort(),
      };
    };
    assert.equal(await slide.locator('[data-van-readout]').getAttribute('role'), 'status');
    assert.deepEqual(await van(), expect([]));
    await bigEnough(slide);
    await parcel('B').click();
    await parcel('D').click();
    assert.deepEqual(await van(), expect(['B', 'D']));
    await stillTurns(page, 'loop');
    // Past the limit the load runs out of the back of the van, in red.
    await parcel('A').click();
    await parcel('H').click();
    assert.deepEqual(await van(), expect(['B', 'D', 'A', 'H']));
    assert.ok(weigh(['B', 'D', 'A', 'H']).kg > capacity);
    await parcel('H').click();
    assert.deepEqual(await van(), expect(['B', 'D', 'A']), 'pressing a loaded parcel unloads it');
    await slide.locator('[data-van-reset]').click();
    assert.deepEqual(await van(), expect([]));
    await stillTurns(page, 'loop');
    await press(page, 'loop', parcel('C'));
    assert.deepEqual(await van(), expect(['C']));
    await focused(parcel('C'));
    await press(page, 'loop', slide.locator('[data-van-reset]'), 'Enter');
    assert.deepEqual(await van(), expect([]));
  });

  test(`D7: the room's bet, then the check revealed and hidden again, at ${size}`, async t => {
    const page = await pageFor(t, { viewport });
    await goTo(page, 'effort-demo');
    const slide = topic(page, 'effort-demo');
    const rows = slide.locator('[data-eff-row]');
    const chip = (row, text) => rows.nth(row).locator('[data-eff-chip]').filter({ hasText: new RegExp(`^${text}$`) });
    const marked = () => rows.evaluateAll(els => els.map(row => [...row.querySelectorAll('[aria-pressed="true"]')].map(b => b.textContent)));
    const check = () => slide.evaluate(el => ({
      state: el.querySelector('[data-eff]').dataset.effState,
      shown: getComputedStyle(el.querySelector('.eff-data')).visibility === 'visible',
      read: el.querySelector('.eff-plot').getAttribute('aria-hidden') !== 'true' && !el.querySelector('#eff-plot-desc').hidden,
    }));
    const verdict = () => slide.locator('svg.spine').evaluate(readSpine).then(seen => seen.verdict);
    const hidden = { state: 'bet', shown: false, read: false }, revealed = { state: 'revealed', shown: true, read: true };
    // The check starts hidden from sight and from assistive tech, so the room bets first.
    await eventually(async () => assert.deepEqual(await check(), hidden));
    assert.deepEqual(await marked(), [[], [], []]);
    assert.equal(await verdict(), false, 'the spine keeps the check’s ✓ until the reveal');
    await bigEnough(slide);
    // Clicking a diagram that does not scroll leaves focus on the slide, so the deck still turns.
    await slide.locator('.spine-wrap').click();
    await stillTurns(page, 'effort-demo');
    await chip(0, '×2').click();
    await chip(0, '×5').click();
    await chip(2, 'yes').click();
    assert.deepEqual(await marked(), [['×5'], [], ['yes']], 'one chip per row');
    await chip(2, 'yes').click();
    assert.deepEqual(await marked(), [['×5'], [], []], 'pressing the marked chip again unmarks it');
    await stillTurns(page, 'effort-demo');
    // A double-click on Reveal lands its second click on the plot, which must not trap the keys.
    await slide.locator('[data-eff-reveal]').dblclick();
    await eventually(async () => assert.deepEqual(await check(), revealed));
    assert.match(norm(await slide.locator('[data-eff-status]').textContent()), /the check is shown/);
    assert.equal(await verdict(), true, 'the reveal also lights the spine’s ✓');
    await bigEnough(slide);
    await stillTurns(page, 'effort-demo');
    await slide.locator('[data-eff-reset]').click();
    await eventually(async () => assert.deepEqual(await check(), hidden));
    assert.deepEqual(await marked(), [[], [], []], 'Reset clears the bets');
    assert.equal(await verdict(), false);
    await stillTurns(page, 'effort-demo');
    await press(page, 'effort-demo', slide.locator('[data-eff-reveal]'));
    await eventually(async () => assert.deepEqual(await check(), revealed));
    await focused(slide.locator('[data-eff-reset]'));
    await press(page, 'effort-demo', slide.locator('[data-eff-reset]'));
    await eventually(async () => assert.deepEqual(await check(), hidden));
  });

  test(`D7: the waffles empty for a guess, then fill on Reveal, at ${size}`, async t => {
    const page = await pageFor(t, { viewport });
    await goTo(page, 'cot-faithfulness');
    const slide = topic(page, 'cot-faithfulness');
    const toggle = slide.locator('[data-cf-toggle]');
    await eventually(async () => assert.deepEqual(await filled(page), [0, 0]));
    assert.equal((await toggle.textContent()).trim(), 'Reveal');
    await count(slide.locator('.cf-v:visible'), 0);
    await bigEnough(slide);
    // One button reveals and resets: a double-click must not undo the reveal it just made.
    await toggle.dblclick();
    await eventually(async () => assert.deepEqual(await filled(page), [25, 39]));
    assert.equal((await toggle.textContent()).trim(), 'Reset');
    assert.match(await slide.locator('[data-cf-status]').textContent(), /\b25\b[^]*\b39\b/, 'the reveal is announced');
    await stillTurns(page, 'cot-faithfulness');
    await toggle.click();
    await eventually(async () => assert.deepEqual(await filled(page), [0, 0]));
    await stillTurns(page, 'cot-faithfulness');
    await press(page, 'cot-faithfulness', toggle);
    await eventually(async () => assert.deepEqual(await filled(page), [25, 39]));
  });

  test(`D7: "Ask it how" reveals what the model said about its sum, at ${size}`, async t => {
    const page = await pageFor(t, { viewport });
    await goTo(page, 'addition-36-59');
    const slide = topic(page, 'addition-36-59');
    const ask = slide.locator('[data-add-ask]'), reset = slide.locator('[data-add-reset]');
    const said = () => slide.evaluate(el => ({
      shown: getComputedStyle(el.querySelector('.add-quote')).visibility === 'visible',
      read: el.querySelector('[data-add-answer]').getAttribute('aria-hidden') !== 'true',
      unequal: el.querySelector('.add-neq-x').checkVisibility(),
    }));
    const before = { shown: false, read: false, unequal: false }, after = { shown: true, read: true, unequal: true };
    assert.deepEqual(await said(), before);
    assert.equal(await reset.isVisible(), false);
    await bigEnough(slide);
    // Reset replaces "Ask it how" in place: a double-click must not ask and reset at once.
    await ask.dblclick();
    assert.deepEqual(await said(), after);
    assert.match(norm(await slide.locator('[data-add-status]').textContent()), /^it said: .*carried the 1/, 'the answer is announced');
    await bigEnough(slide);
    await stillTurns(page, 'addition-36-59');
    await reset.click();
    assert.deepEqual(await said(), before);
    await stillTurns(page, 'addition-36-59');
    await press(page, 'addition-36-59', ask);
    assert.deepEqual(await said(), after);
  });

  test(`D7: Reset and Step walk the planner's frames on both runs at once, at ${size}`, async t => {
    const page = await pageFor(t, { viewport });
    await goTo(page, 'repo-model');
    const slide = topic(page, 'repo-model');
    const step = slide.locator('[data-rm-step]'), reset = slide.locator('[data-rm-reset]'), status = slide.locator('[data-rm-status]');
    const frames = await slide.locator('svg[data-rm-run="open"] [data-rm-frame]').evaluateAll(els => els.map(el => [el.dataset.rmFrame, el.dataset.rmSays]));
    assert.ok(frames.length >= 3, 'several frames to step through');
    // Both runs show frame k, and the status line says it.
    async function at(index) {
      const [k, says] = frames[index];
      assert.deepEqual(await slide.locator('svg[data-rm-run]').evaluateAll(els => els.map(svg => [...svg.querySelectorAll('[data-rm-frame]')]
        .filter(frame => getComputedStyle(frame).display !== 'none').map(frame => frame.dataset.rmFrame))), [[k], [k]], `frame ${k}`);
      assert.equal((await status.textContent()).trim(), says);
      assert.equal(await step.isDisabled(), index === frames.length - 1);
      assert.equal(await reset.isDisabled(), index === 0);
    }
    assert.equal(await status.getAttribute('aria-live'), 'polite');
    // The slide opens on the end, both outcomes drawn.
    await at(frames.length - 1);
    await bigEnough(slide);
    await reset.click();
    await at(0);
    for (let index = 1; index < frames.length; index++) {
      await step.click();
      await at(index);
    }
    await stillTurns(page, 'repo-model');
    await press(page, 'repo-model', reset);
    await at(0);
    // Printing draws the end of both runs, so the status says the last step; then the replay comes back.
    await page.evaluate(() => dispatchEvent(new Event('beforeprint')));
    await at(frames.length - 1);
    await page.evaluate(() => dispatchEvent(new Event('afterprint')));
    await at(0);
    await press(page, 'repo-model', step, 'Enter');
    await at(1);
  });
}

// What each control's slide shows with no script to run it, and on paper: the puzzle laid out, the
// check revealed, the waffles filled, both accounts of the sum, and both runs' outcomes.
async function endStates(page) {
  const van = topic(page, 'loop');
  assert.deepEqual(await van.locator('[data-van-parcel]').evaluateAll(els => els.filter(el => el.checkVisibility()).length), 8, 'the eight parcels');
  assert.equal(await van.locator('[data-van-bay]').isVisible(), true, 'the bay');
  const check = topic(page, 'effort-demo');
  assert.equal(await check.locator('.eff-data').evaluate(el => getComputedStyle(el).visibility), 'visible', 'the check, revealed');
  assert.equal(await check.locator('[data-eff-reveal]').isVisible(), false, 'nothing left to reveal');
  assert.deepEqual(await filled(page), [25, 39], 'the waffles, filled');
  const sum = topic(page, 'addition-36-59');
  assert.equal(await sum.locator('.add-quote').evaluate(el => getComputedStyle(el).visibility), 'visible', 'what it said');
  assert.equal(await sum.locator('.add-neq-x').isVisible(), true, 'the ≠ between the two accounts');
  const plan = topic(page, 'repo-model');
  const end = await plan.locator('svg[data-rm-run="open"] [data-rm-end]').getAttribute('data-rm-frame');
  assert.deepEqual(await plan.locator('svg[data-rm-run]').evaluateAll(els => els.map(svg => [...svg.querySelectorAll('[data-rm-frame]')]
    .filter(frame => getComputedStyle(frame).display !== 'none').map(frame => frame.dataset.rmFrame))), [[end], [end]], 'the last frame');
  assert.equal(await plan.locator('svg[data-rm-run="open"] [data-rm-end] .rm-x').isVisible(), true, 'plan once: ✗');
  assert.equal(await plan.locator('svg[data-rm-run="closed"] [data-rm-end] .rm-check').isVisible(), true, 'replan: ✓');
}

test('D7: without JavaScript each control’s slide shows its end state, and no slide has a slider', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  await endStates(page);
  // Controls that need a script are absent, or visibly inert, until it runs.
  for (const control of await page.locator('section[data-slide] button').all()) {
    assert.ok(!(await control.isVisible()) || await control.isDisabled(), `${await control.textContent()}: no dead control`);
  }
  // A focused slider swallows ← and →, and the deck stops turning.
  await count(page.locator('section[data-slide] :is(input[type="range"], [role="slider"])'), 0);
});

test('D7: print shows each control’s end state, whatever state the room left it in', async t => {
  const page = await pageFor(t);
  // As left after class: the check hidden, the waffles empty, the sum unasked, the planner rewound.
  await goTo(page, 'repo-model');
  await topic(page, 'repo-model').locator('[data-rm-reset]').click();
  await eventually(async () => assert.deepEqual(await filled(page), [0, 0]));
  await page.emulateMedia({ media: 'print' });
  await eventually(async () => endStates(page));
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
          if (node.closest('.visually-hidden')) continue; // clipped on purpose, for assistive tech
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

// On a phone each spine scrolls sideways to its lit parts (svg .now): all of them in view when they
// fit, else starting at the first, as the page script does.
async function highlightsInView(page) {
  for (const part of parts) {
    const wrap = topic(page, part.id).locator('.spine-wrap');
    await eventually(async () => {
      const state = await wrap.evaluate(el => {
        const frame = el.getBoundingClientRect();
        const lit = [...el.querySelectorAll('svg .now')].map(node => node.getBoundingClientRect());
        const left = Math.min(...lit.map(box => box.left)), right = Math.max(...lit.map(box => box.right));
        return {
          scrolls: el.scrollWidth > el.clientWidth,
          lit: right - left <= frame.width ? left >= frame.left - 1 && right <= frame.right + 1 : Math.abs(left - frame.left) <= 1,
        };
      });
      assert.deepEqual(state, { scrolls: true, lit: true }, `${part.id}: current part in view`);
    }, `${part.id}: current part in view`);
  }
}

test('D1: on a phone the spine scrolls sideways, starting at the current part', async t => {
  await highlightsInView(await pageFor(t, { viewport: viewports[2] }));
});

test('D1: after a wide page is narrowed, each spine scrolls to its current part', async t => {
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
