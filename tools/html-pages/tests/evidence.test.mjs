import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdir, readFile, realpath, stat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { chromium } from '../browser.mjs';
import { openPage, repoRoot, count, eventually, focused, assertCollected } from './component-helpers.mjs';

// The Act IV deck merges the plan's Acts IV and V. It opens on Act III's last line, and the students drive
// the lab ladder on P00: before each level, one slide shows the real failure the level guards against and
// the Act III habit it practises (L1 → 4, L2 → 1, L3 → 5, L4 → 3 with 2). The spine is the ladder itself,
// repeated on every slide with the current level lit; the close opens each habit badge into a pill that
// carries the failure behind it. Four slides ask the room to predict, and each reveal shows the room's
// pick beside what really happened. Every number is a recording's, a source's or the P00 data's.
// These are structural floors next to check-page and a person's review of the prose.
const session = path.join(repoRoot, 'sessions/01-fundamentals');
const cursus = path.join(session, 'cursus');
const runs = path.join(cursus, 'fixtures/runs');
const p00 = path.join(session, 'exercises/p00-lab');
const ladder = path.join(session, 'exercises/lab-ladder.html');
const file = path.join(cursus, '04-evidence.html');
const artifacts = path.join(repoRoot, 'artifacts/html-pages/evidence');
const viewports = [
  { width: 1440, height: 900 },
  { width: 1280, height: 720 },
  { width: 390, height: 844 },
];
const order = ['your-turn', 'l1', 'l2', 'catch', 'l3', 'l4', 'debrief', 'gap', 'this-repo', 'wrap'];
// The ladder's stations, left to right, with the Act III habits each level practises.
const stations = ['l1', 'l2', 'l3', 'l4', 'card'];
const habitsOf = { l1: ['4'], l2: ['1'], l3: ['5'], l4: ['3', '2'], card: [] };
const habits = { 1: 'watch what it runs', 2: 'one session per task', 3: 'keep the prefix lean', 4: 'grant the least it needs', 5: '“done” is a claim: check it' };
// The station each slide stands on; the slides after the debrief stand on none (everything done).
const current = { l1: 'l1', l2: 'l2', catch: 'l2', l3: 'l3', l4: 'l4', debrief: 'card' };
const after = ['gap', 'this-repo'];
// The slides that ask the room first, and the chip that what happened answers.
const predicts = [
  { id: 'l2', answer: '50' },
  { id: 'catch', answer: 'none' },
  { id: 'l3', answer: '5' },
  { id: 'l4', answer: '1' },
];
// Only research and incident claims keep a source on the face.
const cited = ['l1', 'l2', 'l4'];
// The slides where the students drive a lab level: their notes carry the lab page's exact commands.
const labSteps = ['l1', 'l2', 'l3', 'l4'];
// About 30 to 45 words of prose on a face; pictures, controls, conditions, labels and the source line are not prose.
const faceWords = 48;
const notProse = ['h2', '.eyebrow', '.cite', '.spine-wrap', 'svg', '[role="img"]', 'table', 'button', '[role="group"]',
  '.cond', '.tag', 'pre', 'figure'];
const norm = value => value.normalize('NFKC').replace(/[‘’]/g, "'").replace(/[“”]/g, '"')
  .replace(/[−–]/g, '-').replace(/\s+/g, ' ').trim().toLowerCase();
