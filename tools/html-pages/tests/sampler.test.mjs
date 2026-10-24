import test from 'node:test';
import assert from 'node:assert/strict';
import { access, mkdir, readFile, realpath, stat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { chromium } from '../browser.mjs';
import { openPage, repoRoot, count, eventually, assertCollected } from './component-helpers.mjs';

// Issue 46, restructured around the one-pass pipeline: the act opens on the graph
// and walks it stage by stage, each stage with its lab. These are structural and
// behavioural floors, complemented by check-page and a person's review of the
// prose and maths. A keyword match is not a correctness review.
// npm --prefix setup test collects this suite by discovery: there is no list to edit.
const cursus = path.join(repoRoot, 'sessions/01-fundamentals/cursus');
const file = path.join(cursus, '01-sampler.html');
const artifacts = path.join(repoRoot, 'artifacts/html-pages/sampler');
const viewports = [
  { width: 1440, height: 900 },
  { width: 1280, height: 720 },
  { width: 390, height: 844 },
];
// Slide id, highlighted pipeline node(s), and the activity linked from that slide.
const stages = [
  { id: 'tokenize', nodes: ['Tokenizer'], activity: 'labs/tokenizer.html', tag: 'tokenizer lab' },
  { id: 'transformer', nodes: ['Transformer'], activity: 'labs/attention.html', tag: 'attention lab' },
  { id: 'logits', nodes: ['Logits'], activity: 'labs/next-token.html', tag: 'next-token lab' },
  { id: 'sample', nodes: ['Sampler'], activity: 'demos/model/sampling.md', tag: 'sampling demo' },
  { id: 'append', nodes: ['Next token'], activity: 'labs/tiny-lm.html', tag: 'tiny-LM lab' },
];
const graphOrder = ['Context', 'Tokenizer', 'Transformer', 'Logits', 'Sampler', 'Next token'];
const norm = value => value.normalize('NFKC').replace(/[‘’]/g, "'")
  .replace(/[−–]/g, '-').replace(/\s+/g, ' ').trim().toLowerCase();
// Quoted fixture text remains case-sensitive; normalize whitespace only.
const quoteNorm = value => value.replace(/\s+/g, ' ').trim();
const math = value => norm(value).replace(/[\s_]/g, '');
const topic = (page, id) => page.locator(`section[data-slide]#${id}`);
const slides = page => page.locator('main[data-deck] section[data-slide]');
const notes = slide => slide.locator('details.speaker-notes');
const notesText = async slide => norm(await notes(slide).evaluate(el => {
  const copy = el.cloneNode(true);
  copy.querySelector('summary')?.remove();
  return copy.textContent;
}));
// Exclude disclosures and the decorative copies of the graph from the student-facing text floor.
async function face(slide) {
  return norm(await slide.evaluate(el => {
    const copy = el.cloneNode(true);
    copy.querySelectorAll('details.speaker-notes, script, svg, [hidden], [aria-hidden="true"]').forEach(el => el.remove());
    return copy.textContent;
  }));
}
async function pageFor(t, options = {}) {
  return openPage(t, chromium, { file, ...options });
}
async function idsOf(page) {
  return slides(page).evaluateAll(els => els.map(el => el.id));
}
async function hrefsOf(locator) {
  return locator.locator('a[href]').evaluateAll(els => els.map(el => el.href));
}
const isTarget = (href, relative) => href.startsWith('file:') &&
  fileURLToPath(new URL(href).href.split('#')[0]) === path.join(cursus, relative);
async function activeSlide(page, id) {
  await eventually(async () => {
    assert.equal(decodeURIComponent(new URL(page.url()).hash.slice(1)), id);
    assert.equal(await page.locator('section[data-slide]').evaluateAll((els, id) => {
      const target = els.find(el => el.id === id);
      return !!target && target.checkVisibility();
    }, id), true, `#${id} is visible`);
    // At presentation sizes the deck shows only the selected slide. Mobile is
    // intentionally a continuous page and must not be forced into that layout.
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

test('D1 / A1 automated part: authored deck, one disclosure per slide, and a 45-minute plan', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  assert.equal(await page.locator('html').getAttribute('data-page-kind'), 'deck');
  assert.equal(await page.locator('html').getAttribute('data-design-system'), 'cursus');
  await count(page.locator('main[data-deck]'), 1);
  await count(page.locator('main[data-deck] nav[data-deck-nav]'), 1);
  await count(page.locator('script[src], script[type="module"]'), 0);
  const ids = await idsOf(page);
  assert.ok(ids.length > 1 && ids.every(Boolean), 'multiple named slides');
  assert.equal(new Set(ids).size, ids.length, 'slide ids are unique');
  await count(page.locator('section[data-slide]'), ids.length);
  await count(page.locator('details.speaker-notes'), ids.length);
  let total = 0;
  for (const slide of await slides(page).all()) {
    assert.equal(await slide.isVisible(), true, 'no-JS readers can read every slide');
    const minutes = await slide.getAttribute('data-minutes');
    assert.match(minutes ?? '', /^[1-9]\d*$/, `${await slide.getAttribute('id')}: positive integer data-minutes`);
    total += Number(minutes);
    const disclosure = notes(slide);
    await count(disclosure, 1);
    assert.equal(await disclosure.evaluate(el => el.open), false, 'notes are authored collapsed');
    await count(disclosure.locator(':scope > summary'), 1);
    assert.equal(norm(await disclosure.locator(':scope > summary').textContent()), `speaker notes · ${minutes} min`);
    assert.ok((await notesText(slide)).split(/\s+/).filter(Boolean).length >= 20,
      'notes contain a talk track and transition, not only a label');
  }
  assert.equal(total, 45, 'planned minutes total 45; this does not certify an observed rehearsal');
  assert.ok(norm(await page.locator('.masthead').innerText()).includes('session 1 · act i · 45 minutes'));
  await assertCollected('sampler');
});

test('D2: the act opens on the pipeline and walks it in order, ending on System 1', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  const ids = await idsOf(page);
  assert.equal(ids[0], 'pipeline', 'the pipeline graph opens the act');
  const order = ['tokenize', 'strawberry', 'transformer', 'logits', 'sample', 'append', 'weights'];
  const positions = order.map(id => ids.indexOf(id));
  assert.ok(positions.every(index => index > 0), `every stage slide exists: ${order}`);
  assert.deepEqual(positions, [...positions].sort((a, b) => a - b), 'stages follow the graph');
  assert.equal(ids.at(-1), 'system-1', 'the last slide closes on System 1');
});

test('D2: the opening graph names every stage, links each stage slide, and carries the board equation', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  const slide = topic(page, 'pipeline');
  const graph = slide.locator('svg.pipeline');
  await count(graph, 1);
  assert.deepEqual(await graph.locator('.node .t').allTextContents(), graphOrder);
  await count(graph.locator('.node.now'), 0);
  const links = await graph.locator('a').evaluateAll(els => els.map(el => el.getAttribute('href')));
  assert.deepEqual(links, stages.map(stage => `#${stage.id}`), 'each stage box opens its slide');
  assert.match(norm(await graph.textContent()), /one forward pass/);
  assert.match(norm(await graph.textContent()), /append/);
  const text = await face(slide);
  assert.ok(math(text).includes('p(xt|x<t)'), 'conditional with the whole preceding context');
  assert.match(text, /gpt-2/);
  const talk = await notesText(slide);
  assert.match(talk, /board/);
  assert.match(talk, /writ|put|draw/);
  assert.match(talk, /chain[ -]rule|factoriz|factoris/);
});

test('D2: each stage slide repeats the graph with its own stage highlighted and its activity named', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  const close = { id: 'system-1', nodes: ['Transformer', 'Logits'] };
  for (const stage of [...stages, close]) {
    const slide = topic(page, stage.id);
    const graph = slide.locator('svg.pipeline');
    await count(graph, 1);
    assert.deepEqual(await graph.locator('.node .t').allTextContents(), graphOrder, `${stage.id}: same graph`);
    assert.deepEqual(await graph.locator('.node.now .t').allTextContents(), stage.nodes, `${stage.id}: highlighted stage`);
    assert.equal(await graph.getAttribute('role'), 'img');
    assert.match(norm(await graph.getAttribute('aria-label')), /highlighted/);
    if (!stage.activity) continue;
    // Earlier stages read as done, later ones as still to come.
    const at = graphOrder.indexOf(stage.nodes[0]);
    const states = await graph.locator('.node').evaluateAll(els => els.map(el =>
      ['done', 'now', 'next'].find(name => el.classList.contains(name))));
    assert.deepEqual(states, graphOrder.map((_, index) => index < at ? 'done' : index === at ? 'now' : 'next'));
    assert.ok((await graph.locator('.tag.now').allTextContents()).some(text => text.includes(stage.tag)),
      `${stage.id}: the highlighted label names ${stage.tag}`);
    assert.ok((await hrefsOf(slide.locator(':scope > :not(details)'))).some(href => isTarget(href, stage.activity)),
      `${stage.id}: the slide links ${stage.activity}`);
  }
});

