import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdir, readFile } from 'node:fs/promises';
import path from 'node:path';
import { chromium } from '../browser.mjs';
import { openPage, repoRoot, count, eventually, assertCollected } from './component-helpers.mjs';

// Act IV is the mini homework, end to end: one slide per step of the loop students repeat on P01 tonight (read,
// plan, build, check, ship), after an opener that names what they learn, and a close that maps the steps onto
// P01. The spine is the loop, repeated on every slide with the current step lit. Two predicts, never back to back.
// The commands and prompts in the notes are the mini homework README's, word for word. These are structural
// floors next to check-page and a person's review; test_evidence_deck.py checks #check's outputs against check.py.
const session = path.join(repoRoot, 'sessions/01-fundamentals');
const file = path.join(session, 'cursus/04-evidence.html');
const readme = path.join(session, 'exercises/mini-homework/README.md');
const artifacts = path.join(repoRoot, 'artifacts/html-pages/evidence');
const viewports = [{ width: 1440, height: 900 }, { width: 1280, height: 720 }, { width: 390, height: 844 }];
const order = ['goals', 'read', 'plan', 'build', 'check', 'gap', 'ship', 'wrap'];
const steps = ['read', 'plan', 'build', 'check', 'ship'];
// The step each slide stands on (0-based); the overview stands on none, the close on every step done.
const current = { read: 0, plan: 1, build: 2, check: 3, gap: 3, ship: 4, wrap: 5 };
const predicts = [{ id: 'plan', answer: 'tue-wed' }, { id: 'check', answer: '0' }];
const faceWords = 48;
// Pictures, controls, labels, code and data (the rosters #check claims about) are not prose.
const notProse = ['h2', '.eyebrow', '.spine-wrap', 'svg', '[role="img"]', 'table', 'button', '[role="group"]', '.tag', 'pre', 'figure', '.ck-roster'];
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
const face = (slide, extra = []) => slide.evaluate((el, extra) => {
  const copy = el.cloneNode(true);
  copy.querySelectorAll(['details.speaker-notes', 'script', 'style', '[hidden]', '[aria-hidden="true"]', '.visually-hidden', ...extra]
    .join(', ')).forEach(node => node.remove());
  return copy.textContent;
}, extra).then(norm);
const pageFor = (t, options = {}) => openPage(t, chromium, { file, ...options });
// The README's fenced block under a step heading, exactly.
const fenced = (text, heading) => text.slice(text.indexOf(heading)).match(/```(?:text|sh)\n([\s\S]*?)\n```/)[1];

async function activeSlide(page, id) {
  await eventually(async () => {
    assert.equal(decodeURIComponent(new URL(page.url()).hash.slice(1)), id);
    assert.equal(await topic(page, id).evaluate(el => el.checkVisibility()), true, `#${id} is visible`);
  }, `slide ${id}`);
}
async function goTo(page, id) {
  await page.evaluate(id => { location.hash = encodeURIComponent(id); }, id);
  await activeSlide(page, id);
}
// One copy of the spine as a viewer sees it: each step's state, on its box, its badge and its "who" label alike.
const readSpine = svg => svg.evaluate(el => {
  const state = node => ['all', 'done', 'now', 'next'].find(name => node.classList.contains(name));
  return {
    steps: [...el.querySelectorAll('g.step')].map(step => {
      const states = new Set([step, step.querySelector('.node'), step.querySelector('.badge'), step.querySelector('.who')].map(state));
      return states.size === 1 ? [...states][0] : [...states].join('≠');
    }),
    loop: state(el.querySelector('.loop')),
    geometry: [...el.querySelectorAll('rect, path, circle')].map(node => ['x', 'y', 'width', 'height', 'd', 'cx', 'cy', 'r']
      .map(name => node.getAttribute(name) ?? '').join(' ')),
  };
});
// What the room sees of a predict: the marked chips, whether the answer shows, and whether a "right" mark sits on its pick.
const readPredict = slide => slide.evaluate(el => {
  const answers = [...el.querySelectorAll('.rp-ans')];
  const probe = document.createElement('i');
  probe.style.color = 'var(--accent)';
  el.append(probe);
  const teal = getComputedStyle(probe).color;
  probe.remove();
  const pressed = [...el.querySelectorAll('[data-rp-chip][aria-pressed="true"]')];
  return {
    pressed: pressed.map(chip => chip.dataset.rpChip),
    shown: answers.every(node => getComputedStyle(node).visibility === 'visible'),
    none: answers.every(node => getComputedStyle(node).visibility === 'hidden'),
    ticked: pressed.filter(chip => !chip.hasAttribute('data-rp-right') &&
      (chip.textContent.includes('✓') || getComputedStyle(chip).borderColor === teal)).map(chip => chip.dataset.rpChip),
  };
});

