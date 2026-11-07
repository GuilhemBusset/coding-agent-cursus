import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { chromium } from '../../../../tools/html-pages/browser.mjs';
import { openPage, repoRoot, eventually } from '../../../../tools/html-pages/tests/component-helpers.mjs';

// Act II deck: what would break in front of the room. The puzzle, the quoted reply and the effort
// chart are the effort demo's recording; each slide control (the van, the bet, the waffles, "Ask it
// how", Copy) works, and after a pointer press the clicker's → still turns the slide.
// check-page covers the rest of every deck: layout, accessibility, navigation, links, no-JS and print.
const cursus = path.join(repoRoot, 'sessions/01-fundamentals/cursus');
const file = path.join(cursus, '02-thinking.html');
const sum = values => values.reduce((a, b) => a + b, 0);
const digits = text => text.replace(/(\d),(?=\d{3}\b)/g, '$1');

// The effort demo's puzzle, from its prompt: the capacity and the eight parcels.
async function puzzle() {
  const prompt = await readFile(path.join(cursus, 'demos/effort/prompt.txt'), 'utf8');
  const capacity = Number(prompt.match(/capacity of (\d+) kg/)?.[1]);
  const parcels = [...prompt.matchAll(/^\| ([A-H]) \| (\d+) \| (\d+) \|$/gm)].map(m => ({ name: m[1], kg: Number(m[2]), eur: Number(m[3]) }));
  assert.equal(parcels.length, 8, 'the prompt lists eight parcels');
  const weigh = names => {
    const chosen = parcels.filter(p => names.includes(p.name));
    return { kg: sum(chosen.map(p => p.kg)), eur: sum(chosen.map(p => p.eur)) };
  };
  return { prompt, capacity, parcels, weigh };
}

