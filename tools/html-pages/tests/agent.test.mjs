import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdir, readFile, realpath, stat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { chromium } from '../browser.mjs';
import { openPage, repoRoot, count, eventually, focused, assertCollected } from './component-helpers.mjs';

// The Act III deck opens Act II's last run: the model only wrote text, the harness ran every tool,
// re-sent the run on every call, and ended it when a reply held no tool call. Five questions, one per
// part, pinned as numbered badges on the spine, Act III's mechanism, repeated on every slide with the
// current part lit; the close opens each badge into a habit. Five slides ask the room to predict, and
// each reveal shows the room's pick beside what the recording did. Every number is a recording's.
// These are structural floors next to check-page and a person's review of the prose.
const cursus = path.join(repoRoot, 'sessions/01-fundamentals/cursus');
const runs = path.join(cursus, 'fixtures/runs');
const recorded = path.join(cursus, 'demos/agent/recorded');
const file = path.join(cursus, '03-agent.html');
const artifacts = path.join(repoRoot, 'artifacts/html-pages/agent');
const viewports = [
  { width: 1440, height: 900 },
  { width: 1280, height: 720 },
  { width: 390, height: 844 },
];
const order = ['harness', 'two-harnesses', 'resend', 'long-run', 'prefix', 'gate', 'stop', 'ladder', 'time-horizons', 'wrap'];
const questions = ['Who runs the tools?', 'What does each call see?', 'What loads before you type?', 'What may it run?', 'When does it stop?'];
// Each part's slides, in order; the landscape and the close sit after part 5.
const parts = [
  { id: 'two-harnesses', part: 1 },
  { id: 'resend', part: 2 },
  { id: 'long-run', part: 2 },
  { id: 'prefix', part: 3 },
  { id: 'gate', part: 4 },
  { id: 'stop', part: 5 },
];
const landscape = ['ladder', 'time-horizons'];
// The slides that ask the room first: the prefix of their data attributes and the chip the run answers.
const predicts = [
  { id: 'harness', p: 'hn', answer: '3' },
  { id: 'two-harnesses', p: 'rp', answer: 'same loop, other steps' },
  { id: 'resend', p: 'rs', answer: 'about 20k' },
  { id: 'prefix', p: 'px', answer: '~10k' },
  { id: 'stop', p: 'rp', answer: 'stop and report' },
];
// Only research claims keep a source on the face.
const cited = ['time-horizons'];
// About 30 to 45 words of prose on a face; pictures, controls and the source line are not prose.
const faceWords = 48;
const notProse = ['h2', '.eyebrow', '.cite', '.spine-wrap', '[role="img"]', 'table', 'blockquote', 'button', '[role="group"]'];
const norm = value => value.normalize('NFKC').replace(/[‘’]/g, "'").replace(/[“”]/g, '"')
  .replace(/[−–]/g, '-').replace(/\s+/g, ' ').trim().toLowerCase();
