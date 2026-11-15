/** Process entry point. No harness import occurs until credentials are captured and removed. */
import { readFileSync } from 'node:fs';
import { registerHooks } from 'node:module';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { createBoundary, sanitizer, Stop } from './boundary.ts';

// Resolve public support and snapshot imports against the session's locked npm
// install, even when TMPDIR is on another drive. No global modules or symlinks.
registerHooks({ resolve(specifier, context, next) {
  if (!specifier.startsWith('.') && !specifier.startsWith('/') && !specifier.includes(':') &&
      !context.parentURL?.includes('/node_modules/')) {
    return next(specifier, { ...context, parentURL: new URL('../../../package.json', import.meta.url).href });
  }
  return next(specifier, context);
} });
const spec = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const credentialEnv: NodeJS.ProcessEnv = {};
for (const [key, value] of Object.entries(process.env)) {
  if (key === 'OPENAI_API_KEY' || key === 'COURSE_API_KEY' || key.startsWith('COURSE_ENDPOINT_')) credentialEnv[key] = value;
}
const clean = sanitizer(Object.values(credentialEnv).filter((s): s is string => !!s));
const originalError = console.error;
for (const name of ['log', 'warn', 'error', 'info', 'debug'] as const) {
  console[name] = (...values: unknown[]) => originalError(...clean(values));
}
const adapter = await import(pathToFileURL(join(spec.support, 'exercises/fixed/model/adapter.ts')).href);
const bridge = await import(pathToFileURL(join(spec.support, 'exercises/fixed/bridge/bridge.ts')).href);
let transport: typeof fetch | undefined;
if (spec.script) {
  // Deterministic offline transport. The script never enters research context.
  // It is NOT a replay or a live compatibility certificate.
  const script = JSON.parse(readFileSync(spec.script, 'utf8'));
  let index = 0;
  transport = async (_target, init) => {
    const step = script[index++];
    if (!step) throw new Error('script exhausted');
    if (step.stall) return new Promise((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new Error('cancelled')), { once: true });
    });
    if (step.throw) throw new Error('scripted transport error');
    return new Response(step.body ?? '', { status: step.status ?? 200,
      headers: { 'content-type': 'text/event-stream' } });
  };
  credentialEnv.OPENAI_API_KEY ??= 'sk-offline-script';
  credentialEnv.COURSE_API_KEY ??= 'offline-script';
  const endpointField = `COURSE_ENDPOINT_${spec.settings.connection.endpoint_alias.toUpperCase().replaceAll('-', '_')}`;
  credentialEnv[endpointField] ??= 'https://offline.invalid/v1';
}
const boundary = createBoundary(spec, { createAdapter: adapter.createAdapter, callTool: bridge.callTool,
  declarations: spec.tools.map((name: string) => ({ name, description: bridge.descriptions[name], parameters: bridge.schemas[name] })) }, credentialEnv, transport);
for (const key of Object.keys(credentialEnv)) delete process.env[key];
let reason = 'no_progress';
try {
  const harness = await import(pathToFileURL(join(spec.workspace, 'harness/main.ts')).href);
  const output = await harness.run(boundary.api);
  if (output) { boundary.api.saveOutput(output); reason = output.stop_reason ?? 'completed'; }
} catch (error) {
  reason = error instanceof Stop ? error.reason : 'harness_error';
} finally {
  boundary.finish(reason);
}