test('D3: real integer token IDs and a strawberry-to-code demo slot', async t => {
  const fixture = JSON.parse(await readFile(path.join(cursus, 'fixtures/next_token.json'), 'utf8'));
  const strawberry = fixture.prompts.find(item => item.prompt === ' strawberry');
  const france = fixture.prompts.find(item => item.prompt === 'The capital of France is');
  assert.ok(strawberry?.prompt_tokens.length && france?.prompt_tokens.length, 'fixture holds both prompts');
  const page = await pageFor(t, { javaScriptEnabled: false });
  const tokenText = await face(topic(page, 'tokenize'));
  for (const term of [/integer/, /\bids?\b/, /strawberry/, /gpt-2/]) assert.match(tokenText, term);
  for (const token of strawberry.prompt_tokens) assert.match(tokenText, new RegExp(`\\b${token.id}\\b`),
    'token ID comes from prompt_tokens, not from a next-token candidate');
  assert.ok(tokenText.includes(france.prompt_tokens.map(token => token.id).join(' ')),
    'the running example shows its recorded IDs in order');
  const demo = topic(page, 'strawberry');
  const text = await face(demo);
  assert.match(text, /strawberry/);
  assert.match(text, /code/);
  const slots = await demo.locator('a[href], code').evaluateAll(els => els.map(el =>
    el.tagName === 'A' ? el.getAttribute('href') : el.textContent));
  assert.ok(slots.some(value => value.includes('demos/model/strawberry.md')), 'runbook link or code-path slot');
  await access(path.join(cursus, 'demos/model/strawberry.md'));
});