const words = text => (text.match(/[\p{L}\p{N}]+(?:['.\-/][\p{L}\p{N}]+)*/gu) || []).length;
const fmt = n => n.toLocaleString('en-US');
const topic = (page, id) => page.locator(`section[data-slide]#${id}`);
const slides = page => page.locator('main[data-deck] section[data-slide]');
const notes = slide => slide.locator('details.speaker-notes');
const notesText = async slide => norm(await notes(slide).evaluate(el => {
  const copy = el.cloneNode(true);
  copy.querySelector('summary')?.remove();
  return copy.textContent;
}));
async function face(slide, extra = []) {
  return norm(await slide.evaluate((el, extra) => {
    const copy = el.cloneNode(true);
    copy.querySelectorAll(['details.speaker-notes', 'script', 'svg', '[hidden]', '[aria-hidden="true"]',
      '.visually-hidden', ...extra].join(', ')).forEach(node => node.remove());
    return copy.textContent;
  }, extra));
}
// The labels of a slide's pictures (not the spine), one per SVG text, so numbers never run together.
const labels = slide => slide.evaluate(el => [...el.querySelectorAll('svg:not(.spine) text')]
  .map(text => text.textContent.replace(/\s+/g, ' ').trim()).filter(Boolean).join(' | ')).then(norm);
const json = async file => JSON.parse(await readFile(file, 'utf8'));
const jsonl = async file => (await readFile(file, 'utf8')).split('\n').filter(Boolean).map(line => JSON.parse(line));
// One usage block per model call: Claude Code repeats it on every event of the same message id.
async function callsOf(raw) {
  const calls = new Map();
  for (const event of await jsonl(raw)) if (event.type === 'assistant' && !calls.has(event.message.id)) calls.set(event.message.id, event.message.usage);
  return [...calls.values()];
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
      if (getComputedStyle(node).position === 'absolute' && node.classList.contains('visually-hidden')) continue;
      if (node.clientWidth && node.scrollWidth > node.clientWidth + 1) result.push(node.tagName);
    }
    return result;
  });
  assert.deepEqual(problems, [], 'open notes have no horizontal overflow');
}

// Run in the page. One copy of the spine as a viewer sees it: each badge's state by its number and how
// many parts are lit.
function readSpine(svg) {
  const state = el => ['all', 'done', 'now', 'next'].find(name => el.classList.contains(name));
  const badges = [...svg.querySelectorAll('.badge')].filter(badge => !badge.closest('.habits'));
  return {
    badges: Object.fromEntries(badges.map(badge => [badge.querySelector('.n').textContent, state(badge)])),
    lit: svg.querySelectorAll(':is(.node, .track, .gate, .part3, .harness, path, rect).now').length,
  };
}
// The drawn shapes of a copy, without the close's habits: copies differ only in their classes.
function geometry(svg) {
  return [...svg.querySelectorAll('rect, path, circle')].filter(el => !el.closest('.habits'))
    .map(el => ['x', 'y', 'width', 'height', 'd', 'cx', 'cy', 'r'].map(name => el.getAttribute(name) ?? '').join(' '));
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
    const talk = await notesText(slide);
    assert.ok(words(talk) >= 40, `#${id}: notes carry the talk track the instructor reads aloud`);
    assert.doesNotMatch(talk, /\b(?:goal|driving):/, `#${id}: no Goal or Driving labels`);
    assert.match(talk, /^(?:talk track|predict question)\b/, `#${id}: notes open on the talk track`);
    assert.match(talk, /\btalk track: /, `#${id}: a talk track`);
    assert.match(talk, /\btransition\b[^.:]*: /, `#${id}: a transition`);
    assert.ok((talk.match(/background for you, not for the slides/g) || []).length <= 1, `#${id}: at most one background line`);
  }
  await count(page.locator('[data-minutes]'), 0);
  // Timing lives in the run of show. METR's chart measures tasks in minutes and hours: data, not timing.
  const text = await page.locator('body').evaluate(el => {
    const copy = el.cloneNode(true);
    copy.querySelector('section#time-horizons')?.remove();
    return copy.textContent;
  });
  assert.doesNotMatch(text, /\bminutes?\b|\b\d+\s?min\b/i, 'no minutes on slides or in notes');
  assert.match(norm(await page.locator('.masthead').innerText()), /act iii/);
  await assertCollected('agent');
});

test('D1: slide faces are sparse and carry no recording artefacts', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  await count(page.locator('footer'), 0);
  for (const slide of await slides(page).all()) {
    const id = await slide.getAttribute('id');
    assert.doesNotMatch(await face(slide), /\brecorded\b|fixtures\/|\.json\b|\b20\d\d-\d\d-\d\d\b|\bclaude code 2\.|codex-cli/, `#${id}: no provenance on the face`);
    await count(slide.locator('.drive'), 0);
    await count(slide.locator('h2'), 1);
    const body = await face(slide, notProse);
    assert.ok(words(body) <= faceWords, `#${id}: ${words(body)} words on the face (at most ${faceWords})`);
  }
  assert.deepEqual(await page.locator('main .cite').evaluateAll(els => els.map(el => el.closest('section').id)), cited,
    'a short source only where the slide makes a research claim');
  for (const source of await page.locator('main .cite').all()) {
    assert.ok(await source.locator('a[href^="https://"]').count() >= 1, 'the source links its origin');
    assert.match(norm(await source.textContent()), /^source: .+, 20\d\d\b/, 'author, title, link, year');
  }
  // No lab on a face: the replay is the live demo's fallback, in the notes.
  for (const link of await page.locator('section[data-slide] a[href*="labs/"]').all()) {
    assert.equal(await link.evaluate(el => !!el.closest('details.speaker-notes')), true, `${await link.getAttribute('href')} sits in the notes`);
  }
});

test('D2: the act opens on Act II’s last run and keeps to its order', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  assert.deepEqual(await idsOf(page), order);
  const opener = topic(page, 'harness');
  assert.match(norm(await opener.locator('h2').textContent()), /^not the model: the harness ran the tests\.$/);
  // The notes pick up Act II's close word for word.
  const act2 = await readFile(path.join(cursus, '02-thinking.html'), 'utf8');
  assert.ok(act2.includes('Who ran the tests on the last slide? Not the model. Agent = model + harness.'));
  assert.ok((await notesText(opener)).includes(norm('Who ran the tests on the last slide? Not the model. Agent = model + harness.')));
});

