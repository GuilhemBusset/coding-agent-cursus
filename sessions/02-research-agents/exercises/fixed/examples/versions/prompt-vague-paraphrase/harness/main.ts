import { Agent, type AgentTool, type StreamFn } from '@earendil-works/pi-agent-core';
import type { Model } from '@earendil-works/pi-ai';
import { createMemory } from './memory.ts';
import { createPolicy, dispatchStop, partialOutput, validateOutput } from './policy.ts';

interface Runtime {
  piModel: Model<any>;
  streamFn: StreamFn;
  systemPrompt: string;
  task: { question: string; context: string };
  researchTool(name: 'read' | 'search' | 'check_table'): AgentTool;
}

export async function run(api: Runtime) {
  const memory = createMemory();
  const policy = createPolicy();
  let dispatchFailure: ReturnType<typeof dispatchStop> | undefined;
  const registered = [api.researchTool('read'), api.researchTool('search')];
  // A/B expose only read/search; C additionally supplies the fixed calculator.
  try { registered.push(api.researchTool('check_table')); } catch { /* absent from this case registry */ }
  const tools = registered.map(tool => {
    return { ...tool, execute: async (...args: Parameters<typeof tool.execute>) => {
      try { return await tool.execute(...args); }
      catch (error) { dispatchFailure = dispatchStop((error as Error).message); throw error; }
    } };
  });
  const agent = new Agent({
    initialState: { model: api.piModel, systemPrompt: api.systemPrompt, tools },
    streamFn: async (...args) => {
      // A mixed tool batch may keep Pi continuing. Stop before its next call.
      if (policy.reason) throw new Error(policy.reason);
      return api.streamFn(...args);
    },
    toolExecution: 'sequential',
    beforeToolCall: async ({ toolCall, args }) => {
      const reason = policy.before(toolCall.name, args);
      return reason ? { block: true, reason, terminate: true } : undefined;
    },
    afterToolCall: async ({ toolCall, args, result }) => {
      const before = memory.evidenceCount();
      memory.ingest(result.details);
      memory.retainCalculation(args, result.details);
      policy.observe(toolCall.name, args, result.details, memory.evidenceCount() > before);
      return policy.reason ? { terminate: true } : undefined;
    },
    transformContext: async messages => [...memory.context(messages),
      ...(policy.pending ? [{ role: 'user' as const, content: policy.instruction(), timestamp: 0 }] : [])],
  });
  await agent.prompt(JSON.stringify(api.task));
  const answer = agent.state.messages.findLast(message => message.role === 'assistant');
  // Check boundary errors first: their precise stop reason wins over policy.
  if (answer?.role === 'assistant' && (answer.stopReason === 'error' || answer.stopReason === 'aborted')) {
    return partialOutput(dispatchFailure ?? policy.reason ?? dispatchStop(answer.errorMessage ?? ''), memory.snapshot());
  }
  if (dispatchFailure) return partialOutput(dispatchFailure, memory.snapshot());
  if (policy.reason || policy.pending) return partialOutput(policy.reason ?? 'service_error', memory.snapshot());
  if (!answer || answer.role !== 'assistant' || answer.stopReason !== 'stop') return partialOutput('invalid_output', memory.snapshot(), ['complete final answer required']);
  const text = answer.content.filter(part => part.type === 'text').map(part => part.text).join('');
  let output;
  try { output = JSON.parse(text); }
  catch { return partialOutput('invalid_output', memory.snapshot(), ['JSON object required']); }
  const errors = validateOutput(output, JSON.parse(api.systemPrompt).output_contract);
  if (errors.length) return { ...partialOutput('invalid_output', memory.snapshot(), errors), rejected_output: output };
  // Structural completion is not a grade. The independent public grader judges
  // facts, row citations and uncertainty after artifacts have been saved.
  return { ...output, stop_reason: 'completed', retained_evidence: memory.snapshot() };
}
