#!/usr/bin/env node
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';

const root = path.dirname(fileURLToPath(import.meta.url));
const usage = 'Usage: node tools/html-pages/create-page.mjs --kind page|deck|lab --title "Title" --out path.html';

export async function createPage({ kind, title, out }) {
  if (!['page', 'deck', 'lab'].includes(kind)) throw new Error('Choose --kind page, deck, or lab.');
  if (!title?.trim()) throw new Error('A nonempty --title is required.');
  if (!out || !/\.html?$/i.test(out)) throw new Error('--out must name an .html or .htm file.');
  const [template, style, script] = await Promise.all([
    readFile(path.join(root, 'templates', `${kind}.html`), 'utf8'),
    readFile(path.join(root, 'assets', 'theme.css'), 'utf8'),
    readFile(path.join(root, 'assets', 'page.js'), 'utf8'),
  ]);
  const escapedTitle = title.replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[char]);
  const values = { TITLE: escapedTitle, STYLE: style, SCRIPT: script };
  const snapshot = (name, value) => `<meta name="cursus-${name}-sha256" content="${createHash('sha256').update(value).digest('hex')}">`;
  const html = template.replace(/\{\{(TITLE|STYLE|SCRIPT)\}\}/g, (_, key) => values[key])
    .replace('</head>', `  ${snapshot('theme', style)}\n  ${snapshot('script', script)}\n</head>`);
  await mkdir(path.dirname(path.resolve(out)), { recursive: true });
  // Exclusive creation deliberately refuses to overwrite authored material.
  await writeFile(out, html, { flag: 'wx' });
  return path.resolve(out);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const args = process.argv.slice(2);
    if (args.length === 1 && args[0] === '--help') {
      console.log(usage);
    } else {
      const options = {};
      for (let i = 0; i < args.length; i += 2) {
        const key = args[i].replace(/^--/, '');
        if (!['kind', 'title', 'out'].includes(key) || args[i] !== `--${key}` ||
            options[key] !== undefined || !args[i + 1]) throw new Error(usage);
        options[key] = args[i + 1];
      }
      console.log(`Created ${await createPage(options)} — open directly in a browser.`);
    }
  } catch (error) {
    console.error(error.code === 'EEXIST' ? 'Destination already exists; edit it in place.' : error.message);
    process.exitCode = 1;
  }
}
