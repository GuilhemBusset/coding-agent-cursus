#!/usr/bin/env node
// Cross-platform author setup; does not change agent configuration or git hooks.
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const directory = path.dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const usage = 'Usage: node setup/html-pages.mjs [--with-system-deps]\n' +
  'Installs locked npm dependencies and Chromium, then checks offline file rendering.\n' +
  '--with-system-deps also installs browser OS libraries (Linux may prompt for sudo).';

function run(command, args, shell = false) {
  const result = spawnSync(command, args, { cwd: directory, stdio: 'inherit', shell });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`${path.basename(command)} failed (${result.signal ?? result.status}).`);
}

try {
  if (args.length === 1 && args[0] === '--help') {
    console.log(usage);
  } else {
    if (args.length > 1 || (args.length === 1 && args[0] !== '--with-system-deps')) throw new Error(usage);
    if (Number(process.versions.node.split('.')[0]) < 22) throw new Error('Node.js 22 or newer, including npm, is required. See setup/README.md.');
    console.log(`HTML author setup: ${directory}\nNode ${process.version}`);
    // npm.cmd needs a shell on Windows; its arguments here are fixed, not user input.
    run(process.platform === 'win32' ? 'npm.cmd' : 'npm', ['ci', '--include=dev'], process.platform === 'win32');
    const cli = path.join(directory, 'node_modules/playwright/cli.js');
    console.log(args.length ? 'Installing Chromium and OS libraries; Linux may request sudo.' : 'Installing Chromium; OS packages are unchanged.');
    run(process.execPath, [cli, 'install', ...(args.length ? ['--with-deps'] : []), '--no-remove', 'chromium']);
    run(process.execPath, [path.join(directory, 'doctor.mjs')]);
    console.log('HTML author setup complete. Run npm --prefix setup test for the full suite.');
  }
} catch (error) {
  console.error(`HTML author setup failed: ${error.message}`);
  process.exitCode = 1;
}
