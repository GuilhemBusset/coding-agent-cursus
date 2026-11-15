import { Agent, type AgentTool, type StreamFn } from '@earendil-works/pi-agent-core';
import type { Model } from '@earendil-works/pi-ai';
import { createMemory } from './memory.ts';

// The supplied launcher injects the metered adapter, prompt and fixed tools.
interface Runtime {
  piModel: Model<any>;
  streamFn: StreamFn;
  systemPrompt: string;
  task: { question: string; context: string };
  researchTool(name: 'read' | 'search'): AgentTool;
}

export async function run(api: Runtime) {
  const tools: AgentTool[] = [api.researchTool('read'), api.researchTool('search')]; // 01: register read; 02: also register search.
  const memory = createMemory(); // 03: inspect memory.ts, then connect these two hooks.
  const agent = new Agent({
    initialState: { model: api.piModel, systemPrompt: api.systemPrompt, tools },
    streamFn: api.streamFn,
    toolExecution: 'sequential',
    afterToolCall: async ({ result }) => { memory.ingest(result.details); return undefined; },
    transformContext: async messages => memory.context(messages),
  });
  await agent.prompt(JSON.stringify(api.task));
  const answer = agent.state.messages.findLast(message => message.role === 'assistant');
  if (!answer || answer.role !== 'assistant' || answer.stopReason === 'error' || answer.stopReason === 'aborted') {
    throw new Error('agent stopped before an answer');
  }
  const text = answer.content.filter(part => part.type === 'text').map(part => part.text).join('');
  return JSON.parse(text); // Fixed output contract is supplied with the prompt.
}
