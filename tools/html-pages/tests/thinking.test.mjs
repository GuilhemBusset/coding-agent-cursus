import test from 'node:test';
import assert from 'node:assert/strict';
import { access, readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { chromium } from '../browser.mjs';
import { repoRoot, openPage, eventually, suites } from './component-helpers.mjs';

/* Locked acceptance contract for issue 40, authored before the deck.
 * Run the WHOLE file through run-suite.mjs; filtering/skipping is not evidence.
 * Keyword checks are floors, not a factual review. Hash-bound review.md and the
 * independent PR reviewer establish source support and inspect screenshots.
 * check-page.mjs supplies axe, asset integrity and presentation layout checks.
 * A real 45-minute delivery rehearsal remains the instructor's obligation;
 * these tests check a timing PLAN and never manufacture actual delivery times.
 */
const stem = 'sessions/01-fundamentals/cursus/02-thinking';
const file = path.join(repoRoot, `${stem}.html`);
const reviewFile = path.join(repoRoot, stem, 'review.md');
const demo = path.join(repoRoot, 'sessions/01-fundamentals/cursus/demos/effort');
const sessionRoot = path.join(repoRoot, 'sessions/01-fundamentals');
const asOf = '2026-10-11';
const planned = ['title', 'forward-pass', 'loop', 'system-1-2', 'cot-depth',
  'search', 'rlvr', 'sharpen-or-expand', 'effort-dials', 'effort-demo',
  'overthinking', 'cot-faithfulness', 'addition-36-59', 'tool-cues',
  'world-models', 'internal-representations', 'kepler', 'simulators',
  'repo-model', 'wrap'];
const nonConcept = new Set(['title', 'effort-demo', 'wrap']);
const contestedTopics = ['sharpen-or-expand', 'cot-faithfulness', 'tool-cues'];
const normal = value => value.normalize('NFKC').replace(/[\u2010-\u2015\u2212]/g, '-')
  .replace(/[\u2018\u2019]/g, "'").replace(/\s+/g, ' ').trim();
const dateRE = /\b(?:\d{4}-\d{2}-\d{2}|(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+\d{4})\b/i;
const slides = page => page.locator('section[data-slide]');
const topic = (page, id) => page.locator(`section[data-slide]#${id}, section[data-slide][id^="${id}-"]`);
const pageFor = (t, options = {}) => openPage(t, chromium, {
  file, offline: true, javaScriptEnabled: false, ...options,
});
const topicOf = id => planned.find(name => id === name || id.startsWith(`${name}-`));

async function orderedIds(page) {
  const ids = await slides(page).evaluateAll(nodes => nodes.map(node => node.id));
  assert.equal(new Set(ids).size, ids.length, 'unique slide IDs');
  for (const id of planned) assert.ok(ids.includes(id), `missing agreed slide #${id}`);
  let previous = -1;
  for (const id of ids) {
    const name = topicOf(id);
    assert.ok(name, `split slide ${id} must keep its topic prefix`);
    const index = planned.indexOf(name);
    assert.ok(index >= previous, `${id} is out of teaching order`);
    previous = index;
  }
  assert.equal(ids[0], 'title');
  assert.equal(topicOf(ids.at(-1)), 'wrap');
  return ids;
}

// Use rendered content, excluding sources, advice and instructor notes: a paper
// title in a citation or a hidden keyword must not stand in for teaching a topic.
async function contentText(page, id) {
  const parts = await topic(page, id).evaluateAll(nodes => nodes.map(el => {
    const out = [];
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const node = walker.currentNode;
      const parent = node.parentElement;
      if (!parent || parent.closest('.notes, .cite, .drive, script, style')) continue;
      const range = document.createRange();
      range.selectNodeContents(node);
      if (!Array.from(range.getClientRects()).some(rect => rect.width > 0 && rect.height > 0)) continue;
      if (getComputedStyle(parent).visibility !== 'hidden') out.push(node.textContent);
    }
    return out.join(' ');
  }));
  return normal(parts.join(' '));
}

async function floor(page, id, expressions) {
  assert.ok(await topic(page, id).count() > 0, `missing ${id}`);
  const text = await contentText(page, id);
  for (const expression of expressions) assert.match(text, expression, `${id}: visible concept content`);
  return text;
}

async function driveLines(page, names = planned.filter(id => !nonConcept.has(id))) {
  for (const name of names) {
    for (const slide of await topic(page, name).all()) {
      const id = await slide.getAttribute('id');
      const drive = slide.locator(':scope > p.drive');
      assert.equal(await drive.count(), 1, `${id}: one direct Driving paragraph`);
      assert.equal(await drive.isVisible(), true, `${id}: advice is visible`);
      assert.match(await drive.innerText(), /^\s*Driving\s*:/i);
      assert.match(await drive.locator('strong').innerText(), /^\s*Driving\s*:/i);
      assert.ok(normal(await drive.innerText()).replace(/^Driving\s*:\s*/i, '').length > 0,
        `${id}: advice must contain more than the label`);
      assert.equal(await slide.evaluate(el => el.lastElementChild?.previousElementSibling?.matches('p.drive')),
        true, `${id}: concept ends with Driving, followed only by notes`);
    }
  }
}

async function cited(page, id, predicate, label) {
  const hrefs = await topic(page, id).locator('.cite a[href]').evaluateAll(nodes => nodes.map(n => n.href));
  assert.ok(hrefs.some(href => {
    const url = new URL(href);
    return /^https?:$/.test(url.protocol) && predicate(url);
  }), `${id}: ${label} must be linked inside .cite`);
}
const arxiv = id => url => /^(?:www\.)?arxiv\.org$/.test(url.hostname) &&
  new RegExp(`^/(?:abs|pdf)/${id.replace('.', '\\.')}(?:v\\d+)?(?:\\.pdf)?/?$`).test(url.pathname);
const onSite = (host, part) => url => (url.hostname === host || url.hostname.endsWith(`.${host}`)) &&
  url.pathname.includes(part);
const biology = onSite('transformer-circuits.pub', '/2025/attribution-graphs/biology.html');
const faithfulness = onSite('anthropic.com', '/research/reasoning-models-dont-say-think');

async function namedCitation(page, id, name, date) {
  for (const cite of await topic(page, id).locator('.cite').all()) {
    const text = await cite.innerText();
    if (!name.test(text) || !date.test(text)) continue;
    const hrefs = await cite.locator('a[href]').evaluateAll(ns => ns.map(n => n.href));
    if (hrefs.some(href => /^https?:/.test(href))) return;
  }
  assert.fail(`${id}: named, dated source ${name} (${date})`);
}

function section(markdown, id) {
  const headings = [...markdown.matchAll(/^(#{1,6})\s+(.+)$/gm)];
  const index = headings.findIndex(h => new RegExp(`\\b${id}\\b`).test(h[2]));
  assert.ok(index >= 0, `review.md needs a ${id} heading`);
  const start = headings[index];
  const end = headings.slice(index + 1).find(h => h[1].length <= start[1].length);
  const body = markdown.slice(start.index + start[0].length, end?.index ?? markdown.length).trim();
  assert.ok(body.length > 40, `review.md ${id} needs substantive evidence`);
  return body;
}

async function reviewEvidence(id, expressions = []) {
  const [deck, review] = await Promise.all([readFile(file), readFile(reviewFile, 'utf8')]);
  const hash = createHash('sha256').update(deck).digest('hex');
  assert.match(review, new RegExp(`\\b${hash}\\b`), 'review must be bound to the CURRENT deck sha256');
  const body = section(review, id);
  for (const expression of expressions) assert.match(normal(body), expression, `${id}: named review evidence`);
  return { deck, review, body };
}

async function datedCitations(page) {
  for (const slide of await slides(page).all()) {
    const id = await slide.getAttribute('id');
    if (['title', 'wrap'].includes(topicOf(id))) continue;
    const citations = await slide.locator('.cite').all();
    let visibleCount = 0;
    for (const cite of citations) {
      // Supporting citations inside collapsed notes are allowed. At least one
      // complete citation must remain visible on the presentation slide.
      if (!await cite.isVisible()) continue;
      visibleCount++;
      assert.match(await cite.innerText(), dateRE, `${id}: citation needs ISO or month/year date`);
      const external = await cite.locator('a[href]').evaluateAll(nodes => nodes.some(n => /^https?:$/.test(new URL(n.href).protocol)));
      const internal = await cite.locator('cite').count() > 0 &&
        /(?:cursus|demos|labs|recorded)\/[\w./-]+/.test(await cite.innerText());
      assert.ok(external || internal, `${id}: external source or <cite> with repo-relative material path`);
    }
    assert.ok(visibleCount > 0, `${id}: needs a visible dated citation`);
  }
}

async function contested(page, id) {
  const labels = topic(page, id).locator('span.contested');
  assert.ok(await labels.count() > 0, `${id}: visible Contested label`);
  for (const label of await labels.all()) {
    assert.equal(await label.isVisible(), true);
    assert.match(await label.innerText(), /\bcontested\b/i);
    const reason = await label.evaluate(el => el.parentElement.innerText);
    assert.ok(normal(reason).replace(/\bcontested\b/ig, '').trim().length > 0,
      `${id}: label is accompanied by a reason`);
  }
}

test('D1: deck structure, topic order, speaker notes and registration', async t => {
  const page = await pageFor(t);
  assert.equal(await page.locator('html').getAttribute('data-page-kind'), 'deck');
  assert.equal(await page.locator('html').getAttribute('data-design-system'), 'cursus');
  assert.equal(await page.locator('main[data-deck]').count(), 1);
  assert.equal(await page.locator('main[data-deck] nav[data-deck-nav]').count(), 1);
  assert.equal(await page.locator('script[src], script[type="module"]').count(), 0);
  const ids = await orderedIds(page);
  assert.equal(await page.locator('main[data-deck] section[data-slide]').count(), ids.length);
  for (const slide of await slides(page).all()) {
    const id = await slide.getAttribute('id');
    assert.equal(await slide.getAttribute('tabindex'), '-1', `${id}: authored slide focus contract`);
    const labelledBy = (await slide.getAttribute('aria-labelledby') || '').trim().split(/\s+/).filter(Boolean);
    assert.ok(labelledBy.length > 0, `${id}: accessible slide title`);
    for (const label of labelledBy) {
      assert.ok(await page.evaluate(label => !!document.getElementById(label)?.textContent.trim(), label), `${id}: title ${label} exists`);
    }
    const notes = slide.locator(':scope > details.notes[data-minutes]');
    assert.equal(await notes.count(), 1, `${id}: one speaker-notes disclosure`);
    assert.equal(await slide.evaluate(el => el.lastElementChild.matches('details.notes[data-minutes]')), true,
      `${id}: notes are the last child`);
    assert.equal(await notes.locator(':scope > summary').count(), 1);
    const summary = await notes.locator('summary').innerText();
    assert.match(summary, /speaker notes/i);
    assert.match(summary, /\bmin(?:ute)?s?\b/i);
    const minutes = Number(await notes.getAttribute('data-minutes'));
    assert.ok(Number.isFinite(minutes) && minutes > 0, `${id}: positive minute budget`);
    assert.ok((summary.match(/\d+(?:\.\d+)?/g) || []).some(n => Number(n) === minutes), `${id}: summary matches minute budget`);
    assert.equal(await notes.isVisible(), true, `${id}: no-JS summary is readable`);
    await notes.locator('summary').click();
    assert.equal(await notes.evaluate(el => el.open), true, `${id}: native disclosure opens without JS`);
    const body = await notes.evaluate(el => Array.from(el.children).filter(n => n.tagName !== 'SUMMARY').map(n => n.innerText).join(' '));
    // Text directly inside details is valid too; do not prescribe paragraph markup.
    const all = normal(await notes.innerText()).replace(normal(summary), '').trim();
    assert.ok(normal(body || all).length > 0, `${id}: nonempty speaker cues`);
    await notes.locator('summary').click();
  }
  await driveLines(page);
  assert.ok(suites.includes('thinking'), 'component-helpers registers thinking');
  const pkg = JSON.parse(await readFile(path.join(repoRoot, 'setup/package.json'), 'utf8'));
  const argv = pkg.scripts.test.trim().split(/\s+/);
  assert.deepEqual(argv.slice(0, 2), ['node', '--test']);
  assert.ok(argv.slice(2).map(arg => path.resolve(repoRoot, 'setup', arg)).includes(path.join(repoRoot, 'tools/html-pages/tests/thinking.test.mjs')),
    'npm test runs the full thinking suite');
});

test('D1: every deep-linked slide navigates to its actual neighbours and history restores it', async t => {
  const page = await pageFor(t, { javaScriptEnabled: true });
  const ids = await orderedIds(page);
  // Exercise nonadjacent middle slides as well as the obvious title. The
  // expected successor is derived from the authored DOM, including split slides.
  for (let index = 0; index < ids.length - 1; index++) {
    await page.goto(`${pathToFileURL(file).href}#${encodeURIComponent(ids[index])}`);
    const current = page.locator(`section[data-slide]#${ids[index]}`);
    assert.equal(await current.isVisible(), true);
    assert.equal(await slides(page).filter({ visible: true }).count(), 1);
    assert.equal(await current.locator('details.notes').evaluate(el => el.open), false,
      'speaker notes start collapsed for presentation');
    await current.focus();
    await page.keyboard.press('ArrowRight');
    await eventually(async () => {
      assert.equal(decodeURIComponent(new URL(page.url()).hash.slice(1)), ids[index + 1]);
      assert.equal(await page.locator(`section[data-slide]#${ids[index + 1]}`).isVisible(), true);
    });
    await page.goBack();
    await eventually(async () => assert.equal(await current.isVisible(), true), 'Back restores the chosen middle slide');
    await page.goForward();
    await eventually(async () => assert.equal(await page.locator(`section[data-slide]#${ids[index + 1]}`).isVisible(), true), 'Forward restores the successor');
  }
  // A summary retains its native keyboard behavior; deck keys must not steal it.
  await page.goto(`${pathToFileURL(file).href}#cot-depth`);
  const notes = page.locator('#cot-depth > details.notes');
  await notes.locator('summary').focus();
  await page.keyboard.press('Space');
  assert.equal(await notes.evaluate(el => el.open), true);
  assert.equal(new URL(page.url()).hash, '#cot-depth');
});

test('D1: notes and all slides remain readable without JS and in print', async t => {
  for (const javaScriptEnabled of [false, true]) {
    const page = await pageFor(t, { javaScriptEnabled });
    const ids = await orderedIds(page);
    if (!javaScriptEnabled) {
      for (const slide of await slides(page).all()) assert.equal(await slide.isVisible(), true);
    }
    await page.emulateMedia({ media: 'print' });
    for (const id of ids) {
      const slide = page.locator(`section[data-slide]#${id}`);
      assert.equal(await slide.isVisible(), true, `${id}: print shows every slide`);
      const text = await slide.locator('details.notes').evaluate(el => {
        const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
        const content = [];
        while (walker.nextNode()) {
          const n = walker.currentNode;
          if (!n.textContent.trim() || n.parentElement.closest('summary')) continue;
          const range = document.createRange();
          range.selectNodeContents(n);
          if (Array.from(range.getClientRects()).some(r => r.width && r.height) && getComputedStyle(n.parentElement).visibility !== 'hidden') content.push(n.textContent);
        }
        return content.join(' ');
      });
      assert.ok(normal(text).length > 0, `${id}: print exposes the note body, not just its summary`);
    }
  }
});

test('D2: single forward pass, token feedback, serial compute and the one-network metaphor', async t => {
  const page = await pageFor(t);
  await orderedIds(page);
  await floor(page, 'forward-pass', [/forward pass/i, /single|one|fixed/i, /token/i]);
  await floor(page, 'loop', [/token/i, /sampl/i, /fed back|feed.*back|append/i, /serial|sequential/i, /comput|pass/i]);
  await floor(page, 'system-1-2', [/Kahneman/i, /Bengio/i, /2019/, /LeCun/i,
    /Mode[- ]?1/i, /Mode[- ]?2/i, /metaphor|analogy/i, /(?:same|one|single)\s+(?:neural\s+)?network/i]);
  // Keynotes can have opaque video URLs; do not require an author's surname in
  // the href. Primary-source status and exact support belong to the prose review.
  await namedCitation(page, 'system-1-2', /Bengio/i, /2019/);
  await namedCitation(page, 'system-1-2', /LeCun/i, /2022/);
  await driveLines(page, ['forward-pass', 'loop', 'system-1-2']);
  await reviewEvidence('D2', [/network/i, /metaphor|analogy|human cognition/i, /comput|budget/i, /verif|check|outcome/i]);
});

test('D3: chain of thought adds sequential depth, with a sourced limitation', async t => {
  const page = await pageFor(t);
  await floor(page, 'cot-depth', [/chain[- ]of[- ]thought|chain of thought/i, /depth/i, /sequential|serial|decod/i]);
  await cited(page, 'cot-depth', arxiv('2310.07923'), 'Merrill and Sabharwal 2310.07923');
  await driveLines(page, ['cot-depth']);
  await reviewEvidence('D3', [/Merrill/i, /Sabharwal/i, /fixed|network depth/i, /sequential|serial|decod/i, /assum|theor|formal/i, /accuracy|guarantee/i]);
});

test('D4: parallel and sequential search, RLVR and both sides of sharpen-or-expand', async t => {
  const page = await pageFor(t);
  await floor(page, 'search', [/parallel/i, /sequential/i, /verifier/i]);
  await floor(page, 'rlvr', [/verifiable rewards/i, /R1[- ]Zero/i, /R1/i]);
  await cited(page, 'rlvr', onSite('nature.com', '/articles/s41586-025-09422-z'), 'DeepSeek-R1 Nature article');
  assert.match(await topic(page, 'rlvr').locator('.cite').allTextContents().then(xs => xs.join(' ')), /2025/);
  await floor(page, 'sharpen-or-expand', [/sharpen/i, /expand/i, /coverage|pass\s*@\s*k|capabilit/i]);
  await cited(page, 'sharpen-or-expand', arxiv('2504.13837'), 'Yue et al.');
  await cited(page, 'sharpen-or-expand', arxiv('2505.24864'), 'ProRL expansion counterpoint');
  await contested(page, 'sharpen-or-expand');
  await driveLines(page, ['search', 'rlvr', 'sharpen-or-expand']);
  await reviewEvidence('D4', [/R1[- ]Zero/i, /R1/i, /coverage/i, /selection|select|verifier/i, /Yue|2504\.13837/i, /ProRL|2505\.24864/i]);
});

test('D5: dated vendor controls and demo agree with the actual recording; overthinking follows', async t => {
  const page = await pageFor(t);
  const ids = await orderedIds(page);
  const lastDemo = ids.findLastIndex(id => topicOf(id) === 'effort-demo');
  assert.equal(topicOf(ids[lastDemo + 1] || ''), 'overthinking', 'overthinking immediately follows the demo topic');
  const [prices, results] = await Promise.all(['prices.json', 'recorded/results.json'].map(async name => JSON.parse(await readFile(path.join(demo, name), 'utf8'))));
  assert.equal(prices.as_of, asOf);
  assert.equal(results.run_date, asOf);
  const models = [...new Set(results.runs.map(run => run.model))];
  assert.ok(models.length >= 2);
  for (const model of models) assert.ok(Object.values(prices).some(v => v?.models?.[model]), `${model}: listed in prices`);
  for (const id of ['effort-dials', 'effort-demo']) {
    const text = await contentText(page, id);
    for (const model of models) assert.ok(text.includes(model), `${id}: recorded model ${model}`);
    const visible = normal((await topic(page, id).allInnerTexts()).join(' '));
    assert.ok(visible.includes(asOf), `${id}: visible recording/as-of date (may be in the citation)`);
  }
  assert.match(await topic(page, 'effort-dials').locator('.cite').allTextContents().then(xs => xs.join(' ')), /as\s+of\s+2026-10-11/i);
  const rows = await topic(page, 'effort-dials').locator('table tr').all();
  let dataRows = 0;
  const found = new Set();
  for (const row of rows) {
    if (!await row.locator('td').count()) continue;
    dataRows++;
    const text = normal(await row.innerText());
    const links = await row.locator('a[href]').evaluateAll(ns => ns.map(n => n.href));
    assert.ok(links.some(href => /^https?:/.test(href)), `vendor row ${text}: docs URL`);
    if (/Claude|Anthropic/i.test(text)) {
      assert.match(text, /\beffort\b/);
      assert.ok(links.some(h => /(?:^|\.)claude\.com$|(?:^|\.)anthropic\.com$/.test(new URL(h).hostname)), 'Claude official docs');
      found.add('claude');
    }
    if (/OpenAI|Codex/i.test(text)) {
      assert.match(text, /model_reasoning_effort/);
      assert.ok(links.some(h => /(?:^|\.)openai\.com$/.test(new URL(h).hostname)), 'OpenAI official docs');
      found.add('openai');
    }
    if (/Gemini|Google/i.test(text)) {
      assert.match(text, /thinking|budget|level/i);
      assert.ok(links.some(h => /(?:^|\.)(?:google\.dev|google\.com)$/.test(new URL(h).hostname)), 'Gemini official docs');
      found.add('gemini');
    }
  }
  assert.ok(dataRows >= 3, 'at least three vendor rows');
  assert.deepEqual([...found].sort(), ['claude', 'gemini', 'openai']);
  await cited(page, 'effort-dials', url => url.href === results.docs.claude_effort || onSite('claude.com', '/effort')(url), 'Claude effort documentation');
  await cited(page, 'effort-dials', url => url.href === results.docs.codex_config || onSite('openai.com', '/codex/')(url), 'Codex configuration documentation');
  await floor(page, 'overthinking', [/inverse scaling/i, /overthinking/i]);
  await cited(page, 'overthinking', arxiv('2507.14417'), 'inverse scaling paper');
  await cited(page, 'overthinking', arxiv('2412.21187'), 'overthinking paper');
  await floor(page, 'effort-demo', [/one|single/i, /sample/i, /anecdote/i, /rate/i]);
  await driveLines(page, ['effort-dials', 'overthinking']);
  await reviewEvidence('D5', [/vendor|documentation|docs/i, /record|sample/i, /tokens|seconds|cost|number/i, /anecdote|rate/i]);
});

test('D6: hint faithfulness, 36 + 59, and qualified tool-output cues', async t => {
  const page = await pageFor(t);
  await floor(page, 'cot-faithfulness', [/hint/i, /mention|report|faithful/i]);
  await cited(page, 'cot-faithfulness', faithfulness, 'Anthropic faithfulness study');
  await contested(page, 'cot-faithfulness');
  await floor(page, 'addition-36-59', [/36\s*\+\s*59/, /\b95\b/, /approxim|carry|parallel/i]);
  await cited(page, 'addition-36-59', biology, 'Biology of a Large Language Model');
  await floor(page, 'tool-cues', [/tool(?:\s+|-)(?:output|result)/i, /cue|hint|instruct/i]);
  await contested(page, 'tool-cues');
  // The design permits an explicitly illustrative case when there is no study
  // supporting this exact tool-output claim. Evidence quality is reviewer-owned.
  const toolText = await contentText(page, 'tool-cues');
  const toolReview = await reviewEvidence('D6', [/36\s*\+\s*59/, /95/, /approxim/i, /carry/i, /explan|stated/i, /limit/i, /evidence|verif|check/i]);
  if (/illustrative|hypothetical|unverified/i.test(toolText)) {
    assert.match(toolText, /illustrative|hypothetical/i, 'unverified case is explicitly an example');
    assert.match(toolReview.body, /tool.*(?:illustrative|hypothetical)|(?:illustrative|hypothetical).*tool/is);
  } else {
    await cited(page, 'tool-cues', () => true, 'a primary source supporting the tool-output example');
    assert.match(toolReview.body, /tool|prompt.injection/i);
  }
  await driveLines(page, ['cot-faithfulness', 'addition-36-59', 'tool-cues']);
});

test('D7: three world-model meanings, representations, limits, simulators and the repo', async t => {
  const page = await pageFor(t);
  await orderedIds(page);
  await floor(page, 'world-models', [/represent|internal/i, /simulat/i, /repo|repository/i]);
  await floor(page, 'internal-representations', [/Othello/i, /board|state/i, /rhyme/i, /plan/i]);
  await cited(page, 'internal-representations', arxiv('2210.13382'), 'Othello-GPT');
  await cited(page, 'internal-representations', biology, 'rhyme-planning evidence');
  await floor(page, 'kepler', [/Kepler/i, /Newton/i, /limit|generaliz|break|mass|force/i]);
  await cited(page, 'kepler', arxiv('2507.06952'), 'Kepler vs Newton');
  await floor(page, 'simulators', [/V[- ]JEPA\s*2/i, /Genie\s*3/i, /Cosmos\s*3/i, /AMI\s*Labs/i, /goal|aim|ambition|propos/i]);
  await cited(page, 'simulators', arxiv('2506.09985'), 'V-JEPA 2');
  await cited(page, 'simulators', onSite('deepmind.google', '/genie-3'), 'official Genie 3 announcement');
  // Cosmos/AMI URLs were intentionally left for source discovery in the design.
  // Check a named, dated attribution rather than inventing a required URL here.
  for (const name of [/Cosmos\s*3/i, /AMI\s*Labs/i]) {
    const citations = await topic(page, 'simulators').locator('.cite').all();
    let attributed = false;
    for (const cite of citations) {
      if (!name.test(await cite.innerText())) continue;
      const hrefs = await cite.locator('a[href]').evaluateAll(ns => ns.map(n => n.href));
      if (hrefs.some(h => /^https?:/.test(h)) && dateRE.test(await cite.innerText())) attributed = true;
    }
    assert.ok(attributed, `${name}: named dated source; reviewer verifies official status and actual support`);
  }
  await floor(page, 'repo-model', [/repo|repository/i, /observation|test output|test result/i, /replan|update|loop/i]);
  await driveLines(page, ['world-models', 'internal-representations', 'kepler', 'simulators', 'repo-model']);
  await reviewEvidence('D7', [/three|3|distinct/i, /represent/i, /simulat/i, /repo|repository/i,
    /illustrative/i, /AMI/i, /goal|aim|ambition/i]);
});

async function labLink(page, id, relative) {
  const links = await topic(page, id).locator('a[href]').all();
  const expected = new URL(relative, pathToFileURL(file));
  let actual;
  for (const link of links) {
    const href = await link.getAttribute('href');
    if (new URL(href, pathToFileURL(file)).href !== expected.href) continue;
    assert.ok(!/^[a-z][a-z\d+.-]*:|^\/\//i.test(href) && !href.startsWith('/'), `${id}: bundled link is relative`);
    assert.equal(await link.isVisible(), true, `${id}: activity link is visible`);
    assert.ok(normal(await link.innerText()), `${id}: activity link has a label`);
    actual = new URL(href, pathToFileURL(file));
  }
  assert.ok(actual, `${id}: missing ${relative}`);
  const target = fileURLToPath(actual);
  assert.ok(path.relative(sessionRoot, target).split(path.sep)[0] !== '..', 'activity remains inside the session');
  await access(target);
  // Open the real target DOM over file://, not a string search for an ID in a
  // comment/script. No network and no modifications to the earlier widgets.
  const targetPage = await page.context().newPage();
  try {
    await targetPage.goto(actual.href);
    assert.equal(new URL(targetPage.url()).protocol, 'file:');
    const fragment = decodeURIComponent(actual.hash.slice(1));
    assert.ok(await targetPage.evaluate(id => {
      const element = document.getElementById(id);
      return !!element && element.getClientRects().length > 0;
    }, fragment), `${relative}: fragment identifies a rendered panel`);
  } finally { await targetPage.close(); }
}

test('D8: all activity deep links resolve offline to real panels; demo names its replay fallback', async t => {
  const page = await pageFor(t);
  await labLink(page, 'search', 'labs/test-time-compute.html#best-of-n');
  await labLink(page, 'sharpen-or-expand', 'labs/test-time-compute.html#sharpen-or-expand');
  let effortTopic;
  for (const id of ['effort-dials', 'overthinking']) {
    const hrefs = await topic(page, id).locator('a[href]').evaluateAll(ns => ns.map(n => n.getAttribute('href')));
    if (hrefs.some(h => new URL(h, pathToFileURL(file)).href === new URL('labs/test-time-compute.html#effort-dial', pathToFileURL(file)).href)) effortTopic = id;
  }
  assert.ok(effortTopic, 'effort-dials or overthinking links the effort panel');
  await labLink(page, effortTopic, 'labs/test-time-compute.html#effort-dial');
  await labLink(page, 'kepler', 'labs/world-model.html#kepler');
  await labLink(page, 'repo-model', 'labs/world-model.html#planner');
  const slot = topic(page, 'effort-demo');
  const code = await slot.locator('code').allTextContents();
  const hrefs = await slot.locator('a[href]').evaluateAll(ns => ns.map(n => n.getAttribute('href')));
  const readme = pathToFileURL(path.join(demo, 'README.md')).href;
  const readmeLinks = hrefs.filter(h => new URL(h, pathToFileURL(file)).href.split('#')[0] === readme);
  assert.ok(code.some(s => s.includes('cursus/demos/effort/')) || readmeLinks.length > 0,
    'effort demo is a code path or a relative README link');
  for (const href of readmeLinks) assert.ok(!/^[a-z][a-z\d+.-]*:|^\//i.test(href), 'demo README link is relative');
  await access(path.join(demo, 'README.md'));
  await floor(page, 'effort-demo', [/offline/i, /replay/i, /fallback|backup|recorded|if.*(?:fail|unavailable)/i]);
});

// The claim inventory is an ordinary Markdown table, not a test-only JSON API.
// Recognize descriptive headers without imposing wording, column order or a
// table position. Escaped pipes in prose and links do not split a cell.
function cells(line) {
  return line.trim().replace(/^\|/, '').replace(/\|$/, '').split(/(?<!\\)\|/).map(s => s.trim());
}
function inventory(markdown) {
  const lines = section(markdown, 'A1').split(/\r?\n/);
  const rows = [];
  for (let i = 0; i < lines.length - 1; i++) {
    const headers = cells(lines[i]);
    const separator = cells(lines[i + 1]);
    if (!lines[i].includes('|') || !separator.every(s => /^:?-{3,}:?$/.test(s))) continue;
    const keys = {
      slide: /slide/i, claim: /claim/i, date: /date|as.of/i,
      source: /URL|source|link/i, contested: /contested/i, outcome: /outcome|finding|verdict|result/i,
    };
    const columns = Object.fromEntries(Object.entries(keys).map(([key, expression]) => [key, headers.findIndex(h => expression.test(h))]));
    if (Object.values(columns).some(index => index < 0)) continue;
    const sourceSection = headers.findIndex(h => /section/i.test(h));
    assert.ok(sourceSection >= 0, 'A1 inventory needs a source section (possibly combined with URL)');
    for (i += 2; i < lines.length && lines[i].includes('|') && lines[i].trim(); i++) {
      const values = cells(lines[i]);
      assert.equal(values.length, headers.length, `malformed inventory row: ${lines[i]}`);
      const row = Object.fromEntries(Object.entries(columns).map(([key, column]) => [key, values[column]]));
      row.sourceSection = values[sourceSection];
      rows.push(row);
    }
    i--;
  }
  assert.ok(rows.length > 0, 'A1 requires a populated claim inventory table');
  return rows;
}

test('A1: visible dated citations, contested labels and hash-bound claim/source inventory', async t => {
  const page = await pageFor(t);
  await datedCitations(page);
  for (const id of contestedTopics) await contested(page, id);
  const { deck, review } = await reviewEvidence('A1');
  for (const id of ['D2', 'D3', 'D4', 'D5', 'D6', 'D7']) section(review, id);
  assert.ok(review.includes(String(deck.length)) || review.includes(deck.length.toLocaleString('en-US')), 'review records current deck byte size');
  for (const expression of [/1440\s*[×x]\s*900/, /1280\s*[×x]\s*720/, /390\s*[×x]\s*844/,
    /no[- ](?:JS|JavaScript)|without JavaScript/i, /print/i, /reduced[- ]motion/i, /screenshot/i]) {
    assert.match(review, expression, 'named screenshot-review evidence');
  }
  const rows = inventory(review);
  const ids = await orderedIds(page);
  for (const row of rows) {
    assert.ok(ids.some(id => row.slide.replace(/[`#]/g, '').trim() === id), `inventory slide exists: ${row.slide}`);
    assert.ok(row.claim.replace(/[`\s]/g, '').length > 5, 'inventory describes a claim');
    assert.match(row.date, dateRE, 'inventory claim is dated');
    assert.match(row.source, /https?:\/\/|(?:sessions\/01-fundamentals\/)?(?:cursus\/)?(?:demos|labs)\/[\w./-]+\.(?:md|json|html)/,
      'inventory gives a source URL or a bundled-material path');
    assert.match(row.contested.replace(/[`*]/g, '').trim(), /^(?:yes|no)\b/i, 'contested status is yes or no');
    assert.ok(normal(row.sourceSection).length > 2, 'inventory names the supporting source section');
    assert.ok(normal(row.outcome).length > 2, 'inventory records review outcome');
    assert.doesNotMatch(row.outcome, /^(?:pending|TODO|TBD|unchecked|not checked)\b/i, 'claim inventory is completed review evidence');
  }
  const hrefs = await page.locator('a[href]').evaluateAll(ns => ns.map(n => n.getAttribute('href')).filter(h => /^https?:/i.test(h)));
  for (const href of new Set(hrefs)) {
    assert.ok(rows.some(row => row.source.includes(href)), `A1 inventory covers external href ${href}`);
  }
  // Each required recent topic must have its own claim evidence, not just a
  // footer bibliography. Completeness inside each slide is independently reviewed.
  for (const id of ['rlvr', 'sharpen-or-expand', 'effort-dials', 'effort-demo', 'overthinking',
    'cot-faithfulness', 'addition-36-59', 'tool-cues', 'internal-representations', 'kepler', 'simulators']) {
    assert.ok(rows.some(row => row.slide.includes(id)), `${id}: recent-claim inventory row`);
  }
  for (const id of contestedTopics) {
    assert.ok(rows.some(row => row.slide.includes(id) && /^yes\b/i.test(row.contested.replace(/[`*]/g, '').trim())),
      `${id}: inventory acknowledges the contested claim`);
  }
});

function timingPlan(notes) {
  let total = 0;
  const budgets = new Map();
  for (const { id, minutes, text } of notes) {
    const n = Number(minutes);
    assert.ok(String(minutes).trim() && Number.isFinite(n) && n > 0, `${id}: positive finite minutes`);
    const words = normal(text).split(/\s+/).filter(Boolean).length;
    assert.ok(words > 0 && words <= 150 * n, `${id}: ${words} cue words exceeds 150 words/minute for ${n} min`);
    total += n;
    const name = topicOf(id);
    budgets.set(name, (budgets.get(name) || 0) + n);
  }
  assert.ok(Math.abs(total - 45) < 1e-9, `minute plan totals ${total}, expected 45 including activities`);
  assert.ok(budgets.get('search') >= 7 && budgets.get('search') <= 9, 'about 8 min for search lab and predict pause');
  assert.equal(budgets.get('effort-demo'), 6, 'six-minute effort demo/replay');
  const worldLab = (budgets.get('kepler') || 0) + (budgets.get('repo-model') || 0);
  assert.ok(worldLab >= 6 && worldLab <= 7, '6-7 min world-model lab, split across Kepler and repo');
  return budgets;
}

test('A2-plan: every slide has concise cues and the activities are included in exactly 45 minutes', async t => {
  const page = await pageFor(t);
  await orderedIds(page);
  const notes = await slides(page).evaluateAll(nodes => nodes.map(slide => {
    const notes = slide.querySelector(':scope > details.notes[data-minutes]');
    if (!notes) return { id: slide.id, minutes: '', text: '' };
    const clone = notes.cloneNode(true);
    clone.querySelector('summary')?.remove();
    return { id: slide.id, minutes: notes.dataset.minutes, text: clone.textContent };
  }));
  timingPlan(notes);
  for (const id of ['search', 'effort-demo', 'kepler', 'repo-model']) {
    const cue = normal(notes.filter(n => topicOf(n.id) === id).map(n => n.text).join(' '));
    assert.match(cue, id === 'search' ? /predict|bet|pause/i : id === 'effort-demo' ? /demo|replay/i : /lab|widget|panel|planner|run/i,
      `${id}: notes budget the activity, not only the prose`);
  }
  t.diagnostic('Only the minute plan is proven. A2 live delivery remains an instructor obligation; no agent-written rehearsal is required.');
});