test('D2: the opening spine is the overview: every badge unanswered, each part linking its slide', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  const spine = topic(page, 'harness').locator('svg.spine');
  await count(spine, 1);
  assert.equal(await spine.getAttribute('role'), null, 'the overview is navigation, not an image');
  const links = await spine.locator('a').evaluateAll(els => els.map(el => [el.getAttribute('href'), el.getAttribute('aria-label')]));
  const expected = questions.map((question, i) => [`#${parts.find(p => p.part === i + 1).id}`, `Part ${i + 1} · ${question}`]);
  assert.deepEqual([...links].sort(), [...expected].sort(), 'each part opens its first slide');
  assert.deepEqual(await spine.evaluate(readSpine), { badges: { 1: 'all', 2: 'all', 3: 'all', 4: 'all', 5: 'all' }, lit: 0 });
  await count(topic(page, 'harness').locator('figure.spine-wrap figcaption.visually-hidden'), 1);
  // The five questions in words, beside their badge numbers.
  assert.deepEqual((await topic(page, 'harness').locator('.qs li').allTextContents()).map(norm),
    questions.map((q, i) => norm(`${i + 1}${q}`)));
});

test('D2: every other slide repeats the spine as an image, its question current and its part lit', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  const reference = await topic(page, 'harness').locator('svg.spine').evaluate(geometry);
  await count(page.locator('svg.spine [id]'), 0);
  const labels = [];
  for (const id of order.slice(1)) {
    const slide = topic(page, id);
    const spine = slide.locator('svg.spine');
    await count(spine, 1);
    assert.deepEqual(await spine.evaluate(geometry), reference, `${id}: the copy has the same geometry`);
    assert.equal(await spine.getAttribute('role'), 'img');
    await count(spine.locator('a'), 0);
    const label = norm(await spine.getAttribute('aria-label'));
    labels.push(label);
    const seen = await spine.evaluate(readSpine);
    const part = parts.find(p => p.id === id)?.part;
    if (part) {
      const badge = n => n === part ? 'now' : n < part ? 'done' : 'next';
      assert.deepEqual(seen.badges, Object.fromEntries([1, 2, 3, 4, 5].map(n => [n, badge(n)])), `${id}: answered up to question ${part}`);
      assert.ok(seen.lit > 0, `${id}: the parts question ${part} is about are lit`);
      assert.ok(norm(await slide.locator(':scope > .eyebrow').textContent()).startsWith(norm(`Part ${part} · ${questions[part - 1]}`)),
        `${id}: the eyebrow names part ${part}`);
    } else if (landscape.includes(id)) {
      assert.deepEqual(seen.badges, { 1: 'done', 2: 'done', 3: 'done', 4: 'done', 5: 'done' }, `${id}: all five answered`);
      assert.match(norm(await slide.locator(':scope > .eyebrow').textContent()), /^the 2026 landscape/);
    } else {
      assert.deepEqual(seen.badges, { 1: 'now', 2: 'now', 3: 'now', 4: 'now', 5: 'now' }, 'the close opens every badge');
    }
    const wrap = slide.locator('.spine-wrap');
    assert.equal(await wrap.getAttribute('role'), 'region');
    assert.ok(await wrap.getAttribute('aria-label'), 'the scrolling wrapper is labelled');
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
      const badge = [...svg.querySelectorAll('.badge')].filter(el => !el.closest('.habits')).find(el => el.querySelector('.n').textContent === numbers[0]);
      return {
        numbers,
        habit: [...svg.querySelectorAll('.habits .habit')].filter(el => inside(box, el)).map(el => el.textContent.trim()).join(' '),
        fromBadge: !!big && !!badge && Math.abs(Number(big.getAttribute('cx')) - Number(badge.querySelector('circle').getAttribute('cx'))) < 0.5,
      };
    });
  });
  assert.equal(habits.length, 5, 'five habits');
  assert.deepEqual(habits.map(habit => habit.numbers[0]).sort(), ['1', '2', '3', '4', '5']);
  for (const habit of habits) {
    assert.ok(words(habit.habit) > 0 && words(habit.habit) <= 6, `habit ${habit.numbers[0]} is a short phrase: ${habit.habit}`);
    assert.ok(habit.fromBadge, `habit ${habit.numbers[0]} opens from badge ${habit.numbers[0]}`);
  }
  assert.match(await face(close), /next · act iv/);
});