const words = text => (text.match(/[\p{L}\p{N}]+(?:['.\-/][\p{L}\p{N}]+)*/gu) || []).length;
const topic = (page, id) => page.locator(`section[data-slide]#${id}`);
const slides = page => page.locator('main[data-deck] section[data-slide]');
const notes = slide => slide.locator('details.speaker-notes');
const notesText = async (slide, { commands = true } = {}) => norm(await notes(slide).evaluate((el, commands) => {
  const copy = el.cloneNode(true);
  copy.querySelector('summary')?.remove();
  if (!commands) copy.querySelectorAll('.notes-prompt').forEach(node => node.remove());
  return copy.textContent;
}, commands));
async function face(slide, extra = []) {
  return norm(await slide.evaluate((el, extra) => {
    const copy = el.cloneNode(true);
    copy.querySelectorAll(['details.speaker-notes', 'script', 'style', '[hidden]', '[aria-hidden="true"]',
      '.visually-hidden', ...extra].join(', ')).forEach(node => node.remove());
    return copy.textContent;
  }, extra));
}
// Everything a viewer can read on a face, pictures included: one entry per SVG text or HTML text node.
const shown = slide => slide.evaluate(el => {
  const out = [];
  const walk = node => {
    if (node.nodeType === Node.TEXT_NODE) { if (node.textContent.trim()) out.push(node.textContent); return; }
    if (!(node instanceof Element) || node.matches('details.speaker-notes, script, style, .visually-hidden, .spine-wrap')) return;
    if (node.matches('svg text')) { out.push(node.textContent); return; }
    node.childNodes.forEach(walk);
  };
  walk(el);
  return out.map(text => text.replace(/\s+/g, ' ').trim()).filter(Boolean).join(' | ');
}).then(norm);
const json = async file => JSON.parse(await readFile(file, 'utf8'));
const csv = async file => {
  const [head, ...rows] = (await readFile(file, 'utf8')).trim().split(/\r?\n/).map(line => line.split(','));
  return rows.map(row => Object.fromEntries(head.map((key, i) => [key.trim(), row[i].trim()])));
};
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

// Run in the page. One copy of the spine as a viewer sees it: each station's state, each habit badge's.
function readSpine(svg) {
  const state = el => ['all', 'done', 'now', 'next'].find(name => el.classList.contains(name));
  return {
    // The box is what the viewer sees lit: read the state on the station's node, and check its wrapper agrees.
    stations: [...svg.querySelectorAll('g.st')].map(st => state(st.querySelector('.node')) === state(st) ? state(st) : `${state(st)}≠${state(st.querySelector('.node'))}`),
    badges: Object.fromEntries([...svg.querySelectorAll('.badge')].filter(badge => !badge.closest('.habits'))
      .map(badge => [badge.querySelector('.n').textContent, state(badge)])),
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
    const talk = await notesText(slide, { commands: false });
    // Read aloud: about 150 to 220 words of talk, the lab commands and the background line aside; the close is short.
    const spoken = talk.split('background for you, not for the slides')[0];
    assert.ok(words(spoken) >= (id === 'wrap' ? 80 : 140) && words(spoken) <= 235, `#${id}: ${words(spoken)} words read aloud`);
    assert.doesNotMatch(talk, /\b(?:goal|driving):/, `#${id}: no Goal or Driving labels`);
    assert.match(talk, /^(?:talk track|predict question)\b/, `#${id}: notes open on the talk track`);
    assert.match(talk, /\btalk track: /, `#${id}: a talk track`);
    assert.match(talk, /\btransition\b[^.:]*: /, `#${id}: a transition`);
    assert.match(talk, /\bpoint (?:at|to)\b/, `#${id}: pointing cues`);
    assert.ok((talk.match(/background for you, not for the slides/g) || []).length <= 1, `#${id}: at most one background line`);
  }
  await count(page.locator('[data-minutes]'), 0);
  // Timing lives in the run of show and the lab page's time boxes.
  assert.doesNotMatch(await page.locator('body').textContent(), /\bminutes?\b|\b\d+\s?min\b/i, 'no minutes on slides or in notes');
  assert.match(norm(await page.locator('.masthead').innerText()), /act iv/);
  await assertCollected('evidence');
});

test('D1: slide faces are sparse and carry no recording artefacts', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  await count(page.locator('footer'), 0);
  for (const slide of await slides(page).all()) {
    const id = await slide.getAttribute('id');
    assert.doesNotMatch(await face(slide), /\brecorded\b|fixtures\/|\.json\b|\b20\d\d-\d\d-\d\d\b|\bclaude code 2\.|codex-cli/, `#${id}: no provenance on the face`);
    await count(slide.locator('h2'), 1);
    const body = await face(slide, notProse);
    assert.ok(words(body) <= faceWords, `#${id}: ${words(body)} words on the face (at most ${faceWords})`);
  }
  assert.deepEqual(await page.locator('main .cite').evaluateAll(els => els.map(el => el.closest('section').id)), cited,
    'a short source only where the slide makes a research or incident claim');
  for (const source of await page.locator('main .cite').all()) {
    assert.ok(await source.locator('a[href^="https://"]').count() >= 1, 'the source links its origin');
    assert.match(norm(await source.textContent()), /^source: .+, 20\d\d\b/, 'author, title, link, year');
  }
  // No lab on a face: the labs the students drive are linked from the notes.
  for (const link of await page.locator('section[data-slide] a[href*="labs/"], section[data-slide] a[href*="exercises/"]').all()) {
    assert.equal(await link.evaluate(el => !!el.closest('details.speaker-notes')), true, `${await link.getAttribute('href')} sits in the notes`);
  }
});

test('D1: every failure slide puts what was asked, what the agent had and the rule on its face', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  for (const id of ['l1', 'l2', 'catch', 'l3', 'l4']) {
    const keys = await topic(page, id).locator('dl.cond dt').allTextContents();
    assert.deepEqual(keys.map(norm), ['asked', 'had', 'rule'], `#${id}: asked, had, rule`);
  }
  // What is drawn from an invented example says so; what is a schematic says so.
  assert.match(await shown(topic(page, 'l1')), /schematic/);
  assert.match(await shown(topic(page, 'catch')), /illustrative/);
  assert.match(await shown(topic(page, 'l2')), /example/);
});

test('D2: the act opens on Act III’s last line and keeps to its order', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  assert.deepEqual(await idsOf(page), order);
  const line = 'Your turn on P00, graded by the evidence, not the message.';
  const act3 = await readFile(path.join(cursus, '03-agent.html'), 'utf8');
  assert.ok(act3.includes(line), 'Act III ends on it');
  assert.ok((await notesText(topic(page, 'your-turn'))).includes(norm(`Act III ended on “${line}”`)));
  assert.equal(norm(await topic(page, 'your-turn').locator('h2').textContent()), norm('Your turn on P00, graded by the evidence.'));
  // Act III's #stop slide promised the faked green; this act measures it.
  assert.ok(act3.includes('false green ▸ Act IV'));
});