test('D1: authored deck in loop order, one collapsed disclosure per slide, and no minutes anywhere', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  assert.equal(await page.locator('html').getAttribute('data-page-kind'), 'deck');
  assert.equal(await page.locator('html').getAttribute('data-design-system'), 'cursus');
  await count(page.locator('script[src], script[type="module"]'), 0);
  assert.deepEqual(await slides(page).evaluateAll(els => els.map(el => el.id)), order);
  for (const slide of await slides(page).all()) {
    const id = await slide.getAttribute('id');
    await count(slide.locator('h2'), 1);
    await count(notes(slide), 1);
    assert.equal(await notes(slide).evaluate(el => el.open), false, `#${id}: notes are authored collapsed`);
    const talk = await notesText(slide, { commands: false });
    // Read aloud: about 150 to 220 words of talk; the commands and the background line aside.
    const spoken = talk.split('background for you, not for the slides')[0];
    assert.ok(words(spoken) >= 120 && words(spoken) <= 235, `#${id}: ${words(spoken)} words read aloud`);
    assert.match(talk, /^talk track: /, `#${id}: notes open on the talk track`);
    assert.match(talk, /\bpoint at\b/, `#${id}: pointing cues`);
    assert.match(talk, /\btransition: /, `#${id}: a transition`);
  }
  await count(page.locator('[data-minutes]'), 0);
  assert.doesNotMatch(await page.locator('body').textContent(), /\bminutes?\b|\b\d+\s?min\b/i, 'timing lives in the run of show');
  await assertCollected('evidence');
});

test('D1: faces are sparse, carry no provenance, and link exercises only from the notes', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  for (const slide of await slides(page).all()) {
    const id = await slide.getAttribute('id');
    assert.doesNotMatch(await face(slide), /\brecorded\b|fixtures\/|\b20\d\d-\d\d-\d\d\b|\bclaude code 2\.|codex-cli/, `#${id}: no provenance`);
    const body = await face(slide, notProse);
    assert.ok(words(body) <= faceWords, `#${id}: ${words(body)} words on the face (at most ${faceWords})`);
    for (const link of await slide.locator('a[href*="exercises/"], a[href*="labs/"]').all()) {
      assert.equal(await link.evaluate(el => !!el.closest('details.speaker-notes')), true, `#${id}: ${await link.getAttribute('href')} sits in the notes`);
    }
  }
  // Every step slide says what the students do now, in one line that points at the README's step.
  for (const [i, id] of steps.entries()) {
    await count(topic(page, id).locator('p.do'), 1);
    assert.match(norm(await topic(page, id).locator('p.do').textContent()), i ? new RegExp(`^do ?readme step ${i + 1}: `) : /exercises\/mini-homework\/readme\.md/, `#${id}`);
  }
});