test('D3: the opener replays Act II’s run, as recorded', async t => {
  const run = await json(path.join(runs, 'flipped-sense-claude.json'));
  const calls = await callsOf(path.join(runs, 'raw/flipped-sense-claude.jsonl'));
  const tools = run.steps.filter(step => step.type === 'tool_call');
  const said = run.steps.filter(step => step.type === 'message').map(step => step.text);
  const results = run.steps.filter(step => step.type === 'tool_result').map(step => step.text);
  assert.equal(calls.length, 3);
  assert.deepEqual(tools.map(step => step.tool), ['Bash', 'Edit', 'Bash']);
  const pytests = tools.filter(step => step.tool === 'Bash' && step.input.command.includes('uv run pytest')).length;
  assert.equal(pytests, 2);
  const page = await pageFor(t, { javaScriptEnabled: false });
  const lanes = norm(await topic(page, 'harness').locator('svg:not(.spine)').first().evaluate(el => el.textContent));
  assert.ok(results[0].includes('1 failed, 29 passed') && results.at(-1).includes('30 passed'));
  assert.match(lanes, /1 failed, 29 passed/);
  assert.match(lanes, /30 passed/);
  assert.ok(lanes.includes(norm(said[0])), 'call 2’s sentence, verbatim');
  assert.ok(lanes.includes(norm(said.at(-1).split('\n')[0].split('. ')[0])), 'call 3’s first sentence, verbatim');
  const last = run.steps.at(-1).t_ms / 1000;
  assert.match(norm(await topic(page, 'harness').evaluate(el => el.textContent)),
    new RegExp(`${calls.length} replies = ${calls.length} model calls ?${tools.length} tool runs \\(${pytests} test runs\\)`));
  // The time axis ends at the run's last event.
  assert.ok((await labels(topic(page, 'harness'))).includes(`${Math.round(last)} s`), 'the axis spans the run');
});

test('D3: the live demo’s notes carry the exact commands and Act II’s prompt, and the lanes count the recorded tools', async t => {
  const meta = await json(path.join(runs, 'raw/flipped-sense-claude.meta.json'));
  const claude = await json(path.join(runs, 'flipped-sense-claude.json'));
  const codex = await json(path.join(runs, 'flipped-sense-codex.json'));
  const page = await pageFor(t, { javaScriptEnabled: false });
  const slide = topic(page, 'two-harnesses');
  const pres = await notes(slide).locator('pre[id]').evaluateAll(els => els.map(el => ({ id: el.id, text: el.textContent })));
  const copies = await notes(slide).locator('button[data-copy]').evaluateAll(els => els.map(el => el.dataset.copy));
  assert.deepEqual(copies, pres.map(pre => pre.id), 'each command and the prompt has its Copy button');
  assert.ok(pres.some(pre => pre.text === meta.scenario.prompt), 'the prompt, word for word the recorded one');
  const launch = pres.map(pre => pre.text).filter(text => /\b(?:claude|codex) /.test(text) && text.includes('agent_demo.py reset loop'));
  assert.equal(launch.length, 2, 'one launch command per harness');
  // Claude Code starts asking, whatever the instructor's own default mode: the prompts are the demo.
  assert.ok(launch.some(text => /\bclaude --model claude-opus-5-5 --effort medium --permission-mode default\b/.test(text)));
  assert.ok(launch.some(text => /\bcodex -m gpt-6-astra\b/.test(text) && text.includes('--sandbox workspace-write')));
  for (const text of launch) assert.match(text, /reset loop --work-root (\/tmp\/cursus-s1-[a-z]+) && cd \1\/loop &&/, 'reset, then open the fresh export');
  // The runbook rehearses the same two lines and the same prompt.
  const runbook = await readFile(path.join(cursus, 'demos/agent/loop.md'), 'utf8');
  const live = runbook.slice(runbook.indexOf('## Live in class'));
  for (const text of launch) assert.ok(live.includes(text), `loop.md's live section has: ${text.slice(0, 60)}…`);
  assert.ok(live.includes(meta.scenario.prompt), 'loop.md has the prompt');
  const toolRuns = run => run.steps.filter(step => step.type === 'tool_call').length;
  const shown = await labels(slide);
  assert.match(shown, new RegExp(`(?:^|\\| )${toolRuns(claude)} tool runs\\b`));
  assert.match(shown, new RegExp(`(?:^|\\| )${toolRuns(codex)} tool runs\\b`));
  assert.match(shown, /kmaximize → kminimize/);
});