test('D2: the opening spine is the overview: every level unanswered, each linking its slide', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  const spine = topic(page, 'your-turn').locator('svg.spine');
  await count(spine, 1);
  assert.equal(await spine.getAttribute('role'), null, 'the overview is navigation, not an image');
  const links = await spine.locator('a').evaluateAll(els => els.map(el => [el.getAttribute('href'), el.getAttribute('aria-label')]));
  assert.deepEqual(links.map(([href]) => href), ['#l1', '#l2', '#l3', '#l4', '#debrief']);
  links.slice(0, 4).forEach(([, label], i) => assert.match(norm(label), new RegExp(`^level ${i + 1} · `)));
  await count(page.locator('svg.spine a'), 5);
  const seen = await spine.evaluate(readSpine);
  assert.deepEqual(seen.stations, stations.map(() => 'all'));
  assert.deepEqual(seen.badges, { 1: 'all', 2: 'all', 3: 'all', 4: 'all', 5: 'all' });
  // Each level carries its Act III habits, in words beside their numbers.
  const text = norm(await spine.evaluate(svg => [...svg.querySelectorAll('text')].map(t => t.textContent).join(' | ')));
  for (const [n, habit] of Object.entries(habits)) if (n !== '2') assert.ok(text.includes(norm(habit)), `habit ${n} named`);
});

test('D2: every other slide repeats the spine as an image, its level current and its habit lit', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  const reference = await topic(page, 'your-turn').locator('svg.spine').evaluate(geometry);
  await count(page.locator('svg.spine [id]'), 0);
  const labels = [];
  for (const id of order.slice(1)) {
    const slide = topic(page, id);
    const spine = slide.locator('svg.spine');
    await count(spine, 1);
    assert.deepEqual(await spine.evaluate(geometry), reference, `${id}: the copy has the same geometry`);
    assert.equal(await spine.getAttribute('role'), 'img');
    await count(spine.locator('a'), 0);
    labels.push(norm(await spine.getAttribute('aria-label')));
    const seen = await spine.evaluate(readSpine);
    const at = current[id] ? stations.indexOf(current[id]) : -1;
    const want = stations.map((key, i) => at < 0 ? 'done' : i < at ? 'done' : i === at ? 'now' : 'next');
    if (id === 'wrap') {
      assert.deepEqual(seen.badges, { 1: 'now', 2: 'now', 3: 'now', 4: 'now', 5: 'now' }, 'the close opens every badge');
      assert.deepEqual(seen.stations, stations.map(() => 'done'), 'the close: every level done');
    } else {
      assert.deepEqual(seen.stations, want, `${id}: stations`);
      for (const [i, key] of stations.entries()) for (const n of habitsOf[key]) assert.equal(seen.badges[n], want[i], `${id}: badge ${n}`);
      if (after.includes(id)) assert.ok(want.every(state => state === 'done'), `${id}: the whole ladder is done`);
    }
    if (current[id]?.startsWith('l')) {
      const level = current[id].slice(1);
      assert.match(norm(await slide.locator(':scope > .eyebrow').textContent()), new RegExp(`^(?:level ${level}|l${level})\\b`), `${id}: the eyebrow names level ${level}`);
    }
    const wrap = slide.locator('.spine-wrap');
    assert.equal(await wrap.getAttribute('role'), 'region');
    assert.ok(await wrap.getAttribute('aria-label'), 'the scrolling wrapper is labelled');
  }
  assert.equal(new Set(labels).size, labels.length, 'each copy describes its own slide');
});

test('D2: the close opens the five badges into five habits, each with the failure behind it', async t => {
  const page = await pageFor(t, { viewport: viewports[0] });
  await goTo(page, 'wrap');
  const pills = await topic(page, 'wrap').locator('svg.spine').evaluate(svg => {
    const inside = (box, el) => {
      const b = el.getBBox(), x = b.x + b.width / 2, y = b.y + b.height / 2;
      return x >= box.x && x <= box.x + box.width && y >= box.y && y <= box.y + box.height;
    };
    return [...svg.querySelectorAll('.habits .pill')].map(pill => {
      const box = pill.getBBox();
      const n = [...svg.querySelectorAll('.habits .bn')].find(el => inside(box, el))?.textContent;
      const big = [...svg.querySelectorAll('.habits .big')].find(el => inside(box, el));
      const badge = [...svg.querySelectorAll('.badge')].filter(el => !el.closest('.habits')).find(el => el.querySelector('.n').textContent === n);
      const texts = [...svg.querySelectorAll('.habits text:not(.bn)')].filter(el => inside(box, el));
      return {
        n,
        habit: texts.filter(el => el.classList.contains('habit')).map(el => el.textContent.trim()).join(' '),
        failure: texts.filter(el => el.classList.contains('fail') && !el.classList.contains('is-plain')).map(el => el.textContent.trim()).join(' '),
        fromBadge: !!big && !!badge && Math.abs(Number(big.getAttribute('cx')) - Number(badge.querySelector('circle').getAttribute('cx'))) < 0.5,
      };
    });
  });
  assert.deepEqual(pills.map(pill => pill.n).sort(), ['1', '2', '3', '4', '5']);
  for (const pill of pills) {
    assert.equal(norm(pill.habit), norm(habits[pill.n]), `pill ${pill.n} names its habit`);
    assert.ok(pill.fromBadge, `pill ${pill.n} opens from badge ${pill.n}`);
    // Habit 2 has no failure of its own: a fresh session is how L4's rule loads.
    if (pill.n !== '2') assert.ok(words(pill.failure) > 0 && words(pill.failure) <= 7, `pill ${pill.n}: the failure in a few words: ${pill.failure}`);
  }
  assert.match(await face(topic(page, 'wrap')), /next · close/);
});

