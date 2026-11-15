import type { AgentMessage } from '@earendil-works/pi-agent-core';

// Readable course memory, not an answer key: each claim is the source's own
// passage text. The model still has to interpret it and produce typed claims.
export const memoryLimits = { entries: 64, bytes: 32768 } as const;
export const memoryPrefix = 'Claim–passage memory\n';
interface Entry {
  passage_id: string;
  source_id: string;
  span: { source_id: string; kind: 'passage'; start: number; end: number };
  claim: string;
  date: string | null;
  experiment_ids: string[];
  supersedes: string[];
  corrected_by: string[];
  references: string[];
  header_seen: boolean;
}
const unique = (values: string[]) => [...new Set(values)].sort();
const sourceIds = (text: string) => unique(text.match(/(?:[A-Za-z0-9]+-)*EV-S\d+/g) ?? []);
const bytes = (value: unknown) => new TextEncoder().encode(JSON.stringify(value)).length;

export function createMemory() {
  const ledger = new Map<string, Entry>(); // New instance inside every run().
  const calculations = new Map<string, unknown>();
  let omitted = 0;
  const evidenceCount = () => ledger.size + calculations.size;

  function ingest(value: unknown) {
    // Only successful read results are evidence. Search snippets remain discovery
    // hints in the most recent tool batch until the model chooses a source read.
    const result = value as { status?: string; tool?: string; data?: {
      span: Entry['span']; text: string;
    } } | null;
    if (result?.status !== 'ok' || result.tool !== 'read' || !result.data) return;
    const { span, text } = result.data;
    if (span.kind !== 'passage') return;
    const field = (name: string) => text.match(new RegExp(`^${name}: (.*)$`, 'm'))?.[1] ?? '';
    const headerSeen = span.start === 0 && field('Source') === span.source_id;
    const date = headerSeen ? field('Date') || null : null;
    const experiments = headerSeen ? unique(field('Experiments').match(/\b[\w-]*EV-E-[\w-]+/g) ?? []) : [];
    const supersedes = headerSeen ? sourceIds(field('Supersedes')) : [];
    const correctedBy = headerSeen ? sourceIds(field('Reporting relationship').split('corrected by ')[1] ?? '') : [];
    const headings = [...text.matchAll(/^## ([\w-]+:P\d+)\s*\n\n/gm)];
    // A partial read without a heading keeps an honest span identity. Never
    // invent the parent passage ID, date or experiment for an isolated snippet.
    const chunks = headings.length ? headings.map((heading, i) => ({
      id: heading[1], start: heading.index! + heading[0].length,
      end: headings[i + 1]?.index ?? text.length,
    })) : [{ id: `${span.source_id}:${span.start}-${span.end}`, start: 0, end: text.length }];
    for (const chunk of chunks) {
      const raw = text.slice(chunk.start, chunk.end);
      const claim = raw.trimEnd();
      const start = span.start + [...text.slice(0, chunk.start)].length;
      const end = start + [...claim].length;
      const key = `${chunk.id}:${start}-${end}`;
      if (ledger.has(key)) continue;
      if (ledger.size >= memoryLimits.entries) { omitted++; continue; }
      ledger.set(key, { passage_id: chunk.id,
        source_id: span.source_id, span: { ...span, start, end }, claim, date,
        experiment_ids: experiments, supersedes, corrected_by: correctedBy,
        references: sourceIds(text).filter(id => id !== span.source_id), header_seen: headerSeen });
      // Bound stored memory as well as the serialized context. The raw read
      // remains in the fixed journal if it cannot fit here.
      if (bytes([...ledger.values()]) > memoryLimits.bytes / 2) { ledger.delete(key); omitted++; }
    }
  }

  function snapshot() {
    const entries = [...ledger.values()];
    const read = new Set(entries.filter(e => e.header_seen).map(e => e.source_id));
    const unresolved = unique(entries.flatMap(e => [...e.references, ...(!e.header_seen ? [e.source_id] : [])]).filter(id => !read.has(id)))
      .map(source_id => ({ kind: 'source-read', source_id, question: `Read ${source_id} to resolve the cited evidence/relationship.` }));
    const sources = Object.fromEntries(unique(entries.map(e => e.source_id)).map(source_id => {
      const entry = entries.find(e => e.source_id === source_id && e.header_seen) ?? entries.find(e => e.source_id === source_id)!;
      const replacements = unique(entries.filter(other => other.supersedes.includes(source_id)).map(e => e.source_id));
      const pending = entry.corrected_by.filter(id => !read.has(id));
      return [source_id, { date: entry.date, experiment_ids: entry.experiment_ids,
        ...(entry.supersedes.length ? { supersedes: entry.supersedes } : {}),
        ...(entry.corrected_by.length ? { corrected_by: entry.corrected_by } : {}),
        ...(replacements.length ? { superseded_by: replacements } : {}),
        conflict_status: replacements.length ? 'superseded' : pending.length ? 'awaiting-correction' :
          entry.supersedes.length ? 'correction' : 'uncontradicted',
      }];
    }));
    // The passage ID already contains its source ID; source-level status and
    // metadata are stored once above, rather than repeated for every passage.
    const claims = entries.map(entry => ({ passage_id: entry.passage_id,
      span: [entry.span.start, entry.span.end], claim: entry.claim }));
    const experiments = unique(entries.flatMap(e => e.experiment_ids)).map(experiment_id => ({
      experiment_id, // One support group per experiment, regardless of report count.
      passage_ids: unique(entries.filter(e => e.experiment_ids.includes(experiment_id)).map(e => e.passage_id)),
    }));
    const result = { ledger: claims, sources, experiments, unresolved, calculations: [...calculations.values()],
      synthesis: 'Apply the task constraints to current evidence; qualify anything still unsupported.',
      omitted_entries: omitted, limits: memoryLimits };
    while (bytes(result) > memoryLimits.bytes - 512 && result.ledger.length) {
      result.ledger.pop(); result.omitted_entries++;
      // Do not leave support groups pointing at omitted passages.
      result.experiments = result.experiments.map(group => ({ ...group, passage_ids:
        group.passage_ids.filter(id => result.ledger.some(e => e.passage_id === id)) })).filter(g => g.passage_ids.length);
    }
    while (bytes(result) > memoryLimits.bytes - 512 && result.calculations.length) {
      result.calculations.pop(); result.omitted_entries++;
    }
    if (result.omitted_entries) result.unresolved.push({ kind: 'capacity', source_id: '',
      question: 'Memory capacity exceeded: inspect raw tool-results.jsonl and reread narrower spans before concluding.' });
    return result;
  }

  function context(messages: AgentMessage[]): AgentMessage[] {
    // Read-only batches are represented entirely by memory. Keep a recent
    // search/error batch so discovery and errors remain actionable; keep its
    // complete call/result pairs to respect the provider protocol.
    const lastAssistant = messages.findLastIndex(m => m.role === 'assistant');
    const batch = lastAssistant < 0 ? [] : messages.slice(lastAssistant);
    const keepBatch = batch.some(m => m.role === 'toolResult' && (m.toolName !== 'read' || m.isError));
    return [...messages.filter(m => m.role === 'system'),
      ...messages.filter(m => m.role === 'user').slice(0, 1),
      { role: 'user', content: memoryPrefix + JSON.stringify(snapshot()), timestamp: 0 },
      ...(keepBatch ? batch : [])];
  }
  function retainCalculation(arguments_: unknown, value: any) {
    if (value?.status !== 'ok' || value.tool !== 'check_table') return;
    const data = value.data;
    const key = JSON.stringify([data.source_id, data.method_left, data.method_right, data.pairs]);
    if (calculations.has(key)) return;
    const baseline_total = data.pairs.reduce((sum: number, p: any) => sum + p.left_value, 0);
    const candidate_total = data.pairs.reduce((sum: number, p: any) => sum + p.right_value, 0);
    // Keep the actual tool rows/citations and requested filter; never just the
    // percentage. The fixed journal additionally retains independent audit IDs.
    const entry = { arguments: arguments_, ...data, baseline_total, candidate_total,
      denominator: baseline_total, formula: '(sum_left - sum_right) / sum_left',
      reduction_percent: 100 * data.relative_reduction };
    if (calculations.size >= 8 || bytes([...calculations.values(), entry]) > memoryLimits.bytes / 4) { omitted++; return; }
    calculations.set(key, entry);
  }
  return { ingest, retainCalculation, evidenceCount, snapshot, context };
}
