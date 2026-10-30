#!/usr/bin/env node
// `npm --prefix setup run check-repo`: check-page.mjs on every Cursus teaching page, or only on
// the pages named as arguments (repo-relative, as scripts/check-changed.sh passes them). Pages are
// independent (each run launches its own browser and writes its own mkdtemp report), so several
// run at once: one per core but one, like `node --test`, capped at 8, or CURSUS_CHECK_JOBS.
// Decks with the most slides go first (check-page's cost grows with slides), so a long deck never
// starts last. Each page's output is printed whole when it finishes.
import { execFileSync, spawn } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import { availableParallelism } from 'node:os';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const named = process.argv.slice(2);
const files = named.length ? [...new Set(named)]
  : [...new Set(execFileSync('git', ['ls-files', '-z', '--cached', '--others', '--exclude-standard'], { cwd: root, encoding: 'utf8' }).split('\0'))]
    .filter(file => /^(docs|sessions)\/.*\.html?$/i.test(file));
const pages = [];
for (const file of files) {
  let html;
  try { html = await readFile(path.join(root, file), 'utf8'); }
  catch (error) { if (error.code === 'ENOENT' && !named.length) continue; throw error; }
  if (!/data-design-system\s*=\s*["']cursus["']/i.test(html)) {
    if (named.length) { console.error(`Not a Cursus teaching page: ${file}`); process.exit(2); }
    continue;
  }
  pages.push({ file, slides: html.match(/\bdata-slide\b/g)?.length ?? 0 });
}
pages.sort((a, b) => b.slides - a.slides || a.file.localeCompare(b.file));

const requested = process.env.CURSUS_CHECK_JOBS;
if (requested !== undefined && !/^[1-9]\d*$/.test(requested)) {
  console.error(`CURSUS_CHECK_JOBS must be a positive integer, not ${JSON.stringify(requested)}`);
  process.exit(2);
}
const jobs = Math.min(pages.length || 1, requested ? Number(requested) : Math.min(8, Math.max(1, availableParallelism() - 1)));

function check(file) {
  return new Promise(resolve => {
    const child = spawn(process.execPath, ['tools/html-pages/check-page.mjs', file], { cwd: root, stdio: ['ignore', 'pipe', 'pipe'] });
    let output = '';
    child.stdout.on('data', chunk => { output += chunk; });
    child.stderr.on('data', chunk => { output += chunk; });
    child.on('error', error => resolve({ file, output: `${output}${error.message}\n`, passed: false }));
    child.on('close', (code, signal) => resolve({ file, output: signal ? `${output}check-page was terminated by ${signal}\n` : output, passed: code === 0 }));
  });
}

let next = 0, failed = 0;
async function worker() {
  while (next < pages.length) {
    const { file } = pages[next++];
    const result = await check(file);
    if (!result.passed) failed++;
    process.stdout.write(`${result.passed ? 'ok' : 'FAILED'} ${file}\n${result.output}`);
  }
}
await Promise.all(Array.from({ length: jobs }, worker));
console.log(`Checked ${pages.length} Cursus teaching page(s), ${jobs} at a time${failed ? `; ${failed} failed` : ''}.`);
if (failed) process.exitCode = 1;