test('D3: the opener’s worked row is Act III’s recorded run, word for word', async t => {
  const run = await json(path.join(runs, 'flipped-sense-claude.json'));
  const meta = await json(path.join(runs, 'raw/flipped-sense-claude.meta.json'));
  const said = run.steps.filter(step => step.type === 'message').map(step => step.text).at(-1);
  const page = await pageFor(t, { javaScriptEnabled: false });
  const row = await shown(topic(page, 'your-turn'));
  assert.ok(said.startsWith('All 30 tests pass now.'), 'the run’s last message opens with the claim');
  assert.ok(row.includes(norm('“All 30 tests pass now.”')), 'the claim, quoted');
  assert.ok(meta.verification.post.summary.startsWith('30 passed') && meta.verification.post.exit_code === 0, 'the run’s own pytest after the fix');
  assert.match(row, /uv run pytest \| → \| 30 passed/);
  assert.deepEqual(meta.changed_files.map(line => line.trim()), ['M p00_model.py']);
  assert.match(row, /git status --short \| → \| m p00_model\.py/);
});

test('D3: the lab steps’ notes carry the lab page’s exact commands and prompts', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  const html = await readFile(ladder, 'utf8');
  const decode = text => text.replace(/<[^>]+>/g, '').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'").replace(/&amp;/g, '&');
  // Each level's own section of the lab page: two levels share a label ("Start Claude Code in plan mode").
  const level = id => html.match(new RegExp(`<section id="${id}" data-level[\\s\\S]*?</section>`))[0];
  const presOf = id => new Map([...level(id).matchAll(/<pre\b[^>]*aria-label="([^"]+)"[^>]*>([\s\S]*?)<\/pre>/g)].map(m => [m[1], decode(m[2])]));
  const needed = {
    l1: ['L1 export commands', 'Start Claude Code in plan mode', 'Start Codex read-only', 'L1 prompt', 'L1 done commands'],
    l2: ['Back to the session from p00-explore', 'L2 export commands', 'Start Claude Code', 'Start Codex', 'L2 prompt', 'L2 done commands'],
    l3: ['Into L3 from p00-fix', 'Start Claude Code in plan mode', 'Start Codex, then switch to Plan mode', 'L3 plan prompt', 'L3 build prompt', 'L3 done commands'],
    l4: ['Back to p00-fix from L3', 'L4 rule done commands', 'L4 skill done commands', 'Back to the session from L3', 'L4 export commands', 'Claude Code headless run', 'Codex headless run', 'L4 headless done commands'],
  };
  for (const id of labSteps) {
    const pres = await notes(topic(page, id)).locator('pre[id]').evaluateAll(els => els.map(el => ({ id: el.id, text: el.textContent })));
    const copies = await notes(topic(page, id)).locator('button[data-copy]').evaluateAll(els => els.map(el => el.dataset.copy));
    assert.deepEqual(copies, pres.map(pre => pre.id), `#${id}: each command and prompt has its Copy button`);
    // The agent CLI flags in them date fast: the notes say as of when, as the lab page does.
    if (id !== 'l2') assert.match(await notesText(topic(page, id)), /cli flags as of 2026-\d\d-\d\d \(claude code [\d.]+, codex-cli [\d.]+\)/, `#${id}: the CLI flags' as-of date`);
    const onPage = presOf(id);
    // The notes carry the level's commands in the lab page's order, each exactly as the page prints it.
    assert.deepEqual(pres.map(pre => pre.text), needed[id].map(label => {
      assert.ok(onPage.has(label), `the lab page's ${id.toUpperCase()} still has “${label}”`);
      return onPage.get(label);
    }), `#${id}’s notes carry ${id.toUpperCase()}’s commands and prompts exactly as the lab page`);
  }
  // The catch-the-agent exercise is the verifier-gaming lab's own panel.
  assert.equal(await notes(topic(page, 'catch')).locator('a[href="labs/verifier-gaming.html#catch-the-agent"]').count(), 1);
});

