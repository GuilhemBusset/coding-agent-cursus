import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from '../browser.mjs';
import { repoRoot, openPage, assertCollected } from './component-helpers.mjs';

// Structure of the Act II deck (issue 40). Prose accuracy is reviewed, not matched here; the
// planner recipe on #repo-model is exercised in a browser by thinking-planner.test.mjs.
const deck = path.join(repoRoot, 'sessions/01-fundamentals/cursus/02-thinking.html');

const slides = page => page.$$eval('[data-slide]', sections => sections.map(section => ({
  id: section.id,
  notes: [...section.querySelectorAll('details.notes')].map(notes => ({
    minutes: notes.dataset.minutes,
    summary: notes.querySelector('summary')?.textContent.trim(),
    text: notes.textContent.trim().length,
  })),
  hrefs: [...section.querySelectorAll('a[href]')].map(a => ({ raw: a.getAttribute('href'), url: a.href })),
})));

test('every slide has speaker notes, and the planned minutes add up to 45', async t => {
  const deckSlides = await slides(await openPage(t, chromium, { file: deck }));
  assert.ok(deckSlides.length >= 10, 'the deck has its slides');
  assert.equal(new Set(deckSlides.map(s => s.id)).size, deckSlides.length, 'slide ids are unique');
  let total = 0;
  for (const { id, notes } of deckSlides) {
    assert.equal(notes.length, 1, `${id} has one speaker-notes block`);
    assert.equal(notes[0].summary, `Speaker notes · ${notes[0].minutes} min`, `${id} notes are labelled with their minutes`);
    assert.ok(notes[0].text > notes[0].summary.length + 40, `${id} notes have content`);
    total += Number(notes[0].minutes);
  }
  assert.equal(total, 45, 'per-slide minutes fill the 45-minute act');
});

test('lab and demo links sit on the right slides and resolve inside the session', async t => {
  const bySlide = new Map((await slides(await openPage(t, chromium, { file: deck }))).map(s => [s.id, s.hrefs]));
  const expected = {
    search: 'labs/test-time-compute.html#best-of-n',
    'sharpen-or-expand': 'labs/test-time-compute.html#sharpen-or-expand',
    overthinking: 'labs/test-time-compute.html#effort-dial',
    kepler: 'labs/world-model.html#kepler',
    'repo-model': 'labs/world-model.html#planner',
    'effort-demo': 'demos/effort/README.md',
  };
  for (const [slide, href] of Object.entries(expected)) {
    const link = bySlide.get(slide)?.find(({ raw }) => raw === href);
    assert.ok(link, `#${slide} links ${href}`);
    const url = new URL(link.url);
    const target = fileURLToPath(url);
    assert.ok(target.startsWith(path.join(repoRoot, 'sessions/01-fundamentals/')), `${href} stays in the session`);
    assert.ok(existsSync(target), `${href} exists`);
    const anchor = url.hash.slice(1);
    if (anchor) assert.match(readFileSync(target, 'utf8'), new RegExp(`\\bid="${anchor}"`), `${href} target id exists`);
  }
});

test('npm --prefix setup test collects thinking', async () => {
  await assertCollected('thinking');
});
