import test from 'node:test';
import assert from 'node:assert/strict';
import { access, mkdir, readFile, realpath, stat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { chromium } from '../browser.mjs';
import { openPage, repoRoot, count, eventually, assertCollected } from './component-helpers.mjs';

// Issue 46, restructured around the one-pass pipeline: the act opens on the graph
// and walks it stage by stage, each stage with the data structure it passes on and
// its lab. These are structural and behavioural floors, complemented by check-page
// and a person's review of the prose and maths. A keyword match is not a correctness review.
// npm --prefix setup test collects this suite by discovery: there is no list to edit.
const cursus = path.join(repoRoot, 'sessions/01-fundamentals/cursus');
const file = path.join(cursus, '01-sampler.html');
const artifacts = path.join(repoRoot, 'artifacts/html-pages/sampler');
const viewports = [
  { width: 1440, height: 900 },
  { width: 1280, height: 720 },
  { width: 390, height: 844 },
];
const order = ['pipeline', 'tokenize', 'strawberry', 'embed', 'transformer', 'attention', 'logits', 'sample', 'append', 'weights', 'system-1'];
// Slide id, highlighted pipeline node(s), and the activity linked from that slide, if any.
const stages = [
  { id: 'tokenize', nodes: ['Tokenizer'], activity: 'labs/tokenizer.html', tag: 'tokenizer lab' },
  { id: 'embed', nodes: ['Embedding'] },
  { id: 'transformer', nodes: ['12 layers'], tag: 'attention lab' },
  { id: 'attention', nodes: ['12 layers'], activity: 'labs/attention.html', tag: 'attention lab' },
  { id: 'logits', nodes: ['Logits'], activity: 'labs/next-token.html', tag: 'next-token lab' },
  { id: 'sample', nodes: ['Sampler'], activity: 'demos/model/sampling.md', tag: 'sampling demo' },
  { id: 'append', nodes: ['Next token'], activity: 'labs/tiny-lm.html', tag: 'tiny-LM lab' },
];
const graphOrder = ['Context', 'Tokenizer', 'Embedding', '12 layers', 'Logits', 'Sampler', 'Next token'];
const norm = value => value.normalize('NFKC').replace(/[‘’]/g, "'")
  .replace(/[−–]/g, '-').replace(/\s+/g, ' ').trim().toLowerCase();
// Quoted fixture text remains case-sensitive; normalize whitespace only.
const quoteNorm = value => value.replace(/\s+/g, ' ').trim();
const math = value => norm(value).replace(/[\s_]/g, '');
const piece = text => text.replace(/ /g, '␣');
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
async function running() {
  const fixture = JSON.parse(await readFile(path.join(cursus, 'fixtures/next_token.json'), 'utf8'));
  const item = fixture.prompts.find(prompt => prompt.id === 'factual-everyone-knows');
  assert.ok(item, 'the running example is the factual-everyone-knows prompt');
  return { fixture, item, p: record => Math.exp(record.logit - item.logsumexp) };
}
async function chips(locator) {
  return locator.locator('[data-token-id]').evaluateAll(els => els.map(el => ({
    id: Number(el.dataset.tokenId), text: el.querySelector('code').textContent, shown: el.querySelector('.id').textContent })));
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
    assert.ok((await notesText(slide)).split(/\s+/).filter(Boolean).length >= 20,
      'notes contain a talk track and transition, not only a label');
  }
  // Timing lives in the run of show, not in the deck.
  await count(page.locator('[data-minutes]'), 0);
  const text = await page.locator('body').evaluate(el => el.textContent);
  assert.doesNotMatch(text, /\bminutes?\b|\b\d+\s?min\b/i, 'no minutes on slides or in notes');
  assert.match(norm(await page.locator('.masthead').innerText()), /act i/);
  await assertCollected('sampler');
});

test('D1: slide faces carry no recording artefacts', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  await count(page.locator('footer'), 0);
  for (const slide of await slides(page).all()) {
    assert.doesNotMatch(await face(slide), /\brecorded\b|fixtures\/|\.json\b/, `#${await slide.getAttribute('id')}: no provenance on the face`);
  }
  // The one source left on a face is the research behind the System 1 qualification.
  assert.deepEqual(await page.locator('main .cite').evaluateAll(els => els.map(el => el.closest('section').id)), ['system-1']);
});

test('D2: the act opens on the pipeline and walks it in order, ending on System 1', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  assert.deepEqual(await idsOf(page), order);
});