test('D2: the act opens on Act III’s last line, then names three outcomes, each on its step', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  const actThree = await readFile(path.join(session, 'cursus/03-agent.html'), 'utf8');
  const line = 'Your turn: one small problem, end to end, graded by the evidence, not the message.';
  assert.ok(actThree.includes(`<p>${line}</p>`), 'Act III’s close hands over with this line');
  assert.ok((await notesText(topic(page, 'goals'))).includes(norm(`Act III ended on “${line}”`)), '#goals opens on it');
  // Each outcome names the step that practises it, by name: no numbers out of order.
  const goals = await topic(page, 'goals').locator('ol.goals .goal-step').allTextContents();
  assert.deepEqual(goals.map(norm), ['plan', 'check', 'ship']);
  await count(topic(page, 'goals').locator('ol.goals :is(.goal-n, .n)'), 0);
  // The overview spine: every step drawn, each linking its own slide, in loop order.
  const overview = topic(page, 'goals').locator('svg.spine');
  assert.deepEqual(await overview.locator('a').evaluateAll(els => els.map(el => el.getAttribute('href'))), steps.map(id => `#${id}`));
  assert.deepEqual((await readSpine(overview)).steps, steps.map(() => 'all'));
});

test('D2: every other slide repeats the spine as an image, its step lit, the rest done or next', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  const reference = (await readSpine(topic(page, 'goals').locator('svg.spine'))).geometry;
  for (const [id, now] of Object.entries(current)) {
    const svg = topic(page, id).locator('svg.spine');
    await count(svg, 1);
    assert.equal(await svg.getAttribute('role'), 'img');
    await count(svg.locator('a'), 0);
    const seen = await readSpine(svg);
    assert.deepEqual(seen.steps, steps.map((_, i) => now === 5 || i < now ? 'done' : i === now ? 'now' : 'next'), `#${id}`);
    assert.equal(seen.loop, now === 3 ? 'now' : now > 3 ? 'done' : 'next', `#${id}: the FAIL loop is lit on the check`);
    assert.deepEqual(seen.geometry, reference, `#${id}: copies differ only in their classes`);
  }
});

test('D3: the notes carry the README’s prompts and commands, word for word', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  const text = await readFile(readme, 'utf8');
  const pre = async id => page.locator(`pre#${id}`).textContent();
  assert.equal(await pre('plan-prompt'), fenced(text, '### 2. Plan'));
  assert.equal(await pre('build-prompt'), fenced(text, '### 3. Build'));
  assert.equal(await pre('check-cmds'), fenced(text, '### 4. Check'));
  for (const id of ['plan-claude', 'ship-claude', 'ship-codex', 'ship-bash']) {
    assert.ok(text.includes(`\`${await pre(id)}\``), `${id}: the README gives the same command`);
  }
  assert.ok(text.includes('start `codex`, then type `/plan`'), 'Codex’s plan mode, as in the notes');
  // Each step slide's notes point the instructor at the README's matching step.
  for (const [i, id] of steps.entries()) {
    assert.match(await notesText(topic(page, id)), new RegExp(`the mini homework's readme, step ${i + 1}\\b`), `#${id}`);
  }
});

test('D3: #read draws the README’s demand, and #gap’s sum is that demand’s', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  const [, ...rows] = (await readFile(path.join(session, 'exercises/mini-homework/data/demand.csv'), 'utf8')).trim().split(/\r?\n/);
  const demand = rows.map(row => row.split(',')).map(([day, value]) => [day, Number(value)]);
  const drawn = await topic(page, 'read').evaluate(el => [...el.querySelectorAll('.rd-d')].map((day, i) =>
    [day.textContent, Number(el.querySelectorAll('.rd-v')[i].textContent), Number(el.querySelectorAll('.rd-bar')[i].getAttribute('height'))]));
  assert.deepEqual(drawn, demand.map(([day, value]) => [day, value, 10 * value]), 'bars to scale, 10 per person');
  const total = demand.reduce((sum, [, value]) => sum + value, 0);
  const sum = norm(await topic(page, 'gap').locator('.gp-sum').textContent());
  assert.equal(sum, norm(`${demand.map(([, value]) => value).join('+')} = ${total} person-days ÷ 5 days each = ${total / 5} → whole people: ${Math.ceil(total / 5)}`));
  const check = await readFile(path.join(session, 'exercises/mini-homework/check.py'), 'utf8');
  assert.match(check, new RegExp(`^LP_BOUND = ${total / 5}$`, 'm'));
  assert.match(check, new RegExp(`^KNOWN_OPTIMUM = ${Math.ceil(total / 5)}$`, 'm'));
});

