/** Offline schema inventory and evidence smoke, with no provider or credentials. */
import { resolve } from 'node:path';
import { callTool, descriptions, limits, schemas } from './bridge.ts';

const args = process.argv.slice(2);
if (args.length !== 2 || args[0] !== '--case') throw Error('Usage: inspect.ts --case <evidence bundle>');
const sample = await callTool({ caseRoot: resolve(args[1]) }, 'search', { query: 'cost feasibility', limit: 2 }, 'inspect-1');
console.log(JSON.stringify({ schemas, descriptions, limits, sample }, null, 2));
if (sample.result.status !== 'ok') process.exitCode = 1;