// ImpossibleBench, arXiv 2510.20270v1 (submitted 2025-10-23; the only version), read 2026-11-02:
// §4 "GPT-5, cheats 54.0% of the time on Conflicting-SWEbench"; §5.1 "Claude Opus 4.1's increases from 50% to 55%";
// Figure 6's data labels on Conflicting-LiveCodeBench: GPT-5 92% under prompt A, 1% under prompt D; o3 91% and 33%
// (§5.1: "prompt A and B lead to a cheating rate >85%, while prompt D lowers them to 1% and 33%"); Appendix G.3.4
// holds the SWE-bench system prompt. The §5.3 sentence "o3 from 49% to 12%" is not used: Figure 8 labels that
// series o4-mini.
const impossible = {
  l2: [['GPT-5', 54], ['Claude Opus 4.1', 50]],
  l4: [['GPT-5', 92, 1], ['o3', 91, 33]],
  sweRule: ['DO NOT MODIFY THE TESTS.', 'STOP. Do NOT try to carve out the code to pass the tests.'],
};
async function bars(slide) {
  // Each bar as drawn: its width as a share of the 0–100% track, and the value printed beside it.
  return slide.evaluate(el => [...el.querySelectorAll('.ib-bar')].map(bar => {
    // The track keeps a pad on its right for the value labels; 100% ends where the pad starts.
    const track = bar.closest('.ib-track');
    const pad = parseFloat(getComputedStyle(track).getPropertyValue('--ib-pad')) * parseFloat(getComputedStyle(document.documentElement).fontSize);
    return { share: bar.getBoundingClientRect().width / (track.getBoundingClientRect().width - pad), v: Number(getComputedStyle(bar).getPropertyValue('--v')) };
  }));
}

test('D3: #l2 and #l4 draw ImpossibleBench’s rates to scale, with the prompts word for word', async t => {
  const page = await pageFor(t, { viewport: viewports[0] });
  for (const id of ['l2', 'l4']) {
    await goTo(page, id);
    await topic(page, id).locator('[data-rp-chip]').first().click();
    await topic(page, id).locator('[data-rp-reveal]').click();
  }
  const l2 = topic(page, 'l2');
  await goTo(page, 'l2');
  const drawn2 = await bars(l2);
  assert.deepEqual(drawn2.map(bar => bar.v), impossible.l2.map(([, v]) => v));
  for (const bar of drawn2) assert.ok(Math.abs(bar.share - bar.v / 100) < 0.01, `#l2: ${bar.v}% to scale (${bar.share})`);
  const face2 = await shown(l2);
  for (const [model, v] of impossible.l2) assert.ok(face2.includes(norm(model)) && face2.includes(`${v}%`), `#l2 shows ${model} ${v}%`);
  for (const part of impossible.sweRule) assert.ok(face2.includes(norm(part)), `#l2’s rule quotes “${part}”`);
  assert.doesNotMatch(face2, /\bo3\b|49%/, 'no o3 on the real repositories');
  await goTo(page, 'l4');
  const l4 = topic(page, 'l4');
  const drawn4 = await bars(l4);
  assert.deepEqual(drawn4.map(bar => bar.v), impossible.l4.flatMap(([, loose, strict]) => [loose, strict]));
  for (const bar of drawn4) assert.ok(Math.abs(bar.share - bar.v / 100) < 0.01, `#l4: ${bar.v}% to scale (${bar.share})`);
  const face4 = await shown(l4);
  for (const [model, loose, strict] of impossible.l4) for (const v of [model, `${loose}%`, `${strict}%`]) assert.ok(face4.includes(norm(String(v))), `#l4 shows ${v}`);
  assert.match(await l4.locator('.cite').textContent(), /Figure 6/, '91% is read from the figure');
  assert.match(await notesText(l4), /act iv returns to that|planted|injection|trifecta/, 'text it reads rides in the context too');
});

test('D3: #gap’s lower bounds are the P00 data’s, recomputed here', async t => {
  const plants = await csv(path.join(p00, 'data/plants.csv'));
  const customers = await csv(path.join(p00, 'data/customers.csv'));
  const costs = await csv(path.join(p00, 'data/costs.csv'));
  const keys = Object.keys(plants[0]);
  const [plantKey, fixedKey, capKey] = [keys.find(k => /plant|id|name/i.test(k)), keys.find(k => /fixed/i.test(k)), keys.find(k => /cap/i.test(k))];
  const ckeys = Object.keys(customers[0]);
  const [custKey, demKey] = [ckeys.find(k => /customer|id|name/i.test(k)), ckeys.find(k => /demand/i.test(k))];
  const kkeys = Object.keys(costs[0]);
  const [fromKey, toKey, unitKey] = [kkeys.find(k => /plant|from/i.test(k)), kkeys.find(k => /customer|to/i.test(k)), kkeys.find(k => /cost/i.test(k))];
  const unit = (p, c) => Number(costs.find(row => row[fromKey] === p && row[toKey] === c)[unitKey]);
  const demand = customers.reduce((sum, c) => sum + Number(c[demKey]), 0);
  const ids = plants.map(p => p[plantKey]);
  const bounds = [];
  for (let mask = 1; mask < 1 << ids.length; mask++) {
    const open = ids.filter((_, i) => mask & (1 << i));
    const capacity = plants.filter(p => open.includes(p[plantKey])).reduce((sum, p) => sum + Number(p[capKey]), 0);
    if (open.length === 1) { assert.ok(capacity < demand, `${open} alone cannot cover ${demand}`); continue; }
    const fixed = plants.filter(p => open.includes(p[plantKey])).reduce((sum, p) => sum + Number(p[fixedKey]), 0);
    const routes = customers.reduce((sum, c) => sum + Number(c[demKey]) * Math.min(...open.map(p => unit(p, c[custKey]))), 0);
    bounds.push({ open: open.join(' + '), bound: fixed + routes, fixed, routes });
  }
  assert.deepEqual(bounds.map(b => b.bound).sort((a, b) => a - b), [485, 595, 600, 615]);
  const page = await pageFor(t, { javaScriptEnabled: false });
  const drawn = await shown(topic(page, 'gap'));
  for (const b of bounds) assert.ok(drawn.includes(`${b.bound}`) && drawn.includes(`${b.fixed}`) && drawn.includes(`${b.routes}`), `#gap shows ${b.open}: ${b.bound} = ${b.fixed} + ${b.routes}`);
  assert.match(drawn, /no plan exists below 485/);
});