test('D5: each predict’s headline keeps its answer back, and its notes ask the face’s question', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  const giveaway = { plan: /tue|wed/, check: /\bnone\b|\bzero\b|no roster/ };
  for (const { id, answer } of predicts) {
    const slide = topic(page, id);
    assert.doesNotMatch(norm(await slide.locator('h2').textContent()), giveaway[id], `#${id}: the headline gives nothing away`);
    assert.equal(await slide.locator('[data-rp-right]').getAttribute('data-rp-chip'), answer);
    const asked = (await notesText(slide)).match(/predict question: "([^"]+)"/)?.[1];
    const onFace = norm(await (await slide.locator('.rp-q').count() ? slide.locator('.rp-q') : slide.locator('h2')).textContent());
    assert.equal(asked, onFace, `#${id}: the notes ask the face’s question`);
    assert.equal(norm(await slide.locator('.rp-chips').getAttribute('aria-label')), onFace, `#${id}: the chips carry it`);
  }
  // Never two predicts back to back.
  assert.ok(predicts.every(({ id }, i) => i === 0 || order.indexOf(id) - order.indexOf(predicts[i - 1].id) > 1));
});

for (const viewport of viewports.slice(0, 2)) {
  const size = `${viewport.width}×${viewport.height}`;
  for (const { id, answer } of predicts) {
    test(`D5: #${id}: the room picks, what happened shows beside the pick, then hides again, at ${size}`, async t => {
      const page = await pageFor(t, { viewport });
      await goTo(page, id);
      const slide = topic(page, id);
      const chip = value => slide.locator(`[data-rp-chip="${value}"]`);
      await eventually(async () => assert.equal((await readPredict(slide)).none, true, 'the answer starts hidden'));
      const values = await slide.locator('[data-rp-chip]').evaluateAll(els => els.map(el => el.dataset.rpChip));
      const wrong = values.find(value => value !== answer);
      await chip(answer).click();
      await chip(wrong).click();
      assert.deepEqual((await readPredict(slide)).pressed, [wrong], 'one pick at a time');
      await slide.locator('[data-rp-reveal]').click();
      await eventually(async () => {
        const seen = await readPredict(slide);
        assert.equal(seen.shown, true, 'the answer shows');
        assert.deepEqual(seen.pressed, [wrong], 'beside the room’s pick');
        assert.deepEqual(seen.ticked, [], 'the room’s pick carries no ✓ and no teal');
      });
      assert.ok(norm(await slide.locator('[data-rp-status]').textContent()).length > 0, 'the reveal is announced');
      assert.equal(await chip(answer).isDisabled(), true, 'the pick is frozen after the reveal');
      await slide.locator('[data-rp-reset]').click();
      await eventually(async () => {
        const seen = await readPredict(slide);
        assert.equal(seen.none, true, 'Reset hides the answer');
        assert.deepEqual(seen.pressed, [], 'Reset clears the pick');
      });
      // A pointer press hands focus back to the slide, so the arrow keys still turn it.
      await page.keyboard.press('ArrowRight');
      await activeSlide(page, order[order.indexOf(id) + 1]);
    });
  }
}

test('D5: Copy in the notes puts the exact text on the clipboard', async t => {
  const page = await pageFor(t, { viewport: viewports[1], permissions: ['clipboard-read', 'clipboard-write'] });
  for (const id of ['plan', 'check']) {
    await goTo(page, id);
    const disclosure = notes(topic(page, id));
    await disclosure.locator(':scope > summary').click();
    for (const button of await disclosure.locator('button[data-copy]').all()) {
      const source = await disclosure.locator(`pre#${await button.getAttribute('data-copy')}`).textContent();
      await button.click();
      await eventually(async () => assert.equal(await page.evaluate(() => navigator.clipboard.readText()), source));
    }
  }
});

