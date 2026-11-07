import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { chromium } from '../../../../tools/html-pages/browser.mjs';
import { openPage, repoRoot, eventually } from '../../../../tools/html-pages/tests/component-helpers.mjs';

// Act IV deck: what would break in front of the room. The worked row is Act III's recording, the lab
// steps' commands are the lab page's, the lower bounds are the P00 data's; each predict and Copy works,
// and after a pointer press the clicker's → still turns the slide.
// #catch and #l3 are checked against P00 itself in sessions/01-fundamentals/tests/test_evidence_deck.py.
// check-page covers the rest of every deck: layout, accessibility, navigation, links, no-JS and print.
const session = path.join(repoRoot, 'sessions/01-fundamentals');
const cursus = path.join(session, 'cursus');
const runs = path.join(cursus, 'fixtures/runs');
const p00 = path.join(session, 'exercises/p00-lab');
const file = path.join(cursus, '04-evidence.html');
const labSteps = ['l1', 'l2', 'l3', 'l4'];
const predicts = ['l2', 'catch', 'l3', 'l4'];
const norm = value => value.normalize('NFKC').replace(/[‘’]/g, "'").replace(/[“”]/g, '"')
  .replace(/[−–]/g, '-').replace(/\s+/g, ' ').trim().toLowerCase();
const json = async file => JSON.parse(await readFile(file, 'utf8'));
const csv = async file => {
  const [head, ...rows] = (await readFile(file, 'utf8')).trim().split(/\r?\n/).map(line => line.split(','));
  return rows.map(row => Object.fromEntries(head.map((key, i) => [key.trim(), row[i].trim()])));
};

test('Act IV deck', async t => {
  const page = await openPage(t, chromium, { file, permissions: ['clipboard-read', 'clipboard-write'] });
  const topic = id => page.locator(`section[data-slide]#${id}`);
  const slides = page.locator('main[data-deck] section[data-slide]');
  // Everything a viewer can read on a face, pictures included: one entry per SVG text or HTML text node.
  const shown = id => topic(id).evaluate(el => {
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

  await t.test('the opener’s worked row is Act III’s recorded run', async () => {
    const run = await json(path.join(runs, 'flipped-sense-claude.json'));
    const meta = await json(path.join(runs, 'raw/flipped-sense-claude.meta.json'));
    const claim = run.steps.filter(step => step.type === 'message').at(-1).text.split(/(?<=\.)\s/)[0];
    const row = await shown('your-turn');
    assert.ok(row.includes(norm(`“${claim}”`)), `the run’s claim, quoted: ${claim}`);
    assert.equal(meta.verification.post.exit_code, 0);
    assert.ok(row.includes(`uv run pytest | → | ${meta.verification.post.summary.match(/^\d+ passed/)[0]}`), 'the run’s own pytest after the fix');
    for (const line of meta.changed_files) assert.ok(row.includes(`git status --short | → | ${norm(line)}`), `git status shows ${line}`);
  });

  await t.test('the lab steps’ notes carry the lab page’s commands and prompts, exactly as it prints them', async () => {
    const source = await readFile(path.join(session, 'exercises/lab-ladder.html'), 'utf8');
    // Parsed inertly in the browser: the lab page's own pre blocks, per level section.
    const onPage = await page.evaluate(({ source, ids }) => {
      const doc = new DOMParser().parseFromString(source, 'text/html');
      return Object.fromEntries(ids.map(id => [id, [...doc.querySelectorAll(`section#${id}[data-level] pre`)].map(pre => pre.textContent)]));
    }, { source, ids: labSteps });
    for (const id of labSteps) {
      const pres = await topic(id).locator('details.speaker-notes pre[id]').allTextContents();
      assert.ok(pres.length > 0, `#${id}’s notes carry the level’s commands`);
      for (const text of pres) assert.ok(onPage[id].includes(text), `#${id}: the lab page’s ${id.toUpperCase()} prints “${text.slice(0, 60)}…”`);
    }
  });

  await t.test('#gap’s lower bounds are the P00 data’s, recomputed here', async () => {
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
    const drawn = await shown('gap');
    for (let mask = 1; mask < 1 << ids.length; mask++) {
      const open = ids.filter((_, i) => mask & (1 << i));
      const chosen = plants.filter(p => open.includes(p[plantKey]));
      const capacity = chosen.reduce((sum, p) => sum + Number(p[capKey]), 0);
      // A single plant cannot cover the demand, so the slide has no row for one.
      if (open.length === 1) { assert.ok(capacity < demand, `${open} alone cannot cover ${demand}`); continue; }
      const fixed = chosen.reduce((sum, p) => sum + Number(p[fixedKey]), 0);
      const routes = customers.reduce((sum, c) => sum + Number(c[demKey]) * Math.min(...open.map(p => unit(p, c[custKey]))), 0);
      for (const n of [fixed + routes, fixed, routes]) assert.ok(drawn.includes(`${n}`), `#gap shows ${open.join(' + ')}: ${fixed + routes} = ${fixed} + ${routes}`);
    }
  });

  await t.test('#this-repo’s bypass list is the ruleset’s', async () => {
    const ruleset = await json(path.join(repoRoot, 'setup/pr-only-main.json'));
    assert.ok((await shown('this-repo')).includes(`bypass list: ${ruleset.bypass_actors.length}`));
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

  await t.test('every Copy in the lab steps’ notes copies its own command or prompt', async () => {
    for (const id of labSteps) {
      const notes = topic(id).locator('details.speaker-notes');
      const targets = await notes.locator('button[data-copy]').evaluateAll(els => els.map(el => el.dataset.copy));
      assert.deepEqual(await notes.locator('pre[id]').evaluateAll(els => els.map(el => el.id)), targets, `#${id}: a Copy per command or prompt`);
      await goTo(id);
      await notes.locator(':scope > summary').click();
      const button = notes.locator('button[data-copy]').first();
      await button.click();
      await eventually(async () => assert.equal(await page.evaluate(() => navigator.clipboard.readText()),
        await notes.locator(`pre#${targets[0]}`).textContent()), `#${id}: Copy ${targets[0]}`);
      await stillTurns(id);
    }
  });
});