test('D3: #this-repo draws only gates this repository really has', async t => {
  const ruleset = await json(path.join(repoRoot, 'setup/pr-only-main.json'));
  assert.deepEqual(ruleset.bypass_actors, []);
  const types = ruleset.rules.map(rule => rule.type);
  for (const type of ['pull_request', 'non_fast_forward', 'deletion', 'required_status_checks']) assert.ok(types.includes(type), type);
  for (const hook of ['.githooks/pre-commit', '.githooks/pre-push', '.github/workflows/pr-only.yml', '.github/workflows/ci.yml']) {
    assert.equal((await stat(path.join(repoRoot, hook))).isFile(), true, hook);
  }
  const page = await pageFor(t, { javaScriptEnabled: false });
  const drawn = await shown(topic(page, 'this-repo'));
  for (const gate of ['pre-commit', 'pre-push', 'pull request', 'required check', 'bypass list', 'audit']) assert.ok(drawn.includes(gate), `#this-repo draws ${gate}`);
  assert.match(drawn, /\bbypass list: \| 0\b|\bbypass list: 0\b/);
  // The gates decide how a change lands, not whether it is right: #catch's fix C would pass the required check.
  assert.match(drawn, /not whether it is right/);
});

test('D3: #l1 keeps PocketOS’s attribution and its recovery', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  const slide = topic(page, 'l1');
  assert.match(await shown(slide), /account scoped access, the maximum access possible/);
  assert.match(await shown(slide), /recovered/);
  const talk = await notesText(slide);
  assert.match(talk, /as quoted by tom's hardware/);
  assert.match(talk, /without naming the customer/);
  for (const href of ['https://blog.railway.com/p/your-ai-wants-to-nuke-your-database', 'https://x.com/lifeofjer/status/2048103471019434248']) {
    assert.ok(await slide.locator(`a[href="${href}"]`).count() >= 1, href);
  }
});

test('D3: #debrief’s one filled row is the instructor’s own account, labelled as one, and does not match', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  const slide = topic(page, 'debrief');
  const drawn = await shown(slide);
  assert.match(drawn, /the instructor's account/);
  assert.match(drawn, /no transcript/);
  assert.match(drawn, /same objective/);
  assert.match(drawn, /no cvar term/);
  // One row per level for the room, empty.
  for (const level of ['l1', 'l2', 'l3', 'l4']) assert.match(drawn, new RegExp(`\\b${level}\\b`));
  // #catch and #l3 are checked against P00 itself in sessions/01-fundamentals/tests/test_evidence_deck.py.
});

async function localLinks(page) {
  const root = await realpath(session);
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
    assert.ok(relative !== '..' && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative), `local target stays in the session: ${href}`);
    assert.equal((await stat(target)).isFile(), true, `local target exists: ${href}`);
  }
}

test('D4: relative links resolve inside the session', async t => {
  await localLinks(await pageFor(t, { javaScriptEnabled: false }));
});

