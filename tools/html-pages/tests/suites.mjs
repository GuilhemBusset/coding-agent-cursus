// Suite discovery: a Node suite is any regular file named *.test.mjs directly in one of the suite
// directories. `npm --prefix setup test` (run-all.mjs) and component-helpers' assertCollected both
// list them from here, so adding a suite file is all it takes to have it collected.
import { readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const testsDir = path.dirname(fileURLToPath(import.meta.url));
export const SUITE_SUFFIX = '.test.mjs';

/** Absolute paths of the suites in `dir` (this directory by default), sorted. Not recursive. */
export function discoverSuites(dir = testsDir) {
  return readdirSync(dir, { withFileTypes: true })
    .filter(entry => entry.isFile() && entry.name.endsWith(SUITE_SUFFIX))
    .map(entry => path.join(dir, entry.name))
    .sort();
}

// The suite directories: this one (the page tooling's own suites), then each session's test parts
// (sessions/<NN>-*/tests/<part>/, where a session's lesson suites live next to its lesson pytest).
// tools/test-impact/impact.py's SUITE_GLOBS lists the same. A folder that does not exist is skipped,
// so a copy of this file elsewhere lists only its own directory.
const sessionsDir = path.resolve(testsDir, '../../../sessions');
const subdirs = dir => {
  try {
    return readdirSync(dir, { withFileTypes: true }).filter(entry => entry.isDirectory()).map(entry => path.join(dir, entry.name)).sort();
  } catch {
    return [];
  }
};
export const suiteDirs = [testsDir, ...subdirs(sessionsDir).flatMap(session => subdirs(path.join(session, 'tests')))];

/** Absolute paths of the suites in every suite directory. */
export const discoverAllSuites = () => suiteDirs.flatMap(dir => discoverSuites(dir));
