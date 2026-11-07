import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { chromium } from '../../../../tools/html-pages/browser.mjs';
import { openPage, repoRoot, eventually } from '../../../../tools/html-pages/tests/component-helpers.mjs';

// Act IV deck: what would break in front of the room. The steps' prompts and commands are the mini homework
// README's, the demand and the bound are its data's; each predict and Copy works, and after a pointer press the
// clicker's → still turns the slide. #check's outputs are checked against check.py in test_evidence_deck.py.
// check-page covers the rest of every deck: layout, accessibility, navigation, links, no-JS and print.
const session = path.join(repoRoot, 'sessions/01-fundamentals');
const mini = path.join(session, 'exercises/mini-homework');
const file = path.join(session, 'cursus/04-evidence.html');
const predicts = ['plan', 'check'];
const withCommands = ['plan', 'build', 'check', 'ship'];
const norm = value => value.normalize('NFKC').replace(/\s+/g, ' ').trim().toLowerCase();
// The README's fenced block under a step heading, exactly as a student copies it.
const fenced = (text, heading) => text.slice(text.indexOf(heading)).match(/```(?:text|sh)\n([\s\S]*?)\n```/)[1];

test('Act IV deck', async t => {
  const page = await openPage(t, chromium, { file, permissions: ['clipboard-read', 'clipboard-write'] });
  const topic = id => page.locator(`section[data-slide]#${id}`);
  const slides = page.locator('main[data-deck] section[data-slide]');
  const at = id => eventually(async () => {
    assert.equal(decodeURIComponent(new URL(page.url()).hash.slice(1)), id);
    assert.deepEqual(await slides.evaluateAll(els => els.filter(el => el.checkVisibility()).map(el => el.id)), [id]);
  }, `on #${id}`);
  const goTo = async id => { await page.evaluate(id => { location.hash = id; }, id); await at(id); };
  // A pointer press on a slide control hands focus back to the slide, so the clicker's → still turns it.
  const stillTurns = async id => {
    const ids = await slides.evaluateAll(els => els.map(el => el.id));
    await page.keyboard.press('ArrowRight');
    await at(ids[ids.indexOf(id) + 1]);
    await goTo(id);
  };

  await t.test('the notes carry the README’s prompts and commands, exactly as a student copies them', async () => {
    const readme = await readFile(path.join(mini, 'README.md'), 'utf8');
    const pre = id => page.locator(`pre#${id}`).textContent();
    assert.equal(await pre('plan-prompt'), fenced(readme, '### 2. Plan'));
    assert.equal(await pre('build-prompt'), fenced(readme, '### 3. Build'));
    assert.equal(await pre('check-cmds'), fenced(readme, '### 4. Check'));
    for (const id of ['plan-claude', 'ship-claude', 'ship-codex', 'ship-bash']) {
      assert.ok(readme.includes(`\`${await pre(id)}\``), `the README gives ${await pre(id)}`);
    }
  });

  await t.test('#read draws the demand, and #gap’s sum and bound are the data’s and check.py’s', async () => {
    const [, ...rows] = (await readFile(path.join(mini, 'data/demand.csv'), 'utf8')).trim().split(/\r?\n/);
    const demand = rows.map(row => row.split(',')).map(([day, value]) => [day, Number(value)]);
    const drawn = await topic('read').evaluate(el => [...el.querySelectorAll('.rd-d')].map((day, i) =>
      [day.textContent, Number(el.querySelectorAll('.rd-v')[i].textContent), Number(el.querySelectorAll('.rd-bar')[i].getAttribute('height'))]));
    assert.deepEqual(drawn, demand.map(([day, value]) => [day, value, 10 * value]), 'one bar per day, to scale');
    const total = demand.reduce((sum, [, value]) => sum + value, 0);
    assert.equal(norm(await topic('gap').locator('.gp-sum').textContent()),
      norm(`${demand.map(([, value]) => value).join('+')} = ${total} person-days ÷ 5 days each = ${total / 5} → whole people: ${Math.ceil(total / 5)}`));
    const check = await readFile(path.join(mini, 'check.py'), 'utf8');
    assert.match(check, new RegExp(`^LP_BOUND = ${total / 5}$`, 'm'));
    assert.match(check, new RegExp(`^KNOWN_OPTIMUM = ${Math.ceil(total / 5)}$`, 'm'));
  });

  await t.test('#plan’s Monday column is the wraparound’s', async () => {
    // Row = start day, column = weekday; Monday is covered by the blocks that start Thu to Mon, so Tue and Wed are off.
    const monday = await topic('plan').evaluate(el => [...el.querySelectorAll('.pl-mon-on, .pl-mon-off')].map(cell => cell.classList[0]));
    const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
    assert.deepEqual(monday, days.map((_, start) => (0 - start + 7) % 7 < 5 ? 'pl-mon-on' : 'pl-mon-off'));
    assert.equal(await topic('plan').locator('[data-rp-right]').textContent(), 'Tue + Wed');
  });

  for (const id of predicts) {
    await t.test(`#${id}: the room’s pick, then what happened revealed beside it, then Reset`, async () => {
      await goTo(id);
      const slide = topic(id);
      const chips = slide.locator('[data-rp-chip]');
      const state = () => slide.evaluate(el => {
        const answer = [...el.querySelectorAll('.rp-ans')].map(node => getComputedStyle(node).visibility);
        return {
          answer: answer.length && answer.every(v => v === 'visible') ? 'shown' : answer.every(v => v === 'hidden') ? 'hidden' : 'partly shown',
          pressed: [...el.querySelectorAll('[data-rp-chip]')].flatMap((chip, i) => chip.getAttribute('aria-pressed') === 'true' ? [i] : []),
        };
      });
      await eventually(async () => assert.deepEqual(await state(), { answer: 'hidden', pressed: [] }), 'the answer starts hidden');
      await chips.nth(0).click();
      await chips.nth(1).click();
      assert.deepEqual((await state()).pressed, [1], 'one pick at a time');
      await stillTurns(id);
      await slide.locator('[data-rp-reveal]').click();
      await eventually(async () => assert.deepEqual(await state(), { answer: 'shown', pressed: [1] }), 'the answer shows beside the pick');
      await stillTurns(id);
      await slide.locator('[data-rp-reset]').click();
      await eventually(async () => assert.deepEqual(await state(), { answer: 'hidden', pressed: [] }), 'Reset hides the answer and clears the pick');
      await stillTurns(id);
    });
  }

  await t.test('every Copy in the steps’ notes copies its own command or prompt', async () => {
    for (const id of withCommands) {
      const notes = topic(id).locator('details.speaker-notes');
      const targets = await notes.locator('button[data-copy]').evaluateAll(els => els.map(el => el.dataset.copy));
      assert.deepEqual(await notes.locator('pre[id]').evaluateAll(els => els.map(el => el.id)), targets, `#${id}: a Copy per command or prompt`);
      await goTo(id);
      await notes.locator(':scope > summary').click();
      for (const [i, target] of targets.entries()) {
        await notes.locator('button[data-copy]').nth(i).click();
        await eventually(async () => assert.equal(await page.evaluate(() => navigator.clipboard.readText()),
          await notes.locator(`pre#${target}`).textContent()), `#${id}: Copy ${target}`);
      }
      await stillTurns(id);
    }
  });
});
