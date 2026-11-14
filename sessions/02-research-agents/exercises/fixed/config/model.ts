/** Public comparison configuration. Routing and credentials are environment-only. */
export const MODEL = "gpt-5.4-mini-2026-03-17";
export const defaults = {
  provider: "openai", endpoint_alias: "openai", model: MODEL,
  settings: { temperature: null, sampling_seed: null, max_output_tokens: 1024, reasoning: "none" },
  timeout_ms: 30000, retries: 1,
} as const;

export interface ConnectionConfig {
  provider: "openai" | "openai-compatible";
  endpoint_alias: string;
  model: string;
  settings: { temperature: null; sampling_seed: null; max_output_tokens: number; reasoning: "none" };
  timeout_ms: number;
  retries: number;
}

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("configuration must be an object");
  return value as Record<string, unknown>;
}
function keys(value: Record<string, unknown>, expected: string[]) {
  if (Object.keys(value).length !== expected.length || expected.some(k => !(k in value)))
    throw new Error("configuration has missing or unsupported fields");
}
function bounded(value: unknown, min: number, max: number): value is number {
  return Number.isSafeInteger(value) && Number(value) >= min && Number(value) <= max;
}
export function parseConfig(input: unknown): ConnectionConfig {
  const c = object(input);
  keys(c, ["provider", "endpoint_alias", "model", "settings", "timeout_ms", "retries"]);
  if (!["openai", "openai-compatible"].includes(String(c.provider)))
    throw new Error("provider must use the OpenAI Responses protocol");
  if (typeof c.endpoint_alias !== "string" || !/^[a-z][a-z0-9_-]{0,40}$/.test(c.endpoint_alias))
    throw new Error("endpoint_alias must be a short lowercase alias, never a URL");
  if (typeof c.model !== "string" || !/^[A-Za-z0-9][A-Za-z0-9_.-]{0,100}$/.test(c.model))
    throw new Error("model must be a model identifier");
  if (c.provider === "openai" && c.model !== MODEL) throw new Error("OpenAI comparison requires the selected snapshot");
  const s = object(c.settings);
  keys(s, ["temperature", "sampling_seed", "max_output_tokens", "reasoning"]);
  if (s.temperature !== null || s.sampling_seed !== null || s.reasoning !== "none")
    throw new Error("unsupported settings: use null temperature/seed and reasoning none");
  if (!bounded(s.max_output_tokens, 16, 8192)) throw new Error("max_output_tokens must be 16..8192");
  if (!bounded(c.timeout_ms, 1, 120000) || !bounded(c.retries, 0, 2))
    throw new Error("timeout_ms must be 1..120000 and retries 0..2");
  return structuredClone(c) as unknown as ConnectionConfig;
}
