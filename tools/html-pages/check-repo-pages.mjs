#!/usr/bin/env node
import { execFileSync, spawnSync } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const files = [...new Set(execFileSync('git', ['ls-files', '-z', '--cached', '--others', '--exclude-standard'], { cwd: root, encoding: 'utf8' }).split('\0'))]
  .filter(file => /^(docs|sessions)\/.*\.html?$/i.test(file));
let checked = 0;
for (const file of files) {
  let html;
  try { html = await readFile(path.join(root, file), 'utf8'); }
  catch (error) { if (error.code === 'ENOENT') continue; throw error; }
  if (!/data-design-system\s*=\s*["']cursus["']/i.test(html)) continue;
  checked++;
  const result = spawnSync(process.execPath, ['tools/html-pages/check-page.mjs', file], { cwd: root, stdio: 'inherit' });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exitCode = 1;
}
console.log(`Checked ${checked} Cursus teaching page(s).`);