test('D5: without JavaScript, and in print, each predict shows what happened and nothing is left to press', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  for (const { id } of predicts) {
    assert.equal((await readPredict(topic(page, id))).shown, true, `#${id}: the answer shows`);
    assert.equal(await topic(page, id).locator('[data-rp-reveal]').isVisible(), false);
  }
  await count(page.locator('section[data-slide] :is(input[type="range"], [role="slider"])'), 0);
  const live = await pageFor(t);
  await eventually(async () => assert.equal((await readPredict(topic(live, 'plan'))).none, true));
  await live.emulateMedia({ media: 'print' });
  await eventually(async () => {
    for (const { id } of predicts) assert.equal((await readPredict(topic(live, id))).shown, true, `#${id} prints its answer`);
  });
});

for (const viewport of viewports.slice(0, 2)) {
  test(`D1: every slide fits ${viewport.width}×${viewport.height}, before and after its reveal, with a one-line headline`, { timeout: 120000 }, async t => {
    const page = await pageFor(t, { viewport });
    await mkdir(artifacts, { recursive: true });
    for (const id of order) {
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
        const problems = await topic(page, id).evaluate(el => [el, ...el.querySelectorAll('*')]
          .filter(node => node instanceof HTMLElement && node.checkVisibility() && !node.closest('.visually-hidden'))
          .filter(node => {
            const r = node.getBoundingClientRect();
            const out = r.width && r.height && (r.left < -1 || r.top < -1 || r.right > innerWidth + 1 || r.bottom > innerHeight + 1);
            const scrolls = node.clientHeight > 0 && (node.scrollHeight > node.clientHeight + 1 || node.scrollWidth > node.clientWidth + 1);
            return out || scrolls;
          }).map(node => node.id || node.className || node.tagName));
        assert.deepEqual(problems, [], `#${id} (${state}) fits without internal scrolling`);
        // Every text a viewer reads on the face renders at 12 px or more, SVG labels scaled included.
        const small = await topic(page, id).evaluate(el => [...el.querySelectorAll('*')]
          .filter(node => node.checkVisibility() && !node.closest('details.speaker-notes, .visually-hidden') &&
            [...node.childNodes].some(child => child.nodeType === Node.TEXT_NODE && child.textContent.trim()))
          .map(node => {
            const svg = node.closest('svg');
            return [node.textContent.trim().slice(0, 30), parseFloat(getComputedStyle(node).fontSize) * (svg ? svg.getScreenCTM().a : 1)];
          }).filter(([, px]) => px < 11.95).map(([text, px]) => `${text}: ${px.toFixed(1)} px`));
        assert.deepEqual(small, [], `#${id} (${state}): no text under 12 px`);
        await page.screenshot({ path: path.join(artifacts, `${viewport.width}-${id}${state === 'revealed' ? '-revealed' : ''}.png`) });
      }
      const lines = await topic(page, id).locator('h2').evaluate(el => el.getBoundingClientRect().height /
        (parseFloat(getComputedStyle(el).lineHeight) || parseFloat(getComputedStyle(el).fontSize) * 1.3));
      assert.ok(lines < 1.5, `#${id}: the headline is one line`);
    }
  });
}

test('D1: on a phone the page reads top to bottom, with only the pictures scrolling sideways', async t => {
  const page = await pageFor(t, { viewport: viewports[2] });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true, 'no page-wide overflow');
  const wide = await page.locator('section[data-slide] svg').evaluateAll(els => els
    .filter(svg => svg.getBoundingClientRect().width > innerWidth && !svg.closest('[role="region"], figure[aria-labelledby]')).map(svg => svg.className.baseVal));
  assert.deepEqual(wide, [], 'a picture wider than the phone sits in a labelled scroller');
});

test('D1: print shows every slide and every talk track, unclipped', async t => {
  const page = await pageFor(t);
  await page.emulateMedia({ media: 'print' });
  await eventually(async () => {
    for (const slide of await slides(page).all()) {
      assert.equal(await slide.isVisible(), true);
      const clipped = await notes(slide).evaluate(el => [el, ...el.querySelectorAll('*')].some(node => node.clientHeight > 0 &&
        node.scrollHeight > node.clientHeight + 1 && /auto|scroll|hidden|clip/.test(getComputedStyle(node).overflowY)));
      assert.equal(clipped, false, 'print contains the full note body');
    }
  });
});
