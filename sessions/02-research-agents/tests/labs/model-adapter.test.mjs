import assert from 'node:assert/strict';
import test from 'node:test';
import { mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Agent } from '@earendil-works/pi-agent-core';
import { normalizeContext } from '@earendil-works/pi-ai/utils/transcript';
import { createAdapter, costUSD, normalizeUsage } from '../../exercises/fixed/model/adapter.ts';
import { defaults } from '../../exercises/fixed/config/model.ts';
// Scripted Responses stream, independent of the diagnostic implementation.
function fixture(tool, usage = {
    input_tokens: 100, output_tokens: 20, total_tokens: 120,
    input_tokens_details: { cached_tokens: 10, cache_write_tokens: 5 }, output_tokens_details: { reasoning_tokens: 2 },
}) {
    const item = tool ? { type: "function_call", id: "fc_echo", call_id: "call_echo", name: "echo", arguments: '{"value":"meter"}' }
        : { type: "message", id: "msg_1", role: "assistant", content: [{ type: "output_text", text: "meter", annotations: [] }] };
    const events = [
        { type: "response.created", response: { id: "resp_1" } },
        { type: "response.output_item.added", output_index: 0, item: { ...item, arguments: "", content: [] } },
        ...(tool ? [
            { type: "response.function_call_arguments.delta", output_index: 0, delta: '{"value":' },
            { type: "response.function_call_arguments.delta", output_index: 0, delta: '"meter"}' },
            { type: "response.function_call_arguments.done", output_index: 0, arguments: item.arguments },
        ] : [{ type: "response.output_text.delta", output_index: 0, content_index: 0, delta: "meter" }]),
        { type: "response.output_item.done", output_index: 0, item },
        { type: "response.completed", response: { id: "resp_1", status: "completed", output: [item], usage } },
    ];
    return events.map(e => `data: ${JSON.stringify(e)}\n\n`).join("");
}

const secret = 'sk-test-SENTINEL_credential';
const env = { OPENAI_API_KEY: secret, COURSE_ENDPOINT_OPENAI: 'https://compatible.example/v1', PI_CACHE_RETENTION: 'long' };
const context = () => normalizeContext({ messages: [{ role: 'user', content: 'diagnostic', timestamp: Date.now() }] });
const response = (body = fixture(false)) => new Response(body, { headers: { 'content-type': 'text/event-stream' } });
const make = (transport, config = {}) => createAdapter({ ...defaults, ...config }, { env, fetch: transport });
async function consume(adapter, signal) {
  const stream = await adapter.streamFn(adapter.model, context(), { signal });
  const output = [];
  for await (const e of stream) output.push(e);
  return { output, result: await stream.result() };
}

test('Agent executes fragmented streamed tool call and sends its result with fixed effective settings', async () => {
  const requests = [];
  const adapter = make(async (target, init) => {
    assert.equal(String(target), 'https://compatible.example/v1/responses');
    assert.equal(init.redirect, 'manual');
    assert.equal(new Headers(init.headers).get('authorization'), `Bearer ${secret}`);
    requests.push(JSON.parse(init.body));
    return response(fixture(requests.length === 1));
  });
  let executed = 0;
  const agent = new Agent({ streamFn: adapter.streamFn, initialState: {
    model: adapter.model, systemPrompt: 'Use echo', tools: [{ name: 'echo', label: 'echo', description: 'Echo',
      parameters: { type: 'object', properties: { value: { type: 'string' } }, required: ['value'] },
      execute: async (_id, args) => {
        assert.deepEqual(args, { value: 'meter' }); executed++;
        return { content: [{ type: 'text', text: 'tool-result-sentinel' }], details: {} };
      } }],
  } });
  await agent.prompt('go');
  assert.equal(executed, 1);
  assert.equal(requests.length, 2);
  assert(requests[1].input.some(x => x.type === 'function_call_output' && x.output === 'tool-result-sentinel'));
  for (const body of requests) {
    assert.equal(body.model, defaults.model);
    assert.deepEqual(body.reasoning, { effort: 'none' });
    assert.equal(body.max_output_tokens, 1024);
    assert.equal(body.store, false);
    for (const omitted of ['temperature', 'seed', 'top_p', 'prompt_cache_retention', 'prompt_cache_key']) assert(!(omitted in body));
  }
  assert.equal(adapter.events.length, 2);
  assert.deepEqual(adapter.events.map(e => e.request_id), ['request-1', 'request-2']);
  assert(adapter.events.every(e => e.status === 'ok'));
  assert.equal(adapter.effectiveSettings.length, 2);
  assert.deepEqual(adapter.effectiveSettings.map(e => e.settings), [defaults.settings, defaults.settings]);
  // A later edit by the caller cannot silently change the comparison configuration.
  assert.equal(adapter.model.baseUrl, 'openai');
  assert(Object.isFrozen(adapter.config) && Object.isFrozen(adapter.config.settings));
});

