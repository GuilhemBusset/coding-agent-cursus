#!/usr/bin/env node
// The loop needs positive accounting: an empty or skipped suite is not evidence.
import { spawn } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export function completePass(tap, code) {
  const count = name => {
    const matches = [...tap.matchAll(new RegExp(`^# ${name} (\\d+)\\s*$`, 'gm'))];
    return matches.length === 1 ? Number(matches[0][1]) : NaN;
  };
  const tests = count('tests');
  const skipped = Number.isNaN(count('skipped')) ? count('skip') : count('skipped');
  return code === 0 && tests > 0 && count('pass') === tests &&
    count('fail') === 0 && count('cancelled') === 0 && skipped === 0 && count('todo') === 0 &&
    !/^\s*(?:not )?ok\b[^\n]*#\s*(?:SKIP|TODO)\b/im.test(tap);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (process.argv.length !== 3 || !process.argv[2].endsWith('.mjs')) {
    console.error('Usage: node run-suite.mjs <suite.mjs>');
    process.exitCode = 1;
  } else {
    const child = spawn(process.execPath, ['--test', '--test-reporter=tap', path.resolve(process.argv[2])], {
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    let tap = '';
    child.stdout.on('data', chunk => { tap += chunk; process.stdout.write(chunk); });
    child.stderr.on('data', chunk => process.stderr.write(chunk));
    child.on('error', error => { console.error(error.message); process.exitCode = 1; });
    child.on('close', code => {
      if (!completePass(tap, code)) {
        console.error('Suite rejected: require nonzero tests, all passing, no failures/cancellations/skips/todos.');
        process.exitCode = 1;
      }
    });
  }
}
