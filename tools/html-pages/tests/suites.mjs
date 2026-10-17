// Suite discovery: a Node suite is any regular file named *.test.mjs directly in this directory.
// `npm --prefix setup test` (run-all.mjs) and component-helpers' `suites` both list them from
// here, so adding a suite file is all it takes to have it collected: there is no list to edit.
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
