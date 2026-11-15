import { existsSync, writeFileSync } from 'node:fs';
let calls = 0;
export async function run(api: { model(): Promise<{ content: { type: string; text?: string }[] }>; tools(): Promise<unknown> }) {
  if (existsSync('prior-state') || calls) throw Error('workspace reused');
  writeFileSync('prior-state', 'fresh'); calls++;
  await api.model();
  await api.tools();
  const answer = await api.model();
  
  return JSON.parse(answer.content.filter(c => c.type === 'text').map(c => c.text).join(''));
}
