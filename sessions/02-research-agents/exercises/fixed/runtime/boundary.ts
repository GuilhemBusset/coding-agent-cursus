/** Instructor-owned dispatch/accounting. The harness owns research decisions. */
import { appendFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import type { AssistantMessage, Message, Tool } from '@earendil-works/pi-ai';
import { normalizeContext } from '@earendil-works/pi-ai/utils/transcript';
import { validateToolCall } from '@earendil-works/pi-ai/utils/validation';
import type { createAdapter as adapterFactory, Attempt } from '../model/adapter.ts';
import type { callTool as toolFactory, ToolName } from '../bridge/bridge.ts';

type Json = Record<string, any>;
export class Stop extends Error {
  readonly reason: string;
  constructor(reason: string) { super(reason); this.reason = reason; }
}
export function sanitizer(secrets: string[]) {
  const redact = (s: string) => {
    for (const secret of secrets.filter(Boolean)) s = s.replaceAll(secret, '[redacted]');
    return s.replace(/https?:\/\/[^\s"<>]+/gi, '[url]')
      .replace(/(?:authorization\s*[:=]\s*)?Bearer\s+[^\s"<>]+/gi, '[authorization]')
      .replace(/sk-[A-Za-z0-9_-]+/g, '[redacted]');
  };
  const clean = (v: any): any => typeof v === 'string' ? redact(v) : Array.isArray(v) ? v.map(clean) :
    v && typeof v === 'object' ? Object.fromEntries(Object.entries(v).map(([k, x]) => [redact(k), clean(x)])) : v;
  return clean;
}

export function createBoundary(spec: Json, support: {
  createAdapter: typeof adapterFactory; callTool: typeof toolFactory; declarations: Tool[];
}, credentialEnv: NodeJS.ProcessEnv, transport?: typeof fetch) {
  const clean = sanitizer(Object.values(credentialEnv).filter((s): s is string => !!s));
  const started = performance.now();
  const controller = new AbortController();
  let terminal: string | undefined;
  let active = false, finished = false, intervened = false, accountingUnknown = false;
  let attempts = 0, tools = 0, observed = 0, logical = 0;
  let eventCount = 0;
  let current: { request: string; previous: string | null; admitted: boolean; reservation?: number };
  const events: Json[] = [], messages: Message[] = [];
  const append = (name: string, value: any) => appendFileSync(join(spec.output, name), JSON.stringify(clean(value)) + '\n');
  const write = (name: string, value: any) => writeFileSync(join(spec.output, name), JSON.stringify(clean(value), null, 2) + '\n');
  const elapsed = () => Math.round(performance.now() - started);
  function stop(reason: string): never { terminal ??= reason; throw new Stop(terminal); }
  function check() {
    if (terminal) throw new Stop(terminal);
    if (finished) throw new Stop('run_finished');
    if (controller.signal.aborted) stop('cancelled');
  }
  function event(value: Json) {
    const e = { ...value, schema_version: '1.0', run_id: spec.run_id,
      event_id: `event-${eventCount}`, sequence: eventCount++, elapsed_ms: elapsed() };
    events.push(e); append('trace.jsonl', e);
  }
  const adapter = support.createAdapter({ ...spec.settings.connection, retries: 0 }, {
    env: credentialEnv, runId: spec.run_id,
    fetch: async (target, init) => {
      check();
      if (attempts >= spec.settings.budgets.model_attempts) stop('model_budget');
      // Text-only Responses framing: UTF-8 bytes bound text tokens; reserve extra
      // protocol tokens per record/tool plus a fixed envelope allowance. Inspect
      // the COMPLETE provider envelope, not a harness estimate or a prompt alone.
      if (typeof init?.body !== 'string') stop('reservation_unknown');
      const body = JSON.parse(init!.body as string);
      if (body.model !== 'gpt-5.4-mini-2026-03-17' ||
          body.max_output_tokens !== spec.settings.connection.settings.max_output_tokens ||
          !Array.isArray(body.input) || JSON.stringify(body).includes('input_image')) stop('reservation_unknown');
      const inputBound = Buffer.byteLength(init!.body as string, 'utf8') + 4096 +
        body.input.length * 128 + (body.tools?.length ?? 0) * 512;
      const reservation = inputBound + body.max_output_tokens;
      const admitted = observed + reservation <= spec.settings.budgets.total_tokens;
      append('reservations.jsonl', { request_id: current.request, retry_of: current.previous,
        input_upper_bound: inputBound, output_reserved: body.max_output_tokens,
        reserved_tokens: reservation, observed_tokens_before: observed, admitted });
      if (!admitted) stop('token_budget');
      check();
      current.admitted = true; current.reservation = reservation;
      attempts++;
      append('dispatches.jsonl', { type: 'model', attempt_id: `attempt-${attempts}`,
        request_id: current.request, retry_of: current.previous, elapsed_ms: elapsed() });
      append('requests.jsonl', { attempt_id: `attempt-${attempts}`, body });
      return (transport ?? globalThis.fetch)(target, init);
    },
  });
  // Credentials/routing stay in the fixed adapter/redactor closures. Tools and
  // the harness are loaded only after the caller clears the process environment.
  const systemPrompt = JSON.stringify({ prompts: spec.prompts, output_contract: spec.output_contract });
  messages.push({ role: 'user', content: JSON.stringify(spec.task), timestamp: Date.now() });
  let last: { message: AssistantMessage; request: string; attempt: string } | undefined;
  const dispatchedToolIds = new Set<string>();
  const timer = setTimeout(() => {
    terminal ??= 'run_timeout';
    write('cancellation.json', { detail: terminal });
    controller.abort();
  }, spec.settings.run_timeout_ms);

  async function model(): Promise<AssistantMessage> {
    check();
    if (active) stop('concurrent_dispatch');
    active = true;
    const request = `request-${++logical}`;
    let previous: string | null = null;
    try {
      for (let retry = 0; retry <= spec.settings.connection.retries; retry++) {
        check();
        if (attempts >= spec.settings.budgets.model_attempts) stop('model_budget');
        current = { request, previous, admitted: false };
        const before = adapter.events.length;
        const stream = await adapter.streamFn(adapter.model, normalizeContext({ systemPrompt, messages,
          tools: support.declarations }), { signal: controller.signal });
        for await (const _ of stream) { /* Drain partial output; saved below. */ }
        const result = await stream.result();
        if (!current.admitted) stop(terminal ?? (controller.signal.aborted ? 'cancelled' : 'service_error'));
        const raw = adapter.events[before];
        if (!raw) stop('accounting_unknown');
        const record: Attempt = { ...raw, request_id: request, attempt_id: `attempt-${attempts}`, retry_of: previous };
        const retryable = record.status === 'error' && record.error?.code === 'service_error' && result.content.length === 0;
        if (record.error) record.error.retryable = retryable;
        event(record);
        append('effective-settings.jsonl', { ...adapter.effectiveSettings.at(-1), attempt_id: record.attempt_id });
        append('responses.jsonl', { attempt_id: record.attempt_id, message: result });
        const usage = record.usage;
        observed += (usage.input_tokens ?? 0) + (usage.output_tokens ?? 0);
        if (usage.input_tokens === null || usage.output_tokens === null) {
          accountingUnknown = true;
          stop('accounting_unknown');
        }
        // Cached input and reasoning are already subsets, never added again.
        if (observed > spec.settings.budgets.total_tokens) stop('token_budget');
        if (usage.input_tokens + usage.output_tokens > current.reservation!) stop('reservation_exceeded');
        check();
        if (record.status === 'ok') {
          messages.push(result); last = { message: result, request, attempt: record.attempt_id };
          write('messages.json', messages);
          return structuredClone(result);
        }
        if (record.error?.code === 'timeout' || record.status === 'cancelled') stop(record.error?.code ?? 'cancelled');
        if (retryable && retry < spec.settings.connection.retries) { previous = record.attempt_id; continue; }
        stop('service_error');
      }
      return stop('service_error');
    } finally { active = false; }
  }

  async function executeTools() {
    check();
    if (active) stop('concurrent_dispatch');
    if (!last) stop('invalid_tool_request');
    active = true;
    try {
      const results = [];
      for (const call of last.message.content) {
        if (call.type !== 'toolCall' || dispatchedToolIds.has(`${last.attempt}:${call.id}`)) continue;
        check();
        if (tools >= spec.settings.budgets.tool_invocations) stop('tool_budget');
        if (!support.declarations.some(t => t.name === call.name)) stop('unregistered_tool');
        const toolId = `tool-${tools + 1}`; // Provider IDs may contain Pi's `|` separator.
        const name = call.name as ToolName;
        let args: Json;
        try { args = validateToolCall(support.declarations, call); }
        catch { stop('invalid_tool_request'); }
        // Let the bridge compute successful read defaults from actual source
        // length. Error-only trace envelopes need explicit bounded defaults to
        // fit v1; the raw arguments remain in the dispatch/tool-result journals.
        const traceArgs = { ...args };
        if (name === 'read') { traceArgs.start ??= 0; traceArgs.end ??= traceArgs.start + 4096; }
        if (name === 'search') traceArgs.limit ??= 5;
        const input = { schema_version: '1.0', run_id: spec.run_id, tool_call_id: toolId, tool: name, arguments: traceArgs };
        const at = performance.now();
        tools++; dispatchedToolIds.add(`${last.attempt}:${call.id}`);
        const linkage = { request_id: last.request, attempt_id: last.attempt, retry_of: null, tool_call_id: toolId };
        append('dispatches.jsonl', { type: 'tool', ...linkage, input, arguments: args, elapsed_ms: elapsed() });
        let response;
        try {
          response = await support.callTool({ caseRoot: spec.case_root, python: spec.python,
            runId: spec.run_id, timeoutMs: spec.settings.tool_timeout_ms }, name, args, toolId, controller.signal);
        } catch {
          response = { invocation: input, result: { schema_version: '1.0', run_id: spec.run_id,
            tool_call_id: toolId, tool: name, status: 'error', data: null,
            error: { code: controller.signal.aborted ? 'cancelled' : 'service_error', retryable: false } } };
        }
        event({ type: 'tool_invocation', ...linkage, duration_ms: Math.round(performance.now() - at),
          input: response.result.status === 'ok' ? response.invocation : input, result: response.result });
        append('tool-results.jsonl', response);
        messages.push({ role: 'toolResult', toolCallId: call.id, toolName: name,
          content: [{ type: 'text', text: JSON.stringify(response.result) }],
          isError: response.result.status === 'error', timestamp: Date.now() });
        results.push(response.result);
        write('messages.json', messages);
        check();
      }
      return structuredClone(results);
    } finally { active = false; }
  }
  function saveOutput(output: Json) { check(); write('candidate-output.json', output); }
  return {
    api: Object.freeze({ task: Object.freeze(structuredClone(spec.task)), model, tools: executeTools,
      addMessage(text: string) { check(); messages.push({ role: 'user', content: String(text), timestamp: Date.now() }); },
      saveOutput,
      cancel() { terminal ??= 'cancelled'; controller.abort(); },
      intervention(action: 'edit' | 'steer' | 'resume') { check(); intervened = true; event({ type: 'intervention', actor: 'human', action }); },
    }),
    finish(reason = 'no_progress') {
      if (finished) return;
      finished = true; clearTimeout(timer); controller.abort();
      terminal ??= reason;
      const mapped = ['completed', 'no_progress', 'model_budget', 'tool_budget', 'token_budget', 'invalid_output'].includes(terminal)
        ? terminal : 'service_error';
      event({ type: 'run_end', stop_reason: mapped, intervention: intervened });
      write('runtime-status.json', { status: mapped === 'completed' ? 'completed' : 'stopped',
        stop_reason: mapped, detail: terminal, model_attempts: attempts, tool_invocations: tools,
        known_observed_tokens: observed, accounting_status: accountingUnknown ? 'unknown' : 'known',
        elapsed_ms: elapsed(), intervention: intervened });
    },
  };
}