test('D3: #resend and #long-run draw their recordings to scale', async t => {
  const calls = await callsOf(path.join(runs, 'raw/flipped-sense-claude.jsonl'));
  const long = await json(path.join(runs, 'context-bomb-claude.json'));
  const inputs = long.steps.filter(step => step.tokens?.input != null).map(step => step.tokens.input);
  const page = await pageFor(t, { javaScriptEnabled: false });
  // Each bar: its cached part and its new part, on one scale for all three calls.
  const bars = await topic(page, 'resend').locator('.rs-bar').evaluateAll(els => els.map(bar => ({
    title: bar.querySelector('title').textContent,
    cached: Number(bar.querySelector('rect.rs-cached').getAttribute('width')),
    fresh: Number(bar.querySelector('rect.rs-new').getAttribute('width')),
  })));
  assert.equal(bars.length, 3);
  const scale = bars[0].cached / calls[0].cache_read_input_tokens;
  bars.forEach((bar, i) => {
    const call = calls[i], total = call.cache_read_input_tokens + call.cache_creation_input_tokens + call.input_tokens;
    assert.ok(bar.title.includes(fmt(total)) && bar.title.includes(fmt(call.cache_read_input_tokens)) && bar.title.includes(fmt(call.cache_creation_input_tokens)), bar.title);
    assert.ok(Math.abs(bar.cached - call.cache_read_input_tokens * scale) < 1, `call ${i + 1}: cached part to scale`);
    assert.ok(Math.abs(bar.fresh - call.cache_creation_input_tokens * scale) < 1, `call ${i + 1}: new part to scale`);
  });
  // #long-run: every one of the 26 calls, on one scale: the previous call re-sent, then what was appended.
  const rows = await topic(page, 'long-run').locator('.lr-bar').evaluateAll(els => els.map(bar => ({
    title: bar.querySelector('title').textContent,
    resent: Number(bar.querySelector('rect.lr-cached')?.getAttribute('width') ?? 0),
    added: Number(bar.querySelector('rect.lr-new').getAttribute('width')),
  })));
  assert.equal(rows.length, inputs.length);
  const unit = rows.at(-1).resent / inputs.at(-2);
  rows.forEach((row, i) => {
    const before = i ? inputs[i - 1] : 0;
    assert.ok(row.title.includes(fmt(inputs[i])) && row.title.includes(fmt(inputs[i] - before)), row.title);
    assert.ok(Math.abs(row.resent - before * unit) < 1, `call ${i + 1}: the re-sent part to scale`);
    assert.ok(Math.abs(row.added - (inputs[i] - before) * unit) < 1, `call ${i + 1}: the appended part to scale`);
  });
  const longText = norm(await topic(page, 'long-run').evaluate(el => el.textContent));
  assert.equal(inputs.length, 26);
  for (const n of [inputs[0], inputs.at(-1)]) assert.ok(longText.includes(fmt(n)), fmt(n));
  // The rule given in call 1 still held at the last call, in both CLIs.
  for (const vendor of ['claude', 'codex']) {
    assert.equal((await json(path.join(runs, `raw/context-bomb-${vendor}.meta.json`))).outcome.final_ends_with_rule, true, vendor);
  }
  assert.match(longText, /-- checked/);
});