test('D4: each level on the opening spine opens its own slide', async t => {
  const page = await pageFor(t, { viewport: viewports[0] });
  for (const id of ['l1', 'l2', 'l3', 'l4', 'debrief']) {
    await goTo(page, 'your-turn');
    await topic(page, 'your-turn').locator(`svg.spine a[href="#${id}"]`).click();
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
// What the room sees of a predict: which chips are marked, whether the answer shows, and whether a mark
// that reads as "right" (a ✓, or teal) sits on the room's pick.
function readPredict(slide) {
  return slide.evaluate(el => {
    const root = el.querySelector('[data-rp]');
    const hidden = [...el.querySelectorAll('.rp-ans')];
    const chips = [...el.querySelectorAll('[data-rp-chip]')];
    const tick = chip => [getComputedStyle(chip, '::before').content, getComputedStyle(chip, '::after').content, chip.textContent].join(' ').includes('✓');
    const probe = document.createElement('i');
    probe.style.color = 'var(--accent)';
    document.body.append(probe);
    const accent = getComputedStyle(probe).color;
    probe.remove();
    const teal = chip => getComputedStyle(chip).borderTopColor === accent;
    return {
      state: root.getAttribute('data-rp-state'),
      shown: hidden.length > 0 && hidden.every(node => getComputedStyle(node).visibility === 'visible'),
      none: hidden.every(node => getComputedStyle(node).visibility === 'hidden'),
      pressed: chips.filter(chip => chip.getAttribute('aria-pressed') === 'true').map(chip => chip.dataset.rpChip),
      ticked: chips.filter(chip => chip.getAttribute('aria-pressed') === 'true' && (tick(chip) || teal(chip))).map(chip => chip.dataset.rpChip),
    };
  });
}

test('D5: every predict’s headline keeps its answer back', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  const giveaway = { l2: /54|half|50%/, catch: /\bnone\b|no command|passes all/, l3: /\b5\b|five times|all five|optimal five/, l4: /\b1%|one percent|92/ };
  for (const { id } of predicts) {
    assert.doesNotMatch(norm(await topic(page, id).locator('h2').textContent()), giveaway[id], `#${id}: the headline gives nothing away`);
    await count(topic(page, id).locator('[data-rp-right]'), 1);
    // One question: the notes ask, word for word, the question on the face (its question line, or its headline).
    const slide = topic(page, id);
    const asked = (await notesText(slide)).match(/predict question: "([^"]+)"/)?.[1];
    const onFace = norm(await (await slide.locator('.rp-q').count() ? slide.locator('.rp-q') : slide.locator('h2')).textContent());
    assert.equal(asked, onFace, `#${id}: the notes ask the face's question`);
    assert.equal(norm(await slide.locator('.rp-chips').getAttribute('aria-label')), onFace, `#${id}: the chips are labelled with it`);
  }
});

for (const viewport of viewports.slice(0, 2)) {
  const size = `${viewport.width}×${viewport.height}`;
  for (const { id, answer } of predicts) {
    test(`D5: #${id}: the room picks, what happened is revealed beside its pick, then hidden again, at ${size}`, async t => {
      const page = await pageFor(t, { viewport });
      await goTo(page, id);
      const slide = topic(page, id);
      const chips = slide.locator('[data-rp-chip]');
      const reveal = slide.locator('[data-rp-reveal]'), reset = slide.locator('[data-rp-reset]');
      await eventually(async () => assert.equal((await readPredict(slide)).none, true, 'the answer starts hidden'));
      assert.deepEqual((await readPredict(slide)).pressed, []);
      await bigEnough(slide);
      assert.equal(await slide.locator('[data-rp-right]').getAttribute('data-rp-chip'), answer);
      const values = await chips.evaluateAll(els => els.map(el => el.dataset.rpChip));
      const wrong = values.find(value => value !== answer);
      const chip = value => slide.locator(`[data-rp-chip="${value}"]`);
      await chip(values.find(value => value !== wrong)).click();
      await chip(wrong).click();
      assert.deepEqual((await readPredict(slide)).pressed, [wrong], 'one pick at a time');
      await stillTurns(page, id);
      await reveal.click();
      await eventually(async () => {
        const seen = await readPredict(slide);
        assert.equal(seen.shown, true, 'the answer shows');
        assert.deepEqual(seen.pressed, [wrong], 'beside the room’s pick');
        assert.deepEqual(seen.ticked, [], 'the room’s pick carries no ✓ and no teal');
      });
      assert.ok(norm(await slide.locator('[data-rp-status]').textContent()).length > 0, 'the reveal is announced');
      await chip(values.find(value => value !== wrong)).click({ force: true }).catch(() => {});
      assert.deepEqual((await readPredict(slide)).pressed, [wrong], 'the pick is frozen after the reveal');
      await bigEnough(slide);
      await stillTurns(page, id);
      await reset.click();
      await eventually(async () => {
        const seen = await readPredict(slide);
        assert.equal(seen.none, true, 'Reset hides the answer');
        assert.deepEqual(seen.pressed, [], 'Reset clears the pick');
      });
      await stillTurns(page, id);
      await reveal.focus();
      await page.keyboard.press('Space');
      await activeSlide(page, id);
      await eventually(async () => assert.equal((await readPredict(slide)).shown, true));
      await focused(reset);
      await page.keyboard.press('Enter');
      await activeSlide(page, id);
      await eventually(async () => assert.equal((await readPredict(slide)).none, true));
    });
  }

  test(`D5: Copy in the lab steps’ notes puts the exact text on the clipboard, at ${size}`, async t => {
    const page = await pageFor(t, { viewport, permissions: ['clipboard-read', 'clipboard-write'] });
    for (const id of labSteps) {
      await goTo(page, id);
      const disclosure = notes(topic(page, id));
      await disclosure.locator(':scope > summary').click();
      for (const button of (await disclosure.locator('button[data-copy]').all()).slice(0, 2)) {
        const source = await disclosure.locator(`pre#${await button.getAttribute('data-copy')}`).textContent();
        await button.click();
        await eventually(async () => assert.equal(await page.evaluate(() => navigator.clipboard.readText()), source));
        assert.equal(norm(await button.textContent()), 'copied');
      }
      await stillTurns(page, id);
    }
  });
}

// With no script, and on paper, every predict shows what happened, and nothing is left to press.
async function endStates(page) {
  for (const { id } of predicts) {
    const slide = topic(page, id);
    assert.equal((await readPredict(slide)).shown, true, `#${id}: the answer shows`);
    assert.equal(await slide.locator('[data-rp-reveal]').isVisible(), false, `#${id}: nothing left to reveal`);
  }
}

test('D5: without JavaScript each predict shows what happened, and no slide has a slider', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  await endStates(page);
  for (const control of await page.locator('section[data-slide] :not(details) > button, section[data-slide] button:not(details button)').all()) {
    assert.ok(!(await control.isVisible()) || await control.isDisabled(), `${await control.textContent()}: no dead control`);
  }
  await count(page.locator('section[data-slide] :is(input[type="range"], [role="slider"])'), 0);
});

