import type { AssistantMessage, Model } from "@earendil-works/pi-ai";
import { AssistantMessageEventStream } from "@earendil-works/pi-ai/utils/event-stream";
import { stream } from "@earendil-works/pi-ai/api/openai-responses";
import type { StreamFn } from "@earendil-works/pi-agent-core";
import { defaults, parseConfig } from "../config/model.ts";

export interface Usage {
  status: "complete" | "partial" | "unknown";
  input_tokens: number | null; output_tokens: number | null;
  cache_read_tokens: number | null; cache_write_tokens: number | null; reasoning_tokens: number | null;
}
export interface Attempt {
  schema_version: "1.0"; type: "model_attempt"; run_id: string; event_id: string;
  sequence: number; elapsed_ms: number; request_id: string; attempt_id: string;
  retry_of: string | null; status: "ok" | "error" | "cancelled"; duration_ms: number;
  usage: Usage; error: { code: "timeout" | "cancelled" | "service_error"; retryable: boolean } | null;
}
export function normalizeUsage(raw?: Record<string, any>): Usage {
  const token = (v: unknown) => Number.isSafeInteger(v) && Number(v) >= 0 ? Number(v) : null;
  const fields = {
    input_tokens: token(raw?.input_tokens), output_tokens: token(raw?.output_tokens),
    cache_read_tokens: token(raw?.input_tokens_details?.cached_tokens),
    // Preserve compatible endpoints' explicit cache-write subset. Standard OpenAI
    // usage has no separate write category; absence means zero only when usage exists.
    cache_write_tokens: raw?.input_tokens_details && "cache_write_tokens" in raw.input_tokens_details
      ? token(raw.input_tokens_details.cache_write_tokens) : raw ? 0 : null,
    reasoning_tokens: token(raw?.output_tokens_details?.reasoning_tokens),
  };
  const values = Object.values(fields);
  return { status: values.every(v => v !== null) ? "complete" : values.every(v => v === null) ? "unknown" : "partial", ...fields };
}

/** Only known cost, never interpret missing usage as free. Prices checked 2026-11-14. */
export function costUSD(usage: Usage): number | null {
  const { input_tokens: i, output_tokens: o, cache_read_tokens: c } = usage;
  return i === null || o === null || c === null ? null : ((i - c) * .75 + c * .075 + o * 4.5) / 1e6;
}