test('Act II deck', async t => {
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
  const { prompt, capacity, parcels, weigh } = await puzzle();
  const results = JSON.parse(await readFile(path.join(cursus, 'demos/effort/recorded/results.json'), 'utf8'));
  const runs = ['low', 'high', 'max'].map(effort => results.runs.find(r => r.cli === 'claude' && r.effort === effort));
  const [low] = runs;

  await t.test('the opener’s van holds the effort demo prompt’s parcels and capacity', async () => {
    assert.equal(capacity, results.puzzle.capacity);
    const opener = topic('loop');
    const shelf = await opener.locator('[data-van-parcel]').evaluateAll(els => els.map(el => ({
      data: [el.dataset.vanParcel, Number(el.dataset.kg), Number(el.dataset.eur)],
      drawn: [el.textContent.trim()[0], ...(el.textContent.match(/\d+/g) || []).map(Number)],
    })));
    const expected = parcels.map(p => [p.name, p.kg, p.eur]);
    assert.deepEqual(shelf.map(parcel => parcel.data), expected, 'the shelf holds the prompt’s parcels');
    assert.deepEqual(shelf.map(parcel => parcel.drawn), expected, 'each parcel shows its weight and value');
    const table = await opener.locator('table.parcels').evaluate(el => {
      const rows = [...el.querySelectorAll('tr')].map(tr => [...tr.cells].map(cell => cell.textContent.trim()));
      return rows[0].slice(1).map((name, i) => [name, Number(rows[1][i + 1]), Number(rows[2][i + 1])]);
    });
    assert.deepEqual(table, expected, 'the table for assistive tech holds the same parcels');
    assert.equal(Number(await opener.locator('[data-van]').getAttribute('data-capacity')), capacity);
  });

  await t.test('part 1 quotes the recorded reply, and counts its recorded thinking tokens', async () => {
    const raw = await readFile(path.join(cursus, 'demos/effort/recorded/raw/claude-low.jsonl'), 'utf8');
    const reply = raw.split('\n').filter(Boolean).map(line => JSON.parse(line)).filter(event => event.type === 'assistant')
      .flatMap(event => event.message.content).filter(part => part.type === 'text').map(part => part.text.replace(/\*\*/g, '')).join('\n');
    const lines = await topic('cot-depth').locator('.reply blockquote p').allTextContents();
    assert.ok(lines.length > 0, 'the slide quotes the reply');
    for (const line of lines) assert.ok(reply.includes(line.replace(/\s+/g, ' ').trim()), `quoted from the recording: ${line}`);
    const face = await topic('cot-depth').evaluate(el => {
      const copy = el.cloneNode(true);
      copy.querySelectorAll('details.speaker-notes').forEach(node => node.remove());
      return copy.textContent;
    });
    assert.match(digits(face), new RegExp(`\\b${low.tokens.thinking} tokens\\b`), 'the recorded thinking count');
  });

  await t.test('#effort-demo draws the recorded runs to scale, and its notes read out the recorded fallback', async () => {
    await goTo('effort-demo');
    const drawn = await topic('effort-demo').locator('[data-eff-row]').evaluateAll(els => els.map(row => {
      const box = el => el.getBoundingClientRect();
      return {
        bars: [...row.querySelectorAll('.eff-bar')].map(bar => ({
          left: box(bar).left, width: box(bar).width,
          parts: [...bar.querySelectorAll(':scope > i')].map(part => box(part).width),
          label: bar.closest('.eff-run')?.querySelector('.eff-out')?.textContent ?? null,
        })),
        lanes: [...row.querySelectorAll('.eff-lane')].map(lane => lane.textContent.trim()),
        chips: Object.fromEntries([...row.querySelectorAll('[data-eff-chip]')].map(chip => [chip.textContent, box(chip).left + box(chip).width / 2])),
      };
    }));
    assert.equal(drawn.length, 2, 'two rows: the tokens and the bill');
    const [tokens, bill] = drawn;
    const close = (a, b, tolerance, label) => assert.ok(Math.abs(a - b) <= tolerance, `${label}: drawn ${a}, expected ${b}`);
    for (const [name, row] of [['tokens', tokens], ['bill', bill]]) {
      assert.deepEqual(row.lanes, ['low', 'high', 'max'], `${name}: a lane per effort`);
      // One scale per row, in times low effort: each bet chip sits at its own value on it.
      const unit = row.bars[0].width;
      for (const v of [1, 2, 5, 10]) close(row.chips[`×${v}`], row.bars[0].left + v * unit, 2, `${name}: chip ×${v} on the scale`);
    }
    const rate = results.prices.anthropic.models[low.model].output / 1e6;
    runs.forEach((r, i) => {
      close(tokens.bars[i].width / tokens.bars[0].width, r.tokens.output / low.tokens.output, 0.01, `tokens: ${r.effort} against low`);
      close(bill.bars[i].width / bill.bars[0].width, r.cost_usd / low.cost_usd, 0.01, `bill: ${r.effort} against low`);
      const share = parts => parts[0] / sum(parts);
      close(share(tokens.bars[i].parts), r.tokens.thinking / r.tokens.output, 0.01, `${r.effort}: thinking share`);
      close(share(bill.bars[i].parts), (r.cost_usd - r.tokens.output * rate) / r.cost_usd, 0.01, `${r.effort}: the prompt’s share of the bill`);
      if (i === 0) return;
      for (const n of [low.tokens.output, r.tokens.output]) assert.ok(digits(tokens.bars[i].label).includes(String(n)), `${r.effort}: ${tokens.bars[i].label} shows ${n}`);
      for (const n of [low.cost_usd, r.cost_usd]) assert.ok(bill.bars[i].label.includes(n.toFixed(3)), `${r.effort}: ${bill.bars[i].label} shows ${n}`);
    });
    const talk = digits(await topic('effort-demo').locator('details.speaker-notes').textContent());
    for (const r of results.runs) {
      assert.ok(talk.includes(`${r.tokens.output} output tokens`), `${r.model} ${r.effort}: output tokens in the notes`);
      assert.ok(talk.includes(`$${r.cost_usd.toFixed(4)}`), `${r.model} ${r.effort}: cost in the notes`);
    }
  });

  await t.test('the van loads, sums and spills over, and Reset empties it', async () => {
    await goTo('loop');
    const slide = topic('loop');
    const parcel = name => slide.locator(`[data-van-parcel="${name}"]`);
    const holds = async names => {
      const seen = await slide.evaluate(el => ({
        kg: Number(el.querySelector('[data-van-kg]').textContent), eur: Number(el.querySelector('[data-van-eur]').textContent),
        over: el.querySelector('[data-van-bay]').hasAttribute('data-over'),
        loaded: [...el.querySelectorAll('[data-van-block]')].map(block => block.dataset.vanBlock),
        pressed: [...el.querySelectorAll('[data-van-parcel][aria-pressed="true"]')].map(button => button.dataset.vanParcel),
      }));
      const { kg, eur } = weigh(names);
      assert.deepEqual(seen, { kg, eur, over: kg > capacity, loaded: names, pressed: [...names].sort() }, `the van holds ${names.join(', ') || 'nothing'}`);
    };
    await holds([]);
    await parcel('B').click();
    await parcel('D').click();
    await holds(['B', 'D']);
    await stillTurns('loop');
    await parcel('A').click();
    await parcel('H').click();
    assert.ok(weigh(['B', 'D', 'A', 'H']).kg > capacity, 'this load is over the limit');
    await holds(['B', 'D', 'A', 'H']);
    await parcel('H').click();
    await holds(['B', 'D', 'A']);
    await slide.locator('[data-van-reset]').click();
    await holds([]);
    await stillTurns('loop');
  });

  await t.test('the room bets on #effort-demo, Reveal shows the run beside the bets, Reset hides it', async () => {
    await goTo('effort-demo');
    const slide = topic('effort-demo');
    const rows = slide.locator('[data-eff-row]');
    const chip = (row, text) => rows.nth(row).locator('[data-eff-chip]').filter({ hasText: new RegExp(`^${text}$`) });
    const state = () => slide.evaluate(el => ({
      run: [...el.querySelectorAll('[data-eff-run]')].map(run => getComputedStyle(run).visibility),
      bets: [...el.querySelectorAll('[data-eff-row]')].map(row => [...row.querySelectorAll('[aria-pressed="true"]')].map(b => b.textContent)),
    }));
    const hidden = Array(4).fill('hidden'), shown = Array(4).fill('visible');
    await eventually(async () => assert.deepEqual(await state(), { run: hidden, bets: [[], []] }), 'the run starts hidden');
    await chip(0, '×2').click();
    await chip(0, '×5').click();
    await chip(1, '×2').click();
    assert.deepEqual((await state()).bets, [['×5'], ['×2']], 'one chip per row');
    await chip(1, '×2').click();
    assert.deepEqual((await state()).bets, [['×5'], []], 'pressing the marked chip again unmarks it');
    await stillTurns('effort-demo');
    // A double-click on Reveal lands its second click on the board, which must not trap the keys.
    await slide.locator('[data-eff-reveal]').dblclick();
    await eventually(async () => assert.deepEqual(await state(), { run: shown, bets: [['×5'], []] }), 'revealed beside the bets');
    await stillTurns('effort-demo');
    await slide.locator('[data-eff-reset]').click();
    await eventually(async () => assert.deepEqual(await state(), { run: hidden, bets: [[], []] }), 'Reset hides the run and clears the bets');
    await stillTurns('effort-demo');
  });

  await t.test('the waffles empty for a guess, fill to their printed counts on Reveal, and empty again', async () => {
    await goTo('cot-faithfulness');
    const chart = topic('cot-faithfulness').locator('[data-cf-chart]');
    const toggle = topic('cot-faithfulness').locator('[data-cf-toggle]');
    // Per waffle, the cells drawn like the legend's "says so" key, and the count printed beside it.
    const waffles = () => chart.evaluate(el => {
      const on = getComputedStyle(el.querySelector('.cf-head i.on')).backgroundColor;
      return [...el.querySelectorAll('.cf-model')].map(model => ({
        filled: [...model.querySelector('.cf-waffle').children].filter(cell => getComputedStyle(cell).backgroundColor === on).length,
        printed: Number(model.querySelector('.cf-num .cf-v').textContent),
      }));
    });
    const printed = (await waffles()).map(w => w.printed);
    assert.deepEqual(printed.map(n => n > 0), [true, true]);
    await eventually(async () => assert.deepEqual((await waffles()).map(w => w.filled), [0, 0]), 'empty for the guess');
    // One button reveals and resets: a double-click must not undo the reveal it just made.
    await toggle.dblclick();
    await eventually(async () => assert.deepEqual((await waffles()).map(w => w.filled), printed), 'filled on Reveal');
    await stillTurns('cot-faithfulness');
    await toggle.click();
    await eventually(async () => assert.deepEqual((await waffles()).map(w => w.filled), [0, 0]), 'empty after Reset');
    await stillTurns('cot-faithfulness');
  });

  await t.test('“Ask it how” reveals what the model said about its sum, and Reset hides it', async () => {
    await goTo('addition-36-59');
    const slide = topic('addition-36-59');
    const said = () => slide.evaluate(el => ({
      shown: getComputedStyle(el.querySelector('.add-quote')).visibility === 'visible',
      read: el.querySelector('[data-add-answer]').getAttribute('aria-hidden') !== 'true',
    }));
    assert.deepEqual(await said(), { shown: false, read: false });
    // Reset replaces "Ask it how" in place: a double-click must not ask and reset at once.
    await slide.locator('[data-add-ask]').dblclick();
    assert.deepEqual(await said(), { shown: true, read: true });
    await stillTurns('addition-36-59');
    await slide.locator('[data-add-reset]').click();
    assert.deepEqual(await said(), { shown: false, read: false });
    await stillTurns('addition-36-59');
  });

  await t.test('Copy in the opener’s notes puts the demo prompt and the launch command on the clipboard', async () => {
    await goTo('loop');
    const notes = topic('loop').locator('details.speaker-notes');
    await notes.locator(':scope > summary').click();
    const clipboard = () => page.evaluate(() => navigator.clipboard.readText());
    await notes.locator('button[data-copy="loop-prompt"]').click();
    await eventually(async () => assert.equal(await clipboard(), prompt.replace(/\n$/, '')), 'the prompt, word for word prompt.txt');
    await notes.locator('button[data-copy="loop-command"]').click();
    await eventually(async () => assert.equal(await clipboard(), await notes.locator('pre#loop-command').textContent()), 'the command');
    assert.match(await clipboard(), new RegExp(`--model ${low.model}\\b.*--effort low\\b`), 'the recorded run’s model and effort');
    await stillTurns('loop');
  });
});