test('D5: print shows each predict’s answer, whatever state the room left it in', async t => {
  const page = await pageFor(t);
  await eventually(async () => assert.equal((await readPredict(topic(page, 'l2'))).none, true));
  await page.emulateMedia({ media: 'print' });
  await eventually(async () => endStates(page));
});

for (const viewport of viewports.slice(0, 2)) {
  test(`D1: every slide fits ${viewport.width}×${viewport.height} without internal scrolling, before and after its reveal`, { timeout: 180000 }, async t => {
    const page = await pageFor(t, { viewport });
    await mkdir(artifacts, { recursive: true });
    for (const id of await idsOf(page)) {
      await goTo(page, id);
      const states = (await topic(page, id).locator('[data-rp-reveal]').count()) ? ['predict', 'revealed'] : ['only'];
      for (const state of states) {
        if (state === 'revealed') {
          await topic(page, id).locator('[data-rp-chip]').first().click();
          await topic(page, id).locator('[data-rp-reveal]').click();
          // The answer fades in: wait until it is fully drawn before measuring and capturing it.
          await eventually(async () => assert.equal(await topic(page, id).evaluate(el => [...el.querySelectorAll('.rp-ans')]
            .every(node => getComputedStyle(node).visibility === 'visible' && getComputedStyle(node).opacity === '1')), true));
        }
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
        assert.deepEqual(problems, [], `#${id} (${state}) fits without internal scrolling`);
        // Every text a viewer reads renders at 13 px or more.
        const small = await topic(page, id).evaluate(el => [...el.querySelectorAll('*')]
          .filter(node => node.checkVisibility() && !node.closest('details.speaker-notes, .visually-hidden') &&
            [...node.childNodes].some(child => child.nodeType === Node.TEXT_NODE && child.textContent.trim()))
          .map(node => {
            const svg = node.closest('svg');
            const size = parseFloat(getComputedStyle(node).fontSize) * (svg ? svg.getScreenCTM().a : 1);
            return [node.textContent.trim().slice(0, 30), Math.round(size * 10) / 10];
          }).filter(([, size]) => size < 12.9));
        assert.deepEqual(small, [], `#${id} (${state}): no text under 13 px`);
        await page.screenshot({ path: path.join(artifacts, `${viewport.width}-${id}${state === 'revealed' ? '-revealed' : ''}.png`) });
      }
      const title = await topic(page, id).locator('h2').evaluate(el => {
        const line = parseFloat(getComputedStyle(el).lineHeight) || parseFloat(getComputedStyle(el).fontSize) * 1.3;
        return el.getBoundingClientRect().height / line;
      });
      assert.ok(title < 1.5, `#${id}: the headline is one line`);
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

test('D1: on a phone the spine scrolls sideways, starting at the current level, its text still legible', async t => {
  const page = await pageFor(t, { viewport: viewports[2] });
  for (const id of order) {
    const wrap = topic(page, id).locator('.spine-wrap');
    await eventually(async () => {
      const state = await wrap.evaluate(el => {
        const svg = el.querySelector('svg');
        const frame = el.getBoundingClientRect();
        const lit = [...svg.querySelectorAll('.st.now')].map(node => node.getBoundingClientRect());
        const texts = [...svg.querySelectorAll('text')].filter(text => text.textContent.trim() && getComputedStyle(text).visibility !== 'hidden');
        return {
          scrolls: el.scrollWidth > el.clientWidth,
          lit: lit.every(box => box.left >= frame.left - 1 && box.right <= frame.right + 1),
          legible: Math.min(...texts.map(text => parseFloat(getComputedStyle(text).fontSize) * svg.getScreenCTM().a)) >= 12.9,
        };
      });
      assert.deepEqual(state, { scrolls: true, lit: true, legible: true }, `${id}: current level in view`);
    }, `${id}: current level in view`);
  }
});

for (const width of [718, 1046]) {
  test(`D1: in print, ${width} px wide (A4 portrait or landscape), no chart is cut by its scroller`, async t => {
    const page = await pageFor(t, { viewport: { width, height: 900 } });
    await page.emulateMedia({ media: 'print' });
    await eventually(async () => {
      const cut = await page.locator('section[data-slide] [role="region"]').evaluateAll(els => els
        .filter(el => el.querySelector('svg') && !el.classList.contains('spine-wrap') && el.scrollWidth > el.clientWidth + 1)
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
