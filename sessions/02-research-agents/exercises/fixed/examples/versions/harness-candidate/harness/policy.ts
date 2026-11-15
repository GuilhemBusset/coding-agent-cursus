// Student policy: the supplied boundary still owns dispatch admission/accounting.
export type StopReason = 'completed' | 'no_progress' | 'invalid_output' | 'service_error' |
  'model_budget' | 'tool_budget' | 'token_budget';
const stops: string[] = ['model_budget', 'tool_budget', 'token_budget'];
export const dispatchStop = (message: string): StopReason =>
  stops.includes(message) ? message as StopReason : 'service_error';
const canonical = (value: any): string => JSON.stringify(value, Object.keys(value).sort());
const requestKey = (name: string, args: any) => name + ':' + canonical(args);

export function createPolicy() {
  let reason: StopReason | undefined;
  let pending: string | undefined;
  let stagnant = 0;
  const retried = new Set<string>();
  function before(name: string, args: unknown) {
    if (pending && requestKey(name, args) !== pending) reason = 'service_error';
    return reason;
  }
  function observe(name: string, args: unknown, result: any, addedEvidence: boolean) {
    if (reason) return;
    const key = requestKey(name, args);
    if (result?.status !== 'ok') {
      // One retry per identical read request, across the entire run. A retry
      // must be another model-requested call through the metered fixed tool.
      if (name === 'read' && result?.error?.retryable === true && !retried.has(key)) {
        retried.add(key); pending = key;
      } else reason = 'service_error';
      return;
    }
    pending = undefined;
    stagnant = addedEvidence ? 0 : stagnant + 1;
    if (stagnant >= 1) reason = 'no_progress';
  }
  return { before, observe,
    get reason() { return reason; },
    get pending() { return pending; },
    instruction() { return pending ? `Retry this identical read once through the fixed tool: ${pending}. Do not conclude before it succeeds.` : ''; },
  };
}

// Validate against the actual public output schemas supplied in systemPrompt.
// This small interpreter handles their schema vocabulary, not factual grading.
function conforms(value: any, schema: any, common: any): boolean {
  if (schema.$ref) return conforms(value, common.$defs[schema.$ref.split('/').at(-1)], common);
  if (schema.oneOf) return schema.oneOf.filter((s: any) => conforms(value, s, common)).length === 1;
  if ('const' in schema && value !== schema.const) return false;
  if (schema.enum && !schema.enum.includes(value)) return false;
  if (schema.type === 'null') return value === null;
  if (schema.type === 'object') {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
    if (schema.required?.some((k: string) => !(k in value))) return false;
    return Object.keys(value).every(k => schema.properties?.[k] ? conforms(value[k], schema.properties[k], common) : schema.additionalProperties !== false);
  }
  if (schema.type === 'array') return Array.isArray(value) && value.length >= (schema.minItems ?? 0) &&
    (!schema.uniqueItems || new Set(value.map((v: any) => JSON.stringify(v))).size === value.length) &&
    value.every(v => conforms(v, schema.items, common));
  if (schema.type === 'string') return typeof value === 'string' && value.length >= (schema.minLength ?? 0) &&
    (!schema.pattern || new RegExp(schema.pattern).test(value));
  if (schema.type === 'boolean') return typeof value === 'boolean';
  if (schema.type === 'number' || schema.type === 'integer') return typeof value === 'number' && Number.isFinite(value) &&
    (schema.type !== 'integer' || Number.isInteger(value)) && value >= (schema.minimum ?? -Infinity);
  return true;
}

export function validateOutput(value: any, contract: any): string[] {
  const errors: string[] = [];
  const envelope = { schema_version: '1.0', run_id: 'validation', case_id: 'validation', variant_id: 'validation' };
  if (!conforms({ ...envelope, claims: value?.claims }, contract.claims, contract.common)) errors.push('claims schema');
  if (!conforms({ ...envelope, claims_path: 'claims.json', report_path: 'report.md', claim_anchors: value?.claim_anchors }, contract.report, contract.common)) errors.push('report schema');
  if (typeof value?.markdown !== 'string' || !value.markdown.trim()) errors.push('nonempty markdown');
  if (errors.length) return errors;
  const ids = value.claims.map((c: any) => c.claim_id);
  const anchors = value.claim_anchors;
  if (new Set(ids).size !== ids.length || anchors.length !== ids.length ||
      new Set(anchors.map((a: any) => a.anchor)).size !== anchors.length ||
      ids.some((id: string) => anchors.filter((a: any) => a.claim_id === id).length !== 1) ||
      anchors.some((a: any) => !value.markdown.includes(`<a id="${a.anchor}"></a>`))) errors.push('one visible anchor per unique claim');
  for (const claim of value.claims) {
    if (claim.kind === 'factual' && (claim.support_status !== 'supported' || !claim.evidence.length)) errors.push(`${claim.claim_id}: factual support required`);
    if (claim.kind === 'uncertainty' && (claim.support_status !== 'unknown' || claim.evidence.length)) errors.push(`${claim.claim_id}: unknown uncertainty required`);
    if (claim.evidence.some((e: any) => e.end <= e.start)) errors.push(`${claim.claim_id}: empty evidence span`);
  }
  return errors;
}

export function partialOutput(reason: StopReason, memory: unknown, errors: string[] = []) {
  return { stop_reason: reason, validation_errors: errors, retained_evidence: memory,
    claims: [{ claim_id: 'unfinished', kind: 'uncertainty', support_status: 'unknown', evidence: [],
      assertion: { subject: 'run', predicate: 'findings', type: 'string', value: 'incomplete', unit: null },
      reference_fact_ids: [], experiment_ids: [], supersedes_claim_ids: [] }],
    claim_anchors: [{ claim_id: 'unfinished', anchor: 'claim-unfinished' }],
    markdown: `<a id="claim-unfinished"></a>\nResearch incomplete. Stop reason: ${reason}. No completed conclusion.\n` +
      `Failed output requirements: ${errors.join('; ') || 'completion not reached'}.\n\nRetained partial evidence (not a final synthesis):\n\n\`\`\`json\n${JSON.stringify(memory, null, 2)}\n\`\`\`\n` };
}