test('D3: #prefix and #stop show the recorded numbers', async t => {
  // #prefix draws one measurement only: Claude Code's own /context, captured before and after adding
  // one noisy MCP server (its tools deferred, as installed; then loaded, with tool search off).
  const captures = (await readFile(path.join(recorded, 'bomb-claude-run1-context-before.txt'), 'utf8') +
    await readFile(path.join(recorded, 'bomb-claude-run1-context-after.txt'), 'utf8')).split(/^\$ /m).filter(Boolean).map(block => ({
    total: block.match(/\*\*Tokens:\*\* ([\d.]+k)/)[1],
    rows: Object.fromEntries([...block.matchAll(/^\| ([^|]+?) \| ([\d.]+k?) \|/gm)].map(m => [m[1], m[2]])),
  }));
  assert.deepEqual(captures.map(c => c.total), ['13k', '14.6k', '36.5k'], 'before; with the server, tools deferred; tools loaded');
  const [, deferred, loaded] = captures;
  assert.equal(deferred.rows['MCP server instructions'], '1.6k');
  assert.equal(deferred.rows['MCP tools (deferred)'], '8k');
  assert.deepEqual([loaded.rows['MCP server instructions'], loaded.rows['MCP tools']], ['1.6k', '8k']);
  const page = await pageFor(t, { javaScriptEnabled: false });
  const drawn = await labels(topic(page, 'prefix'));
  for (const n of ['13k', '14.6k', '1.6k', '8k', '9.6k', '2.7k', '7.7k']) assert.ok(drawn.includes(n), `#prefix draws ${n}`);
  // With tool search off, Claude Code also loaded its own deferred tools: that capture is told, not drawn.
  assert.match(await notesText(topic(page, 'prefix')), /36\.5k/);
  assert.doesNotMatch(await face(topic(page, 'prefix')), /17,233|18,909|40,377|1,676|23,144/, 'the billed totals stay in the notes: one measure on the face');
  // Codex: the same server adds nothing, in /status and in every recorded pair.
  const status = async name => (await readFile(path.join(recorded, name), 'utf8')).match(/Context window:.*\(([\d.]+K) used/)[1];
  assert.equal(await status('bomb-codex-run1-status-after.txt'), await status('bomb-codex-run1-status-before.txt'));
  const codex = async name => (await jsonl(path.join(recorded, name))).filter(event => event.type === 'turn.completed')
    .reduce((sum, event) => sum + event.usage.input_tokens + event.usage.output_tokens, 0);
  for (const run of [1, 2]) assert.equal(await codex(`bomb-codex-run${run}-with.jsonl`), await codex(`bomb-codex-run${run}-without.jsonl`), `Codex run ${run}: +0`);
  assert.match(await notesText(topic(page, 'prefix')), /13\.8k/, 'Codex’s /status in the notes');
  // #gate: who let each tool call through, as the run's own log records it.
  const decisions = (await jsonl(path.join(runs, 'raw/flipped-sense-claude.jsonl'))).flatMap(event => event.tool_result_meta ?? [])
    .map(meta => meta.permission_decision);
  assert.deepEqual(decisions.map(d => [d.decision, d.source, d.reason_type]), [['accept', 'config', 'rule'], ['accept', 'config', 'mode'], ['accept', 'config', 'rule']]);
  assert.match(await labels(topic(page, 'gate')), /rule: \| bash allowed .*mode: \| accept edits .*rule: \| bash allowed/);
  // The impossible task: the two contracts, and both agents' stops, with no edit.
  const stop = await labels(topic(page, 'stop'));
  assert.match(stop, /≤ 400/);
  assert.match(stop, /485/);
  for (const vendor of ['claude', 'codex']) {
    const run = await json(path.join(runs, `impossible-${vendor}.json`));
    const meta = await json(path.join(runs, `raw/impossible-${vendor}.meta.json`));
    assert.deepEqual(meta.changed_files, [], `${vendor} changed nothing`);
    const n = run.steps.filter(step => step.type === 'tool_call').length;
    assert.match(stop, new RegExp(`(?:^|\\| )${n} tool runs\\b`), `${vendor}: ${n} tool runs`);
  }
});

test('D4: the replay fallbacks in the notes open their recordings in the replay lab', async t => {
  const page = await pageFor(t);
  const ids = new Set();
  for (const id of ['two-harnesses', 'stop']) {
    for (const href of await notes(topic(page, id)).locator('a[href*="agent-loop.html#run="]').evaluateAll(els => els.map(el => el.getAttribute('href')))) ids.add(href);
  }
  assert.ok([...ids].some(href => href.endsWith('#run=flipped-sense-claude')) && [...ids].some(href => href.endsWith('#run=flipped-sense-codex')),
    'Act II’s run and its Codex twin');
  for (const href of ids) {
    await page.goto(new URL(href, pathToFileURL(file)).href);
    const run = href.split('#run=')[1];
    assert.equal(await page.locator('#run-select').inputValue(), run);
    assert.equal(await page.locator(`[data-run-panel="${run}"]`).isVisible(), true, `${run} is shown`);
  }
});

async function localLinks(page) {
  const root = await realpath(cursus);
  for (const link of await page.locator('a[href]').all()) {
    const href = await link.getAttribute('href');
    if (/^https?:/i.test(href)) continue;
    if (href.startsWith('#')) {
      await count(page.locator(`[id="${decodeURIComponent(href.slice(1))}"]`), 1);
      continue;
    }
    assert.ok(!/^(?:[a-z][a-z\d+.-]*:|\/)/i.test(href), `local link must be relative: ${href}`);
    const url = new URL(href, pathToFileURL(file));
    const target = await realpath(fileURLToPath(url));
    const relative = path.relative(root, target);
    assert.ok(relative !== '..' && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative), `local target stays in cursus: ${href}`);
    assert.equal((await stat(target)).isFile(), true, `local target exists: ${href}`);
  }
}

test('D4: relative links resolve inside the session', async t => {
  await localLinks(await pageFor(t, { javaScriptEnabled: false }));
});

test('D4: each part on the opening spine opens its own slide', async t => {
  const page = await pageFor(t, { viewport: viewports[0] });
  for (const { id } of parts.filter((part, i) => parts.findIndex(other => other.part === part.part) === i)) {
    await goTo(page, 'harness');
    await topic(page, 'harness').locator(`svg.spine a[href="#${id}"]`).click();
    await activeSlide(page, id);
  }
});