test('D2: the opening graph names every stage and its output shape, and links each stage slide', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  const slide = topic(page, 'pipeline');
  const graph = slide.locator('svg.pipeline');
  await count(graph, 1);
  assert.deepEqual(await graph.locator('.node .t').allTextContents(), graphOrder);
  const shapes = await graph.locator('.node .s').allTextContents();
  for (const shape of ['7 IDs', '7 × 768', '50,257 scores', '1 ID']) {
    assert.ok(shapes.some(text => text.includes(shape)), `a node shows its output: ${shape}`);
  }
  await count(graph.locator('.node.now'), 0);
  const links = await graph.locator('a').evaluateAll(els => els.map(el => el.getAttribute('href')));
  assert.deepEqual(links, ['#tokenize', '#embed', '#transformer', '#logits', '#sample', '#append'], 'each stage box opens its slide');
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

test('D2: each stage slide repeats the same graph with its own stage highlighted', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  const geometry = el => [...el.querySelectorAll('rect, path')].map(node => node.getAttribute('x') + node.getAttribute('d'));
  const reference = await topic(page, 'pipeline').locator('svg.pipeline').evaluate(geometry);
  const close = { id: 'system-1', nodes: ['Embedding', '12 layers', 'Logits'] };
  for (const stage of [...stages, close]) {
    const slide = topic(page, stage.id);
    const graph = slide.locator('svg.pipeline');
    await count(graph, 1);
    assert.deepEqual(await graph.evaluate(geometry), reference, `${stage.id}: the copy has the same geometry`);
    assert.deepEqual(await graph.locator('.node .t').allTextContents(), graphOrder, `${stage.id}: same graph`);
    assert.deepEqual(await graph.locator('.node.now .t').allTextContents(), stage.nodes, `${stage.id}: highlighted stage`);
    assert.equal(await graph.getAttribute('role'), 'img');
    assert.match(norm(await graph.getAttribute('aria-label')), /highlighted/);
    if (stage === close) continue;
    // Earlier stages read as done, later ones as still to come.
    const at = graphOrder.indexOf(stage.nodes[0]);
    const states = await graph.locator('.node').evaluateAll(els => els.map(el =>
      ['done', 'now', 'next'].find(name => el.classList.contains(name))));
    assert.deepEqual(states, graphOrder.map((_, index) => index < at ? 'done' : index === at ? 'now' : 'next'));
    if (stage.tag) {
      assert.ok((await graph.locator('.tag.now').allTextContents()).some(text => text.includes(stage.tag)),
        `${stage.id}: the highlighted label names ${stage.tag}`);
    }
    if (stage.activity) {
      assert.ok((await hrefsOf(slide.locator(':scope > :not(details)'))).some(href => isTarget(href, stage.activity)),
        `${stage.id}: the slide links ${stage.activity}`);
    }
  }
});

test('D3: the tokenizer shows the running example as its recorded list of integers', async t => {
  const { item } = await running();
  const page = await pageFor(t, { javaScriptEnabled: false });
  const slide = topic(page, 'tokenize');
  const expected = item.prompt_tokens.map(token => ({ id: token.id, text: piece(token.text), shown: String(token.id) }));
  assert.deepEqual(await chips(slide), expected);
  const text = await face(slide);
  for (const term of [/integer/, /\bids?\b/, /gpt-2/, /leading space/]) assert.match(text, term);
  assert.match(text, new RegExp(`\\b${item.prompt_tokens.length} integers\\b`));
});

test('D3: strawberry is one ID, and the demo slot pivots to code', async t => {
  const { fixture } = await running();
  const strawberry = fixture.prompts.find(item => item.prompt === ' strawberry');
  assert.equal(strawberry?.prompt_tokens.length, 1, 'fixture holds the real leading-space strawberry prompt');
  const page = await pageFor(t, { javaScriptEnabled: false });
  const demo = topic(page, 'strawberry');
  const text = await face(demo);
  assert.match(text, /strawberry/);
  assert.match(text, new RegExp(`\\b${strawberry.prompt_tokens[0].id}\\b`), 'the ID comes from prompt_tokens');
  assert.match(text, /code/);
  assert.ok((await demo.locator('a[href]').evaluateAll(els => els.map(el => el.getAttribute('href'))))
    .includes('demos/model/strawberry.md'), 'runbook link');
  await access(path.join(cursus, 'demos/model/strawberry.md'));
  assert.match(await notesText(demo), /146/);
});

