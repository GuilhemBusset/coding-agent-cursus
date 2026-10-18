import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { access, mkdir, readFile, realpath, stat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { chromium } from '../browser.mjs';
import { openPage, repoRoot, count, eventually, assertCollected } from './component-helpers.mjs';

// Issue 46. These are structural/behavioural floors, complemented by check-page
// and the cross-vendor prose/math review at the recorded deck hash. A keyword
// match is not a correctness review, and a 45-minute budget is not a rehearsal.
// npm --prefix setup test collects this suite by discovery: there is no list to edit.
const cursus = path.join(repoRoot, 'sessions/01-fundamentals/cursus');
const file = path.join(cursus, '01-sampler.html');
const evidence = path.join(cursus, '01-sampler');
const artifacts = path.join(repoRoot, 'artifacts/html-pages/sampler');
const viewports = [
  { width: 1440, height: 900 },
  { width: 1280, height: 720 },
  { width: 390, height: 844 },
];
const norm = value => value.normalize('NFKC').replace(/[‘’]/g, "'")
  .replace(/[−–]/g, '-').replace(/\s+/g, ' ').trim().toLowerCase();
// Quoted fixture text remains case-sensitive; normalize whitespace only.
const quoteNorm = value => value.replace(/\s+/g, ' ').trim();
const math = value => norm(value).replace(/[\s_]/g, '');
const topic = (page, prefix) => page.locator(`section[data-slide][id^="${prefix}"]`).first();
const slides = page => page.locator('main[data-deck] section[data-slide]');
const notes = slide => slide.locator('details.speaker-notes');
const notesText = async slide => norm(await notes(slide).evaluate(el => {
  const copy = el.cloneNode(true);
  copy.querySelector('summary')?.remove();
  return copy.textContent;
}));
// Exclude disclosures from the student-facing text floor, even in no-JS mode.
async function face(slide) {
  return norm(await slide.evaluate(el => {
    const copy = el.cloneNode(true);
    copy.querySelectorAll('details.speaker-notes, script, [hidden], [aria-hidden="true"]').forEach(el => el.remove());
    return copy.textContent;
  }));
}
async function pageFor(t, options = {}) {
  return openPage(t, chromium, { file, ...options });
}
async function idsOf(page) {
  return slides(page).evaluateAll(els => els.map(el => el.id));
}
function firstIndex(ids, prefix) {
  const index = ids.findIndex(id => id.startsWith(prefix));
  assert.ok(index >= 0, `missing slide with id prefix ${prefix}`);
  return index;
}
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
function markdownSection(markdown, heading) {
  const lines = markdown.split('\n');
  const start = lines.findIndex(line => /^#{1,6}\s/.test(line) && heading.test(line));
  assert.ok(start >= 0, `missing evidence heading ${heading}`);
  const level = lines[start].match(/^#+/)[0].length;
  const rest = lines.slice(start + 1);
  const end = rest.findIndex(line => new RegExp(`^#{1,${level}}\\s`).test(line));
  const body = (end < 0 ? rest : rest.slice(0, end)).join('\n').trim();
  assert.ok(body, `evidence under ${heading} is nonempty`);
  return body;
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

test('D2–D7: teaching order, with room for additional activity slides', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  const ids = await idsOf(page);
  assert.equal(firstIndex(ids, 'factorization'), 1, 'factorization is first after the title');
  let previous = 1;
  for (const prefix of ['tokens', 'strawberry', 'distribution', 'attention', 'pretraining', 'post-training', 'rlvr']) {
    const index = firstIndex(ids, prefix);
    assert.ok(index > previous, `${prefix} follows the previous concept`);
    previous = index;
  }
  for (const prefix of ['cutoff', 'hallucination', 'or-stake']) assert.ok(firstIndex(ids, prefix) > previous);
  assert.ok(ids.at(-1).startsWith('system-1'), 'the last slide closes on System 1');
});

test('D2: conditional, joint factorization and board instruction', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  const slide = topic(page, 'factorization');
  const text = await face(slide);
  assert.ok(math(text).includes('p(xt|x<t)'), 'conditional with the whole preceding context');
  assert.match(text, /∏/);
  assert.match(text, /joint/);
  assert.match(math(text), /p\(x1,(?:…|\.\.\.),?xt\)\s*=/,
    'the joint over the sequence is shown (correct product bounds are prose-review evidence)');
  const talk = await notesText(slide);
  assert.match(talk, /board/);
  assert.match(talk, /writ|put|draw/);
  assert.match(talk, /chain[ -]rule|factoriz|factoris/);
  // Meaning, boundary conventions and projector readability are reviewed in D2
  // evidence; they cannot be established by requiring a particular sentence.
});

test('D3: real integer token ID and a strawberry-to-code demo slot', async t => {
  const fixture = JSON.parse(await readFile(path.join(cursus, 'fixtures/next_token.json'), 'utf8'));
  const strawberry = fixture.prompts.find(item => item.prompt === ' strawberry');
  assert.ok(strawberry?.prompt_tokens.length, 'fixture contains the real leading-space strawberry prompt');
  const page = await pageFor(t, { javaScriptEnabled: false });
  const tokenText = await face(topic(page, 'tokens'));
  for (const term of [/integer/, /\bids?\b/, /strawberry/, /gpt[ -]?2/]) assert.match(tokenText, term);
  for (const token of strawberry.prompt_tokens) assert.match(tokenText, new RegExp(`\\b${token.id}\\b`),
    'token ID comes from prompt_tokens, not from a next-token candidate');
  const demo = topic(page, 'strawberry');
  const text = await face(demo);
  assert.match(text, /strawberry/);
  assert.match(text, /code/);
  const slots = await demo.locator('a[href], code').evaluateAll(els => els.map(el =>
    el.tagName === 'A' ? el.getAttribute('href') : el.textContent));
  assert.ok(slots.some(value => value.includes('demos/model/strawberry.md')), 'runbook link or code-path slot');
  await access(path.join(cursus, 'demos/model/strawberry.md'));
});

test('D4: a distribution, temperature, sampling, reproducibility and the System 1 close', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  const distribution = topic(page, 'distribution');
  const text = await face(distribution);
  for (const term of [/distribution/, /softmax/, /temperature/, /sampl/, /system 1/]) assert.match(text, term);
  assert.ok(math(text).includes('softmax(z/t)'), 'temperature formula is readable HTML');
  const ids = await idsOf(page);
  let reproduction = false;
  for (const slide of (await slides(page).all()).slice(firstIndex(ids, 'distribution') + 1)) {
    if (/reproduc/.test(await face(slide))) reproduction = true;
  }
  assert.ok(reproduction, 'a later slide addresses reproducibility');
  const close = await face(slides(page).last());
  assert.match(close, /system 1/);
  assert.match(close, /fixed compute per token/);
});

test('D5: one attention concept followed by its activity', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  const ids = await idsOf(page);
  const index = firstIndex(ids, 'attention');
  const slide = slides(page).nth(index);
  const text = await face(slide);
  for (const term of [/query/, /key/, /value/, /softmax/, /lookup/]) assert.match(text, term);
  assert.ok(math(text).includes('softmax(qkt/√d)·v'), 'scaled attention formula is readable HTML');
  const next = slides(page).nth(index + 1);
  assert.ok((await next.locator('a[href]').evaluateAll(els => els.map(el => el.href)))
    .some(href => href.startsWith('file:') && fileURLToPath(href) === path.join(cursus, 'labs/attention.html')),
  'the following slide is the attention activity');
  for (const other of (await page.locator('section[data-slide][id^="attention"]').all()).slice(1)) {
    assert.ok((await other.locator('a[href]').evaluateAll(els => els.map(el => el.href)))
      .some(href => href.startsWith('file:') && fileURLToPath(href) === path.join(cursus, 'labs/attention.html')),
    'additional attention-prefixed slides are activities, keeping the concept to one slide');
  }
  // An activity may itself mention query/key/value. Identify the concept by its
  // first prefix, without banning links or imposing a count on activity slides.
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

test('D6: static factual fixture comparison and recorded decoding provenance', async t => {
  const fixture = JSON.parse(await readFile(path.join(cursus, 'fixtures/base_vs_instruct.json'), 'utf8'));
  const item = fixture.items.find(item => item.id === 'factual');
  assert.ok(item, 'factual comparison is available');
  const page = await pageFor(t, { javaScriptEnabled: false });
  for (const prefix of ['pretraining', 'post-training', 'rlvr']) {
    await count(page.locator(`section[data-slide][id^="${prefix}"]`), 1);
  }
  const pretraining = topic(page, 'pretraining');
  assert.match(await face(pretraining), /compression/);
  assert.ok((await pretraining.locator('.cite a[href]').evaluateAll(els => els.map(el => el.href)))
    .some(url => /(?:arxiv\.org\/(?:abs|pdf)\/|doi\.org\/10\.48550\/arXiv\.)2309\.10668/i.test(url)),
  'pretraining cites the compression paper');
  const post = topic(page, 'post-training');
  const text = await face(post);
  for (const term of [/base/, /assistant/, /recorded/, /excerpt/]) assert.match(text, term);
  const comparison = post.locator('[data-fixture-id="factual"]');
  await count(post.locator('[data-fixture-id]'), 1);
  await count(comparison, 1);
  assert.equal(await comparison.isVisible(), true, 'fixture quotations are authored HTML, readable without JS');
  const displayed = quoteNorm(await comparison.innerText());
  assert.ok(displayed.includes(quoteNorm(item.prompt)), 'shared question is item.prompt');
  assert.ok(!displayed.includes('<|im_start|>'), 'do not expose the chat-templated instruct.input as the question');
  const quotationDOM = await comparison.evaluate(el => {
    function quoteText(node) {
      const copy = node.cloneNode(true);
      copy.querySelectorAll('cite, .cite, footer, figcaption').forEach(node => node.remove());
      copy.querySelectorAll('p, div, br, li').forEach(node => node.after(document.createTextNode('\n')));
      return copy.textContent;
    }
    const explicit = [...el.querySelectorAll('blockquote, q, pre')]
      .filter(node => !node.parentElement.closest('blockquote, q, pre'));
    const text = el.innerText;
    const quoted = [...text.matchAll(/“([^”]+)”|«([^»]+)»|"([^"\n]+)"/g)].map(m => m[1] || m[2] || m[3]);
    const blocks = [...el.querySelectorAll('p, td, dd, li, code, div')]
      .filter(node => !node.querySelector('p, td, dd, li, pre, div, blockquote, q') &&
        !node.closest('cite, .cite, footer, figcaption'))
      .map(node => node.innerText.trim());
    return { explicit: explicit.map(quoteText), quoted, blocks };
  });
  // Plain paragraphs under separate model headings are valid too. Semantic
  // quotations are always validated, including wrong ones; otherwise recognize
  // source text without mistaking surrounding explanation for a quotation.
  const sources = [item.base.text, item.instruct.text, item.prompt].map(quoteNorm);
  const blocks = quotationDOM.blocks.filter(text => {
    const stripped = stripQuoteLabel(text);
    return stripped && sources.some(source => source.includes(stripped));
  });
  const quotes = quotationDOM.explicit.length ? quotationDOM.explicit : quotationDOM.quoted;
  const candidates = [...new Set([...quotes, ...blocks])];
  validateQuotes(candidates, item);
  const citation = quoteNorm((await post.locator('.cite').allTextContents()).join(' '));
  for (const model of fixture.meta.models) {
    assert.ok(citation.includes(model.id), 'citation names the model');
    assert.ok(citation.includes(model.revision), 'citation names the full pinned revision');
  }
  assert.ok(citation.includes(fixture.meta.date), 'citation names the recording date');
  assert.match(citation, /greedy/i);
  assert.match(citation, new RegExp(`\\b${fixture.max_new_tokens}\\b`));
  assert.match(citation, /(?:max|up to)[\s\S]*new tokens|new tokens[\s\S]*(?:max|limit)/i);
  const rlvr = topic(page, 'rlvr');
  for (const term of [/verifiable/, /reward/]) assert.match(await face(rlvr), term);
  assert.ok((await rlvr.locator('.cite a[href]').evaluateAll(els => els.map(el => el.href)))
    .some(url => /(?:arxiv\.org\/(?:abs|pdf)\/|doi\.org\/10\.48550\/arXiv\.)2411\.15124/i.test(url)),
  'RLVR cites Tülu 3 as the source of the term');
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

test('D7: cutoff, structural hallucination and the illustrative objective-sense trap', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  assert.match(await face(topic(page, 'cutoff')), /cutoff/);
  const hallucination = await face(topic(page, 'hallucination'));
  for (const term of [/oracle/, /structural/]) assert.match(hallucination, term);
  const or = topic(page, 'or-stake');
  const text = await face(or);
  for (const term of [/minimize|kminimize/, /maximize|kmaximize/, /fluen/]) assert.match(text, term);
  assert.match(await or.innerText(), /illustrative/i, 'the invented solver example has a visible label');
  assert.match(await notesText(or), /changeobjectivesense/i);
  assert.match(await notesText(or), /p00/);
  // Which objective matches the stated problem, and whether only its sense
  // changes, are assessed in D7's hash-bound prose review, not frozen code text.
});

async function localLinks(page) {
  const links = [];
  const root = await realpath(cursus);
  for (const link of await page.locator('a[href]').all()) {
    const href = await link.getAttribute('href');
    assert.ok(!/(?:^|\/)(?:test-time-compute|world-model)\.html(?:[?#]|$)/.test(href),
      'Act II widgets belong in Act II');
    if (/^https?:/i.test(href)) continue; // citations are links, never runtime dependencies
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

test('D8: relative links resolve and the four activities occur after their concepts', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  const ids = await idsOf(page);
  const links = await localLinks(page);
  const index = prefix => firstIndex(ids, prefix);
  for (const [name, start, end] of [
    ['tokenizer', index('tokens'), index('strawberry')],
    ['next-token', index('distribution'), index('attention')],
    ['tiny-lm', index('distribution'), index('attention')],
    ['attention', index('attention') + 1, index('attention') + 2],
  ]) {
    const matching = links.filter(link => !link.inNotes && link.target === path.join(cursus, `labs/${name}.html`));
    assert.ok(matching.length > 0, `link to ${name} widget`);
    assert.ok(matching.some(link => {
      const at = ids.indexOf(link.slide);
      return at >= start && at < end;
    }), `${name} has a link in its concept/activity group`);
  }
});

test('D8: all four file:// activities load offline and Back restores their originating slides', { timeout: 120000 }, async t => {
  const page = await pageFor(t);
  const links = await localLinks(page);
  for (const name of ['tokenizer', 'next-token', 'tiny-lm', 'attention']) {
    const destination = path.join(cursus, `labs/${name}.html`);
    const link = links.find(link => !link.inNotes && link.target === destination);
    assert.ok(link?.slide, `${name} has a slide-local activity link`);
    await goTo(page, link.slide);
    const anchor = page.locator('section[data-slide]').filter({ has: page.locator(`a[href=${JSON.stringify(link.href)}]`) })
      .locator(`a[href=${JSON.stringify(link.href)}]`).first();
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
      if (index === 1 || id.startsWith('distribution') || id.startsWith('post-training')) {
        await page.screenshot({ path: path.join(artifacts, `notes-${viewport.width}-${index + 1}.png`), fullPage: true });
      }
      await page.keyboard.press(key);
      await eventually(async () => assert.equal(await disclosure.evaluate(el => el.open), false));
      await activeSlide(page, id);
    }
    // A second, nontrivial state: extend actual notes in memory. No fixture,
    // runtime file or implementation script is altered. The disclosure must
    // contain long notes in its own scroll area rather than clip the talk track.
    const id = ids[firstIndex(ids, 'distribution')];
    await goTo(page, id);
    const disclosure = notes(topic(page, 'distribution'));
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

test('D1–D7: review evidence is bound to the current deck and covers all required views', async () => {
  const bytes = await readFile(file);
  const hash = createHash('sha256').update(bytes).digest('hex');
  const review = await readFile(path.join(evidence, 'review.md'), 'utf8');
  assert.ok(review.includes(hash), 'any deck edit invalidates the prose and screenshot review');
  assert.ok(review.replace(/[,\u2009\u202f]/g, '').includes(String(bytes.length)), 'review records the deck byte size');
  for (const criterion of ['D2', 'D3', 'D4', 'D5', 'D6', 'D7']) markdownSection(review, new RegExp(`\\b${criterion}\\b`));
  const views = markdownSection(review, /screenshot|visual.*review/i);
  for (const view of [/desktop/i, /laptop/i, /mobile/i, /no[ -]?(?:js|javascript)/i, /print/i, /reduced[ -]motion/i]) assert.match(views, view);
  // A cross-vendor reviewer confirms these sections against the deck at hash.
  // This test intentionally cannot certify that the prose is scientifically true.
});

test('A1 evidence scaffold: rehearsal plan and fields for the owner’s timed run exist', async () => {
  const rehearsal = await readFile(path.join(evidence, 'rehearsal.md'), 'utf8');
  for (const field of [/plan|schedule/i, /date/i, /sha[ -]?256/i, /observed/i, /minutes/i, /total/i, /cuts/i]) assert.match(rehearsal, field);
  // Do not require a fabricated observation, nor permanently require "pending":
  // a person may later fill the table. A1 remains manual until that run is reviewed.
});