test('accounting includes visible retry, partial failure, missing usage and cache/reasoning subsets', async () => {
  let calls = 0;
  const adapter = make(async () => ++calls === 1 ? new Response('retry', { status: 429 }) : response());
  await consume(adapter);
  assert.equal(calls, 2); // SDK + Pi retries disabled, only the adapter retries once.
  assert.deepEqual(adapter.events.map(e => [e.request_id, e.attempt_id, e.retry_of, e.status]), [
    ['request-1', 'attempt-1', null, 'error'], ['request-1', 'attempt-2', 'attempt-1', 'ok'],
  ]);
  assert.equal(adapter.events[0].usage.status, 'unknown');
  assert.equal(adapter.events[0].usage.input_tokens, null);
  assert.deepEqual(adapter.events[1].usage, { status: 'complete', input_tokens: 100, output_tokens: 20,
    cache_read_tokens: 10, cache_write_tokens: 5, reasoning_tokens: 2 });
  assert.equal(costUSD(adapter.events[0].usage), null);
  assert.equal(costUSD(adapter.events[1].usage), .00015825);
  assert.equal(adapter.effectiveSettings.length, calls);
  const partial = fixture(false).split('data: {"type":"response.completed"')[0] +
    `data: ${JSON.stringify({ type: 'response.failed', response: { error: { message: secret },
      usage: { input_tokens: 15, output_tokens: 3 } } })}\n\n`;
  const failed = make(async () => response(partial));
  const result = await consume(failed);
  assert.equal(failed.events.length, 1); // Do not retry after exposing partial output.
  assert.equal(failed.events[0].status, 'error');
  assert.deepEqual(failed.events[0].usage, { status: 'partial', input_tokens: 15, output_tokens: 3,
    cache_read_tokens: null, cache_write_tokens: 0, reasoning_tokens: null });
  assert(result.result.content.some(x => x.text === 'meter'));
  assert.equal(result.output.at(-1).type, 'error');
  assert.equal(result.result.errorMessage, 'service_error');
  const absent = make(async () => response(fixture(false, null)));
  await consume(absent);
  assert.deepEqual(absent.events[0].usage, normalizeUsage());
  assert(Object.entries(absent.events[0].usage).filter(([k]) => k !== 'status').every(([, v]) => v === null));
});

test('deadline bounds dispatch and stalled streams; caller cancellation counts only dispatched requests', async () => {
  for (const streaming of [false, true]) {
    let signal;
    const adapter = make(async (_url, init) => {
      signal = init.signal;
      if (!streaming) return new Promise(() => {}); // deliberately uncooperative fake
      return response(new ReadableStream({ start(controller) {
        controller.enqueue(new TextEncoder().encode('data: {"type":"response.created","response":{"id":"resp_stall"}}\n\n'));
      } }));
    }, { timeout_ms: 30 });
    const start = performance.now();
    const { result } = await consume(adapter);
    assert(performance.now() - start < 1000);
    assert.equal(result.errorMessage, 'timeout');
    assert.equal(adapter.events.length, 1);
    assert.equal(adapter.events[0].usage.status, 'unknown');
    assert.equal(signal.aborted, true);
  }
  const controller = new AbortController();
  const adapter = make(async () => { controller.abort(); throw Error(secret); });
  const { result } = await consume(adapter, controller.signal);
  assert.equal(result.errorMessage, 'cancelled');
  assert.equal(adapter.events[0].status, 'cancelled');
  await consume(adapter, controller.signal);
  assert.equal(adapter.events.length, 1); // cancelled before dispatch
});