test('D4: a recorded distribution, temperature, sampling, reproducibility and the System 1 close', async t => {
  const fixture = JSON.parse(await readFile(path.join(cursus, 'fixtures/next_token.json'), 'utf8'));
  const france = fixture.prompts.find(item => item.prompt === 'The capital of France is');
  const page = await pageFor(t, { javaScriptEnabled: false });
  const logits = topic(page, 'logits');
  const text = await face(logits);
  for (const term of [/distribution/, /softmax/, /temperature/]) assert.match(text, term);
  assert.ok(math(text).includes('softmax(z/t)'), 'temperature formula is readable HTML');
  const rows = await logits.locator('[data-prob-row]').evaluateAll(els => els.map(el => ({
    label: el.querySelector('[data-prob-label]').textContent, value: Number(el.dataset.value) })));
  assert.equal(rows.length, 5);
  for (const [index, row] of rows.entries()) {
    const top = france.top[index];
    assert.equal(row.label.replace(/\s*\(highlighted\)\s*$/, '').trim(), top.text.replace(/^ /, '␣'));
    assert.ok(Math.abs(row.value - Math.exp(top.logit - france.logsumexp)) < 5e-4, `${top.text}: recorded probability`);
  }
  const sample = await face(topic(page, 'sample'));
  for (const term of [/draw/, /reproduc/, /seed/]) assert.match(sample, term);
  const close = topic(page, 'system-1');
  const closeText = await face(close);
  assert.match(closeText, /system 1/);
  assert.match(closeText, /fixed compute per token/);
  assert.ok((await close.locator('.cite a[href]').evaluateAll(els => els.map(el => el.href)))
    .some(url => url.startsWith('https://transformer-circuits.pub/2025/attribution-graphs/biology')),
  'the in-pass reasoning qualification is sourced');
});

test('D5: attention on the transformer stage, with query, key and value', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  const text = await face(topic(page, 'transformer'));
  for (const term of [/attention/, /query/, /key/, /value/, /softmax/, /look/]) assert.match(text, term);
  assert.ok(math(text).includes('softmax(qkt/√d)·v'), 'scaled attention formula is readable HTML');
});