// The predicts. A pointer press hands focus back to the slide, so a clicker or the arrow keys still
// turn it; a key press on a focused control acts on the control and leaves the deck where it is.
async function stillTurns(page, id) {
  await page.keyboard.press('ArrowRight');
  await activeSlide(page, order[order.indexOf(id) + 1]);
  await goTo(page, id);
}
async function bigEnough(slide) {
  const small = await slide.evaluate(el => [...el.querySelectorAll('button')]
    .filter(button => !button.closest('details') && button.checkVisibility())
    .map(button => ({ name: button.textContent.trim(), ...button.getBoundingClientRect().toJSON() }))
    .filter(box => box.width < 43.5 || box.height < 43.5).map(box => `${box.name}: ${box.width}×${box.height}`));
  assert.deepEqual(small, [], 'every control is at least 44 × 44 px');
}
// What the room sees of a predict: which chips are marked, whether the run shows, and whether a mark
// that reads as "right" (a ✓) sits on the room's pick.
function readPredict(slide, p) {
  return slide.evaluate((el, p) => {
    const root = el.querySelector(`[data-${p}]`);
    const hidden = [...el.querySelectorAll(`[data-${p}-run], .${p}-ans`)];
    const chips = [...el.querySelectorAll(`[data-${p}-chip]`)];
    const tick = chip => [getComputedStyle(chip, '::before').content, getComputedStyle(chip, '::after').content, chip.textContent].join(' ').includes('✓');
    // Teal is what the run did; the room's pick never wears it.
    const probe = document.createElement('i');
    probe.style.color = 'var(--accent)';
    document.body.append(probe);
    const accent = getComputedStyle(probe).color;
    probe.remove();
    const teal = chip => getComputedStyle(chip).borderTopColor === accent;
    return {
      state: root.getAttribute(`data-${p}-state`),
      shown: hidden.length > 0 && hidden.every(node => getComputedStyle(node).visibility === 'visible'),
      none: hidden.every(node => getComputedStyle(node).visibility === 'hidden'),
      pressed: chips.filter(chip => chip.getAttribute('aria-pressed') === 'true').map(chip => chip.textContent.trim()),
      ticked: chips.filter(chip => chip.getAttribute('aria-pressed') === 'true' && (tick(chip) || teal(chip))).map(chip => chip.textContent.trim()),
    };
  }, p);
}

for (const viewport of viewports.slice(0, 2)) {
  const size = `${viewport.width}×${viewport.height}`;
  for (const { id, p, answer } of predicts) {
    test(`D5: #${id}: the room picks, the run is revealed beside its pick, then hidden again, at ${size}`, async t => {
      const page = await pageFor(t, { viewport });
      await goTo(page, id);
      const slide = topic(page, id);
      const chips = slide.locator(`[data-${p}-chip]`);
      const reveal = slide.locator(`[data-${p}-reveal]`), reset = slide.locator(`[data-${p}-reset]`);
      await eventually(async () => assert.equal((await readPredict(slide, p)).none, true, 'the run starts hidden'));
      assert.deepEqual((await readPredict(slide, p)).pressed, []);
      await bigEnough(slide);
      // The room's pick: a wrong one where the run answers a chip, so the reveal must not mark it right.
      const texts = (await chips.allTextContents()).map(text => text.trim());
      const wrong = texts.find(text => text !== answer);
      const chip = text => chips.filter({ hasText: text }).first();
      await chip(texts.find(text => text !== wrong)).click();
      await chip(wrong).click();
      assert.deepEqual((await readPredict(slide, p)).pressed, [wrong], 'one pick at a time');
      await stillTurns(page, id);
      await reveal.click();
      await eventually(async () => {
        const seen = await readPredict(slide, p);
        assert.equal(seen.shown, true, 'the run shows');
        assert.deepEqual(seen.pressed, [wrong], 'beside the room’s pick');
        assert.deepEqual(seen.ticked, [], 'the room’s pick carries no ✓ and no teal');
      });
      assert.ok(norm(await slide.locator(`[data-${p}-status]`).textContent()).length > 0, 'the reveal is announced');
      // After the reveal the room's pick stays where it was.
      await chip(texts.find(text => text !== wrong)).click({ force: true }).catch(() => {});
      assert.deepEqual((await readPredict(slide, p)).pressed, [wrong], 'the pick is frozen after the reveal');
      await bigEnough(slide);
      await stillTurns(page, id);
      await reset.click();
      await eventually(async () => {
        const seen = await readPredict(slide, p);
        assert.equal(seen.none, true, 'Reset hides the run');
        assert.deepEqual(seen.pressed, [], 'Reset clears the pick');
      });
      await stillTurns(page, id);
      // By keyboard: the key acts on the control, and the deck stays put.
      await reveal.focus();
      await page.keyboard.press('Space');
      await activeSlide(page, id);
      await eventually(async () => assert.equal((await readPredict(slide, p)).shown, true));
      await focused(reset);
      await page.keyboard.press('Enter');
      await activeSlide(page, id);
      await eventually(async () => assert.equal((await readPredict(slide, p)).none, true));
    });
  }

  test(`D5: Copy in the demo's notes puts the exact text on the clipboard, at ${size}`, async t => {
    const page = await pageFor(t, { viewport, permissions: ['clipboard-read', 'clipboard-write'] });
    await goTo(page, 'two-harnesses');
    const disclosure = notes(topic(page, 'two-harnesses'));
    await disclosure.locator(':scope > summary').click();
    for (const button of await disclosure.locator('button[data-copy]').all()) {
      const source = await disclosure.locator(`pre#${await button.getAttribute('data-copy')}`).textContent();
      await button.click();
      await eventually(async () => assert.equal(await page.evaluate(() => navigator.clipboard.readText()), source));
      assert.equal(norm(await button.textContent()), 'copied');
    }
    await stillTurns(page, 'two-harnesses');
  });
}

