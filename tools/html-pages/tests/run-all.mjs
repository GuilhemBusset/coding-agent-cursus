#!/usr/bin/env node
// `npm --prefix setup test`: run every suite suites.mjs discovers next to this file under one
// `node --test`. Arguments are passed to `node --test` as options (for example
// `npm --prefix setup test -- --test-reporter=tap`). To run one suite with strict accounting,
// use run-suite.mjs instead.
import { spawn } from 'node:child_process';
import { discoverSuites, testsDir } from './suites.mjs';

const files = discoverSuites();
if (files.length === 0) {
  // `node --test` with no files would fall back to its own repository-wide search.
  console.error(`No *.test.mjs suites found in ${testsDir}`);
  process.exit(1);
}
const child = spawn(process.execPath, ['--test', ...process.argv.slice(2), ...files], { stdio: 'inherit' });
child.on('error', error => { console.error(error.message); process.exitCode = 1; });
child.on('exit', (code, signal) => {
  if (signal) console.error(`node --test was terminated by ${signal}`);
  process.exitCode = code ?? 1;
});