test('D4: embedding and layers keep a 7 × 768 matrix, one row per token, in order', async t => {
  const { item } = await running();
  const page = await pageFor(t, { javaScriptEnabled: false });
  const embed = topic(page, 'embed');
  const rows = await embed.locator('.matrix').evaluate(el => [...el.querySelectorAll('.id')].map(node => Number(node.textContent)));
  assert.deepEqual(rows, item.prompt_tokens.map(token => token.id), 'one row per recorded ID');
  await count(embed.locator('.matrix .row'), item.prompt_tokens.length);
  const embedText = await face(embed);
  for (const term of [/7 × 768/, /768 numbers/, /position/]) assert.match(embedText, term);
  assert.match(await notesText(embed), /50,257 × 768/);
  const layers = await face(topic(page, 'transformer'));
  for (const term of [/layer 1\b/, /layer 12\b/, /7 × 768/, /attention/, /mlp/, /in order/]) assert.match(layers, term);
});

test('D5: inside a layer, one head is a causal 7 × 7 table of query, key and value', async t => {
  const { item } = await running();
  const n = item.prompt_tokens.length;
  const page = await pageFor(t, { javaScriptEnabled: false });
  const slide = topic(page, 'attention');
  const grid = slide.locator('.attn-grid');
  await count(grid.locator('.c'), n * n);
  await count(grid.locator('.c.off'), n * (n - 1) / 2);
  const masked = await grid.evaluate((el, n) => [...el.querySelectorAll('.c')].map((cell, index) =>
    cell.classList.contains('off') === (index % n > Math.floor(index / n))), n);
  assert.ok(masked.every(Boolean), 'exactly the cells above the diagonal are empty');
  const text = await face(slide);
  for (const term of [/attention/, /look/, /query/, /key/, /value/, /softmax/, /7 × 7/, /12 heads/]) assert.match(text, term);
  assert.ok(math(text).includes('softmax(qkt/√d)·v'), 'scaled attention formula is readable HTML');
  assert.match(await notesText(slide), /13-token/, 'the notes tie the table to the lab’s GPT-2 panel');
});

test('D6: the last row becomes the recorded distribution, and one draw is appended', async t => {
  const { item, p } = await running();
  const page = await pageFor(t, { javaScriptEnabled: false });
  const logits = topic(page, 'logits');
  const text = await face(logits);
  for (const term of [/distribution/, /softmax/, /temperature/, /768/, /50,257/]) assert.match(text, term);
  assert.ok(math(text).includes('softmax(z/t)'), 'temperature formula is readable HTML');
  const rows = await logits.locator('[data-prob-row]').evaluateAll(els => els.map(el => ({
    label: el.querySelector('[data-prob-label] code').textContent, value: Number(el.dataset.value),
    highlight: el.hasAttribute('data-highlight') })));
  assert.equal(rows.length, 5);
  for (const [index, row] of rows.entries()) {
    const top = item.top[index];
    assert.equal(row.label, piece(top.text));
    assert.ok(Math.abs(row.value - p(top)) < 5e-4, `${top.text}: recorded probability`);
    assert.equal(row.highlight, index === 0, 'the top token is the highlighted one');
  }
  assert.equal(item.top[0].text, item.expect, 'the expected answer is the most likely next token');
  const drawn = { id: item.top[0].id, text: piece(item.top[0].text), shown: String(item.top[0].id) };
  const sample = topic(page, 'sample');
  assert.deepEqual(await chips(sample), [drawn]);
  assert.match(await face(sample), /draw/);
  const append = topic(page, 'append');
  const expected = item.prompt_tokens.map(token => ({ id: token.id, text: piece(token.text), shown: String(token.id) }));
  assert.deepEqual(await chips(append), [...expected, drawn]);
  assert.match(await face(append), new RegExp(`\\b${item.prompt_tokens.length + 1} ids\\b`));
});