export function createAdapter(input: unknown = defaults, runtime: {
  env?: NodeJS.ProcessEnv; fetch?: typeof fetch; runId?: string;
} = {}) {
  const config = parseConfig(input);
  Object.freeze(config.settings);
  Object.freeze(config);
  const env = runtime.env ?? process.env;
  const runId = runtime.runId ?? "adapter";
  if (!/^[A-Za-z0-9][A-Za-z0-9_.-]*$/.test(runId)) throw new Error("runId must be an identifier");
  const key = env[config.provider === "openai" ? "OPENAI_API_KEY" : "COURSE_API_KEY"];
  if (!key?.trim()) throw new Error("API credential missing: set the provider API key environment variable");
  // Reject subscription tokens rather than invoking Pi's sign-in path.
  if (config.provider === "openai" && !key.startsWith("sk-")) throw new Error("OPENAI_API_KEY must be an API key, not a subscription token");
  const endpoint = env[`COURSE_ENDPOINT_${config.endpoint_alias.toUpperCase().replaceAll("-", "_")}`]
    ?? (config.provider === "openai" && config.endpoint_alias === "openai" ? "https://api.openai.com/v1" : undefined);
  let url: URL;
  try { url = new URL(endpoint ?? ""); } catch { throw new Error("endpoint alias has no valid environment URL"); }
  if (url.username || url.password || url.search || url.hash ||
      !(url.protocol === "https:" || (url.protocol === "http:" && ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname))))
    throw new Error("endpoint requires HTTPS (or loopback HTTP), without credentials, query or fragment");
  const transport = runtime.fetch ?? globalThis.fetch;
  const privateModel: Model<"openai-responses"> = {
    id: config.model, name: config.model, api: "openai-responses", provider: config.provider,
    baseUrl: url.href.replace(/\/$/, ""), reasoning: true, input: ["text"],
    contextWindow: 400000, maxTokens: 8192,
    cost: { input: .75, output: 4.5, cacheRead: .075, cacheWrite: 0 },
  };
  // Safe to hand to Agent or save: actual routing URL remains inside this closure.
  const model = Object.freeze({ ...privateModel, baseUrl: config.endpoint_alias });
  const events: Attempt[] = [];
  const effectiveSettings: Array<{ run_id: string; attempt_id: string; provider: string; endpoint_alias: string; model: string;
    route: string; settings: typeof config.settings; stream: true; store: false; http_status: number | null }> = [];
  const started = performance.now();
  let requests = 0;
  let dispatches = 0;
  const redact = (text: string) => text.replaceAll(key, "[redacted]")
    .replaceAll(url.href, "[endpoint]")
    .replace(/https?:\/\/[^\s"<>]+/gi, "[url]")
    .replace(/(?:authorization\s*[:=]\s*)?(?:Bearer\s+)[^\s"<>]+/gi, "[authorization]")
    .replace(/sk-[A-Za-z0-9_-]+/g, "[redacted]");
  function clean<T>(value: T): T {
    // Sanitize values, including object keys, before events cross the boundary.
    const walk = (v: any): any => typeof v === "string" ? redact(v) : Array.isArray(v) ? v.map(walk) :
      v && typeof v === "object" ? Object.fromEntries(Object.entries(v).map(([k, x]) => [redact(k), walk(x)])) : v;
    return walk(value) as T;
  }
  const streamFn: StreamFn = (_model, context, options) => {
    const outgoing = new AssistantMessageEventStream();
    const requestId = `request-${++requests}`;
    void (async () => {
      let previous: string | null = null;
      for (let retry = 0; retry <= config.retries; retry++) {
        const controller = new AbortController();
        let timedOut = false;
        const cancel = () => controller.abort();
        options?.signal?.addEventListener("abort", cancel, { once: true });
        if (options?.signal?.aborted) cancel();
        const timer = setTimeout(() => { timedOut = true; controller.abort(); }, config.timeout_ms);
        const signal = controller.signal;
        let abortListener: () => void = () => {};
        const aborted = new Promise<never>((_, reject) => {
          abortListener = () => reject(new Error("cancelled"));
          signal.addEventListener("abort", abortListener, { once: true });
          if (signal.aborted) abortListener();
        });
        // Race dispatch AND stream consumption; even a non-cooperating transport is bounded.
        void aborted.catch(() => {});
        let attemptId: string | undefined;
        let at = performance.now();
        let httpStatus: number | undefined;
        let rawUsage: Record<string, any> | undefined;
        let partial = false;
        let result: AssistantMessage = {
          role: "assistant", content: [], api: model.api, provider: model.provider, model: model.id,
          usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
            cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
          stopReason: "error", timestamp: Date.now(), errorMessage: "service_error",
        };
        try {
          if (signal.aborted) throw new Error("cancelled");
          const inner = stream(privateModel, context, {
            apiKey: key, env: {}, signal, maxRetries: 0, timeoutMs: config.timeout_ms,
            cacheRetention: "none", maxTokens: config.settings.max_output_tokens,
            // Pi's no-effort branch explicitly sends reasoning.effort=none.
            fetch: async (target, init) => {
              if (signal.aborted) throw new Error("cancelled");
              attemptId = `attempt-${++dispatches}`;
              at = performance.now();
              effectiveSettings.push({ run_id: runId, attempt_id: attemptId, provider: config.provider,
                endpoint_alias: config.endpoint_alias, model: config.model, route: "POST /v1/responses",
                settings: structuredClone(config.settings), stream: true, store: false, http_status: null });
              const response = await Promise.race([transport(target, { ...init, signal, redirect: "manual" }), aborted]);
              httpStatus = response.status;
              effectiveSettings.find(s => s.attempt_id === attemptId)!.http_status = response.status;
              return response;
            },
            onProviderStreamEvent: (event) => {
              const response = (event as { response?: { usage?: Record<string, any> } }).response;
              if (response?.usage) rawUsage = response.usage;
            },
          });
          const iterator = inner[Symbol.asyncIterator]();
          while (true) {
            const next = await Promise.race([iterator.next(), aborted]);
            if (next.done) break;
            const event = next.value;
            result = clean("partial" in event ? event.partial : "message" in event ? event.message : event.error);
            if (event.type === "error" || event.type === "done") continue;
            if (event.type !== "start") partial = true;
            outgoing.push(clean(event));
          }
        } catch { result.stopReason = signal.aborted ? "aborted" : "error"; }
        finally {
          clearTimeout(timer);
          options?.signal?.removeEventListener("abort", cancel);
          signal.removeEventListener("abort", abortListener);
        }
        const ok = !signal.aborted && !["error", "aborted", "pending"].includes(result.stopReason);
        const code = timedOut ? "timeout" : signal.aborted ? "cancelled" : "service_error";
        const retryable = !ok && !signal.aborted && !partial &&
          (httpStatus === undefined || httpStatus === 429 || httpStatus >= 500);
        if (attemptId) {
          const elapsed = Math.round(performance.now() - started);
          events.push({ schema_version: "1.0", type: "model_attempt", run_id: runId,
            event_id: `event-${events.length}`, sequence: events.length, elapsed_ms: elapsed,
            request_id: requestId, attempt_id: attemptId, retry_of: previous,
            status: ok ? "ok" : signal.aborted ? "cancelled" : "error",
            duration_ms: Math.round(performance.now() - at), usage: normalizeUsage(rawUsage),
            error: ok ? null : { code, retryable } });
          previous = attemptId;
        }
        if (retryable && retry < config.retries) continue;
        if (ok) outgoing.push({ type: "done", reason: result.stopReason as "stop" | "length" | "toolUse", message: result });
        else {
          result.stopReason = signal.aborted ? "aborted" : "error";
          result.errorMessage = code; // Never expose Pi/SDK/provider exception strings or bodies.
          outgoing.push({ type: "error", reason: result.stopReason, error: result });
        }
        outgoing.end();
        return;
      }
    })();
    return outgoing;
  };
  return { config, model, streamFn, events, effectiveSettings };
}
