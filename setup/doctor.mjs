#!/usr/bin/env node
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const directory = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(directory, '..');
let browser;
let scratch;
try {
  if (Number(process.versions.node.split('.')[0]) < 22) throw new Error('Node.js 22 or newer is required.');
  const { chromium } = await import('../tools/html-pages/browser.mjs');
  for (const name of ['playwright', '@axe-core/playwright']) {
    const pkg = JSON.parse(await readFile(path.join(directory, 'node_modules', name, 'package.json'), 'utf8'));
    console.log(`${name}: ${pkg.version}`);
  }
  console.log(`Node: ${process.version}\nChromium executable: ${chromium.executablePath()}`);
  scratch = await mkdtemp(path.join(tmpdir(), 'cursus-html-doctor-'));
  const file = path.join(scratch, 'offline.html');
  await writeFile(file, '<!doctype html><html lang="en"><title>Setup check</title><p id="status">Loading</p><script>document.getElementById("status").textContent="Ready";</script></html>');
  browser = await chromium.launch();
  const context = await browser.newContext({ offline: true });
  const page = await context.newPage();
  await page.goto(pathToFileURL(file).href);
  if (await page.locator('#status').textContent() !== 'Ready') throw new Error('Offline HTML did not execute its inline script.');
  console.log('Ready: Chromium launched and rendered local file:// HTML with networking disabled.');
} catch (error) {
  const reason = error.message.match(/error while loading shared libraries:[^\n]+/)?.[0] ?? error.message.split('\n')[0];
  console.error(`Not ready: ${reason}`);
  console.error(`From ${root}, run: node setup/html-pages.mjs`);
  if (process.platform === 'linux') console.error('For missing Linux system libraries, run: node setup/html-pages.mjs --with-system-deps (may prompt for sudo).');
  process.exitCode = 1;
} finally {
  await browser?.close();
  if (scratch) await rm(scratch, { recursive: true, force: true });
}
