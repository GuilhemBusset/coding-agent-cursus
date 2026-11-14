/** Trusted process configuration stays outside the three model-facing schemas. */
import { spawn } from 'node:child_process';
import { resolve as resolvePath } from 'node:path';
import { fileURLToPath } from 'node:url';
import type { AgentTool } from '@earendil-works/pi-agent-core';

export const limits = { requestBytes: 16384, responseBytes: 131072, read: 4096, query: 256, hits: 8, snippet: 600, pairs: 100 } as const;
const id = { type: 'string', pattern: '^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$' } as const;
export const schemas = {
  read: { type: 'object', properties: { source_id: id, start: { type: 'integer', minimum: 0 }, end: { type: 'integer', minimum: 1 } }, required: ['source_id'], additionalProperties: false },
  search: { type: 'object', properties: { query: { type: 'string', minLength: 1, maxLength: limits.query }, limit: { type: 'integer', minimum: 1, maximum: limits.hits } }, required: ['query'], additionalProperties: false },
  check_table: { type: 'object', properties: {
    source_id: id, method_left: id, method_right: id,
    metric: { const: 'cost' }, unit: { type: 'string', minLength: 1 }, feasible_only: { const: true }, pair_key: { const: 'pair_id' },
    pair_ids: { type: 'array', items: id, minItems: 1, maxItems: limits.pairs, uniqueItems: true },
  }, required: ['source_id', 'method_left', 'method_right', 'metric', 'unit', 'feasible_only', 'pair_key', 'pair_ids'], additionalProperties: false },
} as const;
export type ToolName = keyof typeof schemas;
export const descriptions: Record<ToolName, string> = {
  read: 'Read a local evidence source by ID. Optional start/end are half-open Unicode code-point offsets, at most 4096 characters; omit both for the first bounded span. Returns exact text, citations and truncation.',
  search: 'Search local manifest passages lexically. At most 256 query characters; limit 1–8 (default 5). Returns deterministic snippets of at most 600 code points, source spans, parent passage IDs and truncation. No network.',
  check_table: 'Compute only feasible paired cost reduction: a supplied baseline method versus a supplied candidate method, same instance/run, exactly one feasible row each. Supply known pair_ids, cost, its manifest unit, feasible_only=true and pair_key=pair_id. Returns inputs, row/execution IDs, totals, means and (sum_left-sum_right)/sum_left. No supplied code is evaluated.',
};
type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
export interface BridgeResponse {
  bridge_version: '1.0';
  invocation: { schema_version: '1.0'; run_id: string; tool_call_id: string; tool: ToolName; arguments: Record<string, Json> };
  result: { schema_version: '1.0'; run_id: string; tool_call_id: string; tool: ToolName; status: 'ok' | 'error'; data: Json; error: { code: string; retryable: boolean } | null };
  audit: Record<string, Json>;
}
export class BridgeError extends Error {
  code: string;
  constructor(code: string) { super(code); this.code = code; }
}
export interface BridgeConfig {
  caseRoot: string;
  python?: string; // executable path only, never a shell command
  runId?: string;
  timeoutMs?: number;
}

export function callTool(config: BridgeConfig, tool: ToolName, args: unknown, toolCallId: string, signal?: AbortSignal): Promise<BridgeResponse> {
  const runId = config.runId ?? 'offline';
  const input = JSON.stringify({ tool, arguments: args, run_id: runId, tool_call_id: toolCallId });
  if (Buffer.byteLength(input, 'utf8') > limits.requestBytes) return Promise.reject(new BridgeError('invalid_input'));
  if (signal?.aborted) return Promise.reject(new BridgeError('cancelled'));
  return new Promise((resolve, reject) => {
    const child = spawn(config.python ?? 'python', ['-m', 'exercises.fixed.bridge.dispatch', resolvePath(config.caseRoot)], {
      cwd: fileURLToPath(new URL('../../../', import.meta.url)),
      shell: false, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'],
    });
    const chunks: Buffer[] = [];
    let size = 0;
    let settled = false;
    const finish = (error?: BridgeError, response?: BridgeResponse) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      signal?.removeEventListener('abort', abort);
      if (error) { child.kill(); reject(error); } else resolve(response!);
    };
    const abort = () => finish(new BridgeError('cancelled'));
    const timer = setTimeout(() => finish(new BridgeError('timeout')), config.timeoutMs ?? 10000);
    signal?.addEventListener('abort', abort, { once: true });
    if (signal?.aborted) abort();
    child.on('error', () => finish(new BridgeError('service_error')));
    child.stdin.on('error', () => finish(new BridgeError('service_error')));
    child.stderr.resume(); // Drain diagnostics; do not expose process paths to the research model.
    child.stdout.on('data', (chunk: Buffer) => {
      size += chunk.length;
      if (size > limits.responseBytes + 1) finish(new BridgeError('service_error'));
      else chunks.push(chunk);
    });
    child.on('close', code => {
      if (settled) return;
      try {
        if (code !== 0) throw new BridgeError('service_error');
        const response = JSON.parse(Buffer.concat(chunks).toString('utf8'));
        if (response.bridge_error) throw new BridgeError(response.bridge_error.code);
        if (response.bridge_version !== '1.0' || !response.audit || !response.result || !response.invocation) throw new BridgeError('service_error');
        for (const part of [response.result, response.invocation]) {
          if (part.schema_version !== '1.0' || part.run_id !== runId || part.tool_call_id !== toolCallId || part.tool !== tool) throw new BridgeError('service_error');
        }
        if (!['ok', 'error'].includes(response.result.status)) throw new BridgeError('service_error');
        if (response.result.status === 'ok' && tool === 'check_table') {
          const d = response.result.data, a = response.audit;
          if (a.denominator !== a.baseline_total || a.unit !== d.unit || a.pairs.length !== d.pairs.length ||
              Math.abs(d.relative_reduction - (a.baseline_total - a.candidate_total) / a.denominator) > 1e-12 ||
              Math.abs(a.reduction_percent - 100 * d.relative_reduction) > 1e-10) throw new BridgeError('service_error');
        }
        finish(undefined, response);
      } catch (error) { finish(error instanceof BridgeError ? error : new BridgeError('service_error')); }
    });
    child.stdin.end(input, 'utf8');
  });
}

function registration<S extends object>(name: ToolName, parameters: S, config: BridgeConfig): AgentTool<S, BridgeResponse | { error: { code: string; retryable: boolean } }> {
  return { name, label: name, description: descriptions[name], parameters, replay: 'safe',
    execute: async (callId, args, signal) => {
      try {
        const details = await callTool(config, name, args, callId, signal);
        return { content: [{ type: 'text', text: JSON.stringify(details) }], details, isError: details.result.status === 'error' };
      } catch (error) {
        const details = { error: { code: error instanceof BridgeError ? error.code : 'service_error', retryable: false } };
        return { content: [{ type: 'text', text: JSON.stringify(details) }], details, isError: true };
      }
    },
  };
}
export function createResearchTools(config: BridgeConfig) {
  return [registration('read', schemas.read, config), registration('search', schemas.search, config), registration('check_table', schemas.check_table, config)] as const;
}