// A quotation can use semantic quote elements, literal quotation marks, or
// labelled prose/table cells. No extra page-specific data attributes are needed.
function stripQuoteLabel(value) {
  return quoteNorm(value)
    .replace(/^(?:(?:base(?: model)?|instruct(?: model)?|assistant|recorded|answer|continuation|excerpt)\b[\s·:()\-–—]*)+/i, '')
    .replace(/\s*\(?excerpt\)?\s*$/i, '')
    .replace(/^[“"«]|[”"»]$/g, '').trim();
}
function validateQuotes(candidates, item) {
  const sources = [item.base.text, item.instruct.text, item.prompt].map(quoteNorm);
  const excerpts = candidates.map(stripQuoteLabel).filter(Boolean);
  assert.ok(excerpts.length >= 2, 'the factual comparison displays two model continuations');
  for (const excerpt of excerpts) assert.ok(sources.some(source => source.includes(excerpt)),
    `displayed quotation is a contiguous fixture substring: ${excerpt}`);
  assert.ok(excerpts.some(text => quoteNorm(item.instruct.text).includes(text)), 'an instruct excerpt');
  const falsehood = item.base.text.match(/New Zealand is [^\n]*?\bworld\b/)?.[0];
  assert.ok(falsehood, 'factual fixture contains the fluent falsehood discussed in the design');
  assert.ok(excerpts.some(text => quoteNorm(item.base.text).includes(text) && text.includes(falsehood)),
    'the base excerpt preserves the fixture line about New Zealand');
}