test('secrets stay out of console, events and saved artifacts; invalid configuration fails before dispatch', async () => {
  const logs = [];
  const originals = [console.log, console.warn, console.error];
  const dir = await mkdtemp(join(tmpdir(), 'adapter-redaction-'));
  let calls = 0;
  try {
    [console.log, console.warn, console.error] = [0, 1, 2].map(() => (...args) => logs.push(args));
    const adapter = make(async () => {
      calls++;
      return new Response(JSON.stringify({ error: { message: `${secret} Authorization: Bearer raw-header-secret https://user:password@example.test/v1?key=query-secret` } }), { status: 401 });
    });
    const failed = await consume(adapter);
    assert.equal(calls, 1);
    const echoed = make(async () => response(fixture(false).replaceAll('meter', `${secret} Authorization: Bearer raw-header-secret https://user:password@example.test/v1?key=query-secret`)));
    const output = await consume(echoed);
    await writeFile(join(dir, 'saved.json'), JSON.stringify({ failed, output, logs, config: adapter.config,
      trace: adapter.events, settings: adapter.effectiveSettings, model: adapter.model }));
    const saved = await readFile(join(dir, 'saved.json'), 'utf8');
    for (const forbidden of [secret, 'raw-header-secret', 'user:password', 'query-secret', 'compatible.example', 'Authorization:']) assert(!saved.includes(forbidden));
    for (const bad of [
      { ...defaults, provider: 'other' }, { ...defaults, endpoint_alias: 'https://user:password@host/?key=query-secret' },
      { ...defaults, model: secret + '/invalid' }, { ...defaults, settings: { ...defaults.settings, temperature: .2 } },
      { ...defaults, settings: { ...defaults.settings, sampling_seed: 42 } },
      { ...defaults, settings: { ...defaults.settings, reasoning: 'high' } },
      { ...defaults, settings: { ...defaults.settings, max_output_tokens: 1 } }, { ...defaults, apiKey: secret },
    ]) assert.throws(() => createAdapter(bad, { env, fetch: async () => { calls++; } }));
    for (const endpoint of ['https://user:password@host/v1', 'https://host/v1?key=query-secret'])
      assert.throws(() => createAdapter(defaults, { env: { ...env, COURSE_ENDPOINT_OPENAI: endpoint } }), /without credentials/);
    assert.equal(calls, 1);
    assert.equal(logs.length, 0);
    for (const folder of ['config', 'model']) {
      const base = new URL(`../../exercises/fixed/${folder}/`, import.meta.url);
      for (const file of await readdir(base, { recursive: true, withFileTypes: true })) {
        if (file.isFile()) assert(!(await readFile(join(file.parentPath, file.name), 'utf8')).includes(secret));
      }
    }
  } finally {
    [console.log, console.warn, console.error] = originals;
    await rm(dir, { recursive: true, force: true });
  }
});

test('network failures have bounded visible retries and redirects never follow an unmetered hop', async () => {
  let calls = 0;
  const network = make(async () => { calls++; throw Error(secret); }, { retries: 2 });
  await consume(network);
  assert.equal(calls, 3);
  assert.equal(network.events.length, 3);
  assert.deepEqual(network.events.map(e => e.retry_of), [null, 'attempt-1', 'attempt-2']);
  const redirect = make(async (_url, init) => {
    assert.equal(init.redirect, 'manual');
    return new Response('', { status: 307, headers: { location: 'https://other.example/v1' } });
  });
  await consume(redirect);
  assert.equal(redirect.events.length, 1);
  assert.equal(redirect.events[0].status, 'error');
});