test('D6: the sampler notes keep reproducibility and the dated CLI claim with its sources', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  const slide = topic(page, 'sample');
  const talk = await notesText(slide);
  for (const term of [/seed/, /reproduc/, /as of 2026-10-18/, /neither cli exposes a temperature, top-p or seed option/]) assert.match(talk, term);
  const links = await notes(slide).locator('a[href]').evaluateAll(els => els.map(el => el.href));
  for (const url of ['https://code.claude.com/docs/en/cli-reference', 'https://developers.openai.com/codex/cli/reference']) {
    assert.ok(links.includes(url), `notes cite ${url}`);
  }
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

test('D7: base versus assistant from the static fixture, with its sources in the notes', async t => {
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
  // Pretraining, RLVR, decoding and the cutoff are spoken, with their sources in the notes.
  const talk = await notesText(weights);
  for (const term of [/base model/, /cutoff/, /hallucination/, /verifiable reward/, /greedy/, new RegExp(`\\b${fixture.max_new_tokens}\\b`)]) {
    assert.match(talk, term);
  }
  for (const model of fixture.meta.models) assert.ok(talk.includes(model.id.split('/')[1].toLowerCase().replace('-instruct', '')), `notes name ${model.id}`);
  const sources = await notes(weights).locator('a[href]').evaluateAll(els => els.map(el => el.href));
  for (const id of ['2309.10668', '2411.15124', '2501.12948']) {
    assert.ok(sources.some(url => url.includes(`arxiv.org/abs/${id}`)), `notes cite arXiv ${id}`);
  }
  assert.ok((await page.locator('details.speaker-notes a[href]').evaluateAll(els => els.map(el => el.href)))
    .some(url => /(?:youtube\.com\/watch\?[^#]*v=7xTGNNLPyMI|youtu\.be\/7xTGNNLPyMI)/.test(url)),
  'Karpathy reference is in the speaker notes');
});

test('D7 oracle rejects a fluent alteration and a splice, rather than just a model label', async () => {
  const fixture = JSON.parse(await readFile(path.join(cursus, 'fixtures/base_vs_instruct.json'), 'utf8'));
  const item = fixture.items.find(item => item.id === 'factual');
  validateQuotes([item.base.text, item.instruct.text], item);
  // The same fixture-derived checker must reject plausible but unrecorded text.
  assert.throws(() => validateQuotes([item.base.text, `${item.instruct.text} Certainly.`], item));
  const pieces = item.base.text.trim().split(/\n\n+/);
  assert.ok(pieces.length > 2);
  assert.throws(() => validateQuotes([`${pieces[0]} ${pieces.at(-1)}`, item.instruct.text], item));
});

test('D7: the close names System 1, its fixed compute, and the source of its qualification', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  const close = topic(page, 'system-1');
  const text = await face(close);
  assert.match(text, /system 1/);
  assert.match(text, /fixed compute per token/);
  assert.ok((await close.locator('.cite a[href]').evaluateAll(els => els.map(el => el.href)))
    .some(url => url.startsWith('https://transformer-circuits.pub/2025/attribution-graphs/biology')),
  'the in-pass reasoning qualification is sourced');
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
  for (const stage of stages.filter(stage => stage.activity)) {
    const matching = links.filter(link => !link.inNotes && link.target === path.join(cursus, stage.activity));
    assert.ok(matching.some(link => link.slide === stage.id), `${stage.activity} is linked from #${stage.id}`);
  }
});

test('D8: all four file:// labs load offline and Back restores their originating slides', { timeout: 120000 }, async t => {
  const page = await pageFor(t);
  const links = await localLinks(page);
  for (const stage of stages.filter(stage => stage.activity?.startsWith('labs/'))) {
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

async function currentStagesInView(page) {
  for (const stage of stages) {
    const wrap = topic(page, stage.id).locator('.pipeline-wrap');
    await eventually(async () => {
      const state = await wrap.evaluate(el => {
        const now = el.querySelector('.node.now').getBoundingClientRect();
        const frame = el.getBoundingClientRect();
        return { scrolls: el.scrollWidth > el.clientWidth, visible: now.left >= frame.left - 1 && now.right <= frame.right + 1 };
      });
      assert.deepEqual(state, { scrolls: true, visible: true }, `${stage.id}: current stage in view`);
    }, `${stage.id}: current stage in view`);
  }
}

test('D1: on a phone the graph scrolls sideways, starting at the current stage', async t => {
  await currentStagesInView(await pageFor(t, { viewport: viewports[2] }));
});

test('D1: after a wide page is narrowed, each graph scrolls to its current stage', async t => {
  // Loaded paged, where the other slides' graphs are hidden; then rotated or resized to a phone.
  const page = await pageFor(t, { viewport: viewports[0] });
  await goTo(page, 'logits');
  await page.setViewportSize(viewports[2]);
  await currentStagesInView(page);
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