// With no script, and on paper, every predict shows the run, and nothing is left to press.
async function endStates(page) {
  for (const { id, p } of predicts) {
    const slide = topic(page, id);
    assert.equal((await readPredict(slide, p)).shown, true, `#${id}: the run shows`);
    assert.equal(await slide.locator(`[data-${p}-reveal]`).isVisible(), false, `#${id}: nothing left to reveal`);
  }
}

test('D5: without JavaScript each predict shows the run, and no slide has a slider', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  await endStates(page);
  for (const control of await page.locator('section[data-slide] :not(details) > button, section[data-slide] button:not(details button)').all()) {
    assert.ok(!(await control.isVisible()) || await control.isDisabled(), `${await control.textContent()}: no dead control`);
  }
  await count(page.locator('section[data-slide] :is(input[type="range"], [role="slider"])'), 0);
});

test('D5: print shows each predict’s run, whatever state the room left it in', async t => {
  const page = await pageFor(t);
  await eventually(async () => assert.equal((await readPredict(topic(page, 'harness'), 'hn')).none, true));
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
          if (node.closest('.visually-hidden')) continue;
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
  test(`D1: every disclosure works by keyboard at ${viewport.width}×${viewport.height}`, { timeout: 120000 }, async t => {
    const page = await pageFor(t, { viewport });
    const ids = await idsOf(page);
    for (const [index, id] of ids.entries()) {
      await goTo(page, id);
      const disclosure = notes(slides(page).nth(index));
      const summary = disclosure.locator(':scope > summary');
      await summary.focus();
      const key = index % 2 ? 'Space' : 'Enter';
      await page.keyboard.press(key);
      await eventually(async () => assert.equal(await disclosure.evaluate(el => el.open), true));
      await activeSlide(page, id);
      await noHorizontalOverflow(page, disclosure);
      await page.keyboard.press(key);
      await eventually(async () => assert.equal(await disclosure.evaluate(el => el.open), false));
      await activeSlide(page, id);
    }
  });
}

test('D1: on a phone the spine scrolls sideways, starting at the current part', async t => {
  const page = await pageFor(t, { viewport: viewports[2] });
  for (const { id } of parts) {
    const wrap = topic(page, id).locator('.spine-wrap');
    await eventually(async () => {
      const state = await wrap.evaluate(el => {
        const frame = el.getBoundingClientRect();
        // The lit parts and their badges; part 1 also tints the whole harness band, which is wider than a phone.
        const lit = [...el.querySelectorAll('svg :is(.node, .gate, .track, .part3, .badge).now')].map(node => node.getBoundingClientRect()).filter(box => box.width);
        const left = Math.min(...lit.map(box => box.left)), right = Math.max(...lit.map(box => box.right));
        return {
          scrolls: el.scrollWidth > el.clientWidth,
          lit: right - left <= frame.width ? left >= frame.left - 1 && right <= frame.right + 1 : Math.abs(left - frame.left) <= 1,
        };
      });
      assert.deepEqual(state, { scrolls: true, lit: true }, `${id}: current part in view`);
    }, `${id}: current part in view`);
  }
});

for (const width of [718, 1046]) {
  test(`D1: in print, ${width} px wide (A4 portrait or landscape), no chart is cut by its scroller`, async t => {
    const page = await pageFor(t, { viewport: { width, height: 900 } });
    await page.emulateMedia({ media: 'print' });
    await eventually(async () => {
      const cut = await page.locator('section[data-slide] [role="region"]').evaluateAll(els => els
        .filter(el => el.querySelector('svg') && el.scrollWidth > el.clientWidth + 1)
        .map(el => `${el.closest('section').id}: ${el.getAttribute('aria-label')}`));
      assert.deepEqual(cut, []);
    });
  });
}

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