test('D6: base versus assistant from the static fixture, with recorded decoding provenance', async t => {
  const fixture = JSON.parse(await readFile(path.join(cursus, 'fixtures/base_vs_instruct.json'), 'utf8'));
  const item = fixture.items.find(item => item.id === 'factual');
  assert.ok(item, 'factual comparison is available');
  const page = await pageFor(t, { javaScriptEnabled: false });
  const weights = topic(page, 'weights');
  const text = await face(weights);
  for (const term of [/pretraining/, /post-training/, /base/, /assistant/, /excerpt/, /fluent/]) assert.match(text, term);
  const comparison = weights.locator('[data-fixture-id="factual"]');
  await count(page.locator('[data-fixture-id]'), 1);
  await count(comparison, 1);
  assert.equal(await comparison.isVisible(), true, 'fixture quotations are authored HTML, readable without JS');
  const displayed = quoteNorm(await comparison.innerText());
  assert.ok(displayed.includes(quoteNorm(item.prompt)), 'shared question is item.prompt');
  assert.ok(!displayed.includes('<|im_start|>'), 'do not expose the chat-templated instruct.input as the question');
  const quotes = await comparison.evaluate(el => [...el.querySelectorAll('blockquote')].map(node => {
    const copy = node.cloneNode(true);
    copy.querySelectorAll('p').forEach(p => p.after(document.createTextNode('\n')));
    return copy.textContent;
  }));
  validateQuotes(quotes.filter(quote => quoteNorm(quote) !== quoteNorm(item.prompt)), item);
  const citation = quoteNorm((await weights.locator('.cite').allTextContents()).join(' '));
  for (const model of fixture.meta.models) {
    assert.ok(citation.includes(model.id), 'citation names the model');
    assert.ok(citation.includes(model.revision), 'citation names the full pinned revision');
  }
  assert.ok(citation.includes(fixture.meta.date), 'citation names the recording date');
  assert.match(citation, /greedy/i);
  assert.match(citation, new RegExp(`\\b${fixture.max_new_tokens}\\b`));
  assert.match(citation, /(?:max|up to)[\s\S]*new tokens|new tokens[\s\S]*(?:max|limit)/i);
  // Pretraining, RLVR and the cutoff are spoken, with their sources in the notes.
  const talk = await notesText(weights);
  for (const term of [/base model/, /cutoff/, /hallucination/, /verifiable reward/]) assert.match(talk, term);
  const sources = await notes(weights).locator('a[href]').evaluateAll(els => els.map(el => el.href));
  for (const id of ['2309.10668', '2411.15124', '2501.12948']) {
    assert.ok(sources.some(url => url.includes(`arxiv.org/abs/${id}`)), `notes cite arXiv ${id}`);
  }
  assert.ok((await page.locator('details.speaker-notes a[href]').evaluateAll(els => els.map(el => el.href)))
    .some(url => /(?:youtube\.com\/watch\?[^#]*v=7xTGNNLPyMI|youtu\.be\/7xTGNNLPyMI)/.test(url)),
  'Karpathy reference is in the speaker notes');
});

test('D6 oracle rejects a fluent alteration and a splice, rather than just a model label', async () => {
  const fixture = JSON.parse(await readFile(path.join(cursus, 'fixtures/base_vs_instruct.json'), 'utf8'));
  const item = fixture.items.find(item => item.id === 'factual');
  validateQuotes([item.base.text, item.instruct.text], item);
  // The same fixture-derived checker must reject plausible but unrecorded text.
  assert.throws(() => validateQuotes([item.base.text, `${item.instruct.text} Certainly.`], item));
  const pieces = item.base.text.trim().split(/\n\n+/);
  assert.ok(pieces.length > 2);
  assert.throws(() => validateQuotes([`${pieces[0]} ${pieces.at(-1)}`, item.instruct.text], item));
});

async function localLinks(page) {
  const links = [];
  const root = await realpath(cursus);
  for (const link of await page.locator('a[href]').all()) {
    const href = await link.getAttribute('href');
    assert.ok(!/(?:^|\/)(?:test-time-compute|world-model)\.html(?:[?#]|$)/.test(href),
      'Act II widgets belong in Act II');
    if (/^https?:/i.test(href)) continue; // citations are links, never runtime dependencies
    if (href.startsWith('#')) {
      await count(page.locator(`[id="${decodeURIComponent(href.slice(1))}"]`), 1);
      continue;
    }
    assert.ok(!/^(?:[a-z][a-z\d+.-]*:|\/)/i.test(href), `local link must be relative: ${href}`);
    const url = new URL(href, pathToFileURL(file));
    assert.equal(url.protocol, 'file:');
    const target = await realpath(fileURLToPath(url));
    const relative = path.relative(root, target);
    assert.ok(relative !== '..' && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative),
      `local target stays in cursus: ${href}`);
    assert.equal((await stat(target)).isFile(), true, `local target exists: ${href}`);
    if (url.hash) {
      const fragment = decodeURIComponent(url.hash.slice(1));
      const source = await readFile(target, 'utf8');
      // Parse with the same browser, inertly: do not run a linked page just to
      // inspect an anchor and do not assume ids use a particular quote style.
      assert.equal(await page.evaluate(({ source, fragment }) =>
        !!new DOMParser().parseFromString(source, 'text/html').getElementById(fragment), { source, fragment }), true,
      `fragment exists: ${href}`);
    }
    links.push({ href, target, ...await link.evaluate(el => ({
      slide: el.closest('section[data-slide]')?.id ?? null,
      inNotes: !!el.closest('details.speaker-notes'),
    })) });
  }
  return links;
}

test('D8: relative links resolve and each lab is linked from its own stage', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  const links = await localLinks(page);
  for (const stage of stages) {
    const matching = links.filter(link => !link.inNotes && link.target === path.join(cursus, stage.activity));
    assert.ok(matching.some(link => link.slide === stage.id), `${stage.activity} is linked from #${stage.id}`);
  }
});

test('D8: all four file:// labs load offline and Back restores their originating slides', { timeout: 120000 }, async t => {
  const page = await pageFor(t);
  const links = await localLinks(page);
  for (const stage of stages.filter(stage => stage.activity.startsWith('labs/'))) {
    const destination = path.join(cursus, stage.activity);
    const link = links.find(link => !link.inNotes && link.target === destination && link.slide === stage.id);
    assert.ok(link, `${stage.activity} has a slide-local activity link`);
    await goTo(page, link.slide);
    const anchor = topic(page, link.slide).locator(`a[href=${JSON.stringify(link.href)}]`).first();
    // A normal same-tab link is required to exercise the deck's history contract.
    assert.ok(['', null, '_self'].includes(await anchor.getAttribute('target')), 'activity can return with browser Back');
    await Promise.all([
      page.waitForURL(url => url.protocol === 'file:' && fileURLToPath(url) === destination),
      anchor.click(),
    ]);
    assert.equal(await page.locator('html').getAttribute('data-page-kind'), 'lab');
    assert.equal(await page.locator('body').isVisible(), true);
    assert.ok((await page.locator('body').innerText()).trim().length > 0, 'lab is readable offline');
    await page.goBack();
    await activeSlide(page, link.slide);
  }
});

test('D8: a stage box on the opening graph opens its slide', async t => {
  const page = await pageFor(t, { viewport: viewports[0] });
  await goTo(page, 'pipeline');
  await topic(page, 'pipeline').locator('svg.pipeline a[href="#logits"]').click();
  await activeSlide(page, 'logits');
});

for (const viewport of viewports) {
  test(`D1: every disclosure works by keyboard at ${viewport.width}×${viewport.height}, including long notes`, { timeout: 120000 }, async t => {
    const page = await pageFor(t, { viewport });
    const ids = await idsOf(page);
    await mkdir(artifacts, { recursive: true });
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
      if (index === 1 || id === 'logits' || id === 'weights') {
        await page.screenshot({ path: path.join(artifacts, `notes-${viewport.width}-${index + 1}.png`), fullPage: true });
      }
      await page.keyboard.press(key);
      await eventually(async () => assert.equal(await disclosure.evaluate(el => el.open), false));
      await activeSlide(page, id);
    }
    // A second, nontrivial state: extend actual notes in memory. No fixture,
    // runtime file or implementation script is altered. The disclosure must
    // contain long notes in its own scroll area rather than clip the talk track.
    await goTo(page, 'logits');
    const disclosure = notes(topic(page, 'logits'));
    await disclosure.locator(':scope > summary').focus();
    await page.keyboard.press('Enter');
    await disclosure.evaluate(el => {
      const leaves = [...el.querySelectorAll('p, li, dd, div')].filter(node =>
        !node.closest('summary') && !node.querySelector('p, li, dd, div') && node.textContent.trim().split(/\s+/).length >= 4);
      const last = leaves.at(-1);
      const parent = last?.parentElement ?? el;
      for (let i = 0; i < 80; i++) {
        const copy = document.createElement('p');
        copy.textContent = last?.textContent ?? 'Read the model distribution, predict the next token, then discuss the sampling outcome with the class.';
        parent.append(copy);
      }
    });
    await noHorizontalOverflow(page, disclosure);
    const scrolling = await disclosure.evaluate(el => {
      const candidates = [el, ...el.querySelectorAll('*')].filter(node => {
        const css = getComputedStyle(node);
        return node.clientHeight > 0 && node.scrollHeight > node.clientHeight + 1 && /auto|scroll/.test(css.overflowY);
      });
      return candidates.some(node => {
        node.scrollTop = node.scrollHeight;
        return node.scrollTop > 0 && node.scrollTop + node.clientHeight >= node.scrollHeight - 2;
      });
    });
    assert.ok(scrolling, 'long notes scroll to their end inside the details element');
  });
}

test('D1: on a phone the graph scrolls sideways, starting at the current stage', async t => {
  const page = await pageFor(t, { viewport: viewports[2] });
  for (const stage of stages) {
    const wrap = topic(page, stage.id).locator('.pipeline-wrap');
    const state = await wrap.evaluate(el => {
      const now = el.querySelector('.node.now').getBoundingClientRect();
      const frame = el.getBoundingClientRect();
      return { scrolls: el.scrollWidth > el.clientWidth, visible: now.left >= frame.left - 1 && now.right <= frame.right + 1 };
    });
    assert.deepEqual(state, { scrolls: true, visible: true }, `${stage.id}: current stage in view`);
  }
});

test('D1: print reveals all talk tracks without scroll clipping', async t => {
  const page = await pageFor(t);
  await page.emulateMedia({ media: 'print' });
  await eventually(async () => {
    for (const slide of await slides(page).all()) {
      assert.equal(await slide.isVisible(), true, 'all slides print');
      const disclosure = notes(slide);
      const result = await disclosure.evaluate(el => {
        const children = [...el.children].filter(node => node.tagName !== 'SUMMARY');
        const readable = children.length ? children.every(node => node.checkVisibility()) : el.open;
        const clipped = [el, ...el.querySelectorAll('*')].some(node => node.clientHeight > 0 &&
          node.scrollHeight > node.clientHeight + 1 && /auto|scroll|hidden|clip/.test(getComputedStyle(node).overflowY));
        return { readable, clipped };
      });
      assert.deepEqual(result, { readable: true, clipped: false }, 'print contains the full note body');
    }
  });
  await mkdir(artifacts, { recursive: true });
  await page.screenshot({ path: path.join(artifacts, 'print.png'), fullPage: true });
});
