"""Install Session 2 from its local locks, then check offline readiness (all student OSes).

uv run --no-project --python 3.12 python setup/session-02-research-agents.py
Requires mise and uv from the existing student installer. No logins or API key required.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from student.prepare import RETRY_DELAYS_S, run_quiet, sync

# JavaScript runs with the session-local locked Node/Pi packages. Keeping the
# diagnostic here lets the student adapter remain independent of repository tooling.
ADAPTER_SMOKE = r'''
/** Opt-in diagnostic entry point; invoked by the repository setup helper. */
import { createServer } from "node:http";
import { Agent } from "@earendil-works/pi-agent-core";
import { normalizeContext } from "@earendil-works/pi-ai/utils/transcript";
import { defaults, parseConfig } from "./exercises/fixed/config/model.ts";
import { costUSD, createAdapter } from "./exercises/fixed/model/adapter.ts";
// A tiny compatible Responses endpoint, never a live-compatibility claim.
export function fixture(tool, usage = {
    input_tokens: 100, output_tokens: 20, total_tokens: 120,
    input_tokens_details: { cached_tokens: 10 }, output_tokens_details: { reasoning_tokens: 2 },
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
export async function smoke(live) {
    const bodies = [];
    const server = live ? undefined : createServer(async (req, res) => {
        let body = "";
        for await (const chunk of req)
            body += chunk;
        bodies.push(JSON.parse(body));
        if (bodies.length > 2)
            return; // deliberate stall tests stream/dispatch deadline
        res.writeHead(200, { "content-type": "text/event-stream" });
        res.end(fixture(bodies.length === 1));
    });
    if (server)
        await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
    try {
        const address = server?.address();
        // The live compatibility diagnostic always probes the official OpenAI API.
        // Other endpoints use createAdapter's configurable boundary, tested offline here.
        const env = live ? { OPENAI_API_KEY: process.env.OPENAI_API_KEY,
            COURSE_ENDPOINT_OPENAI: "https://api.openai.com/v1" } : {
            COURSE_API_KEY: "offline-placeholder",
            COURSE_ENDPOINT_FAKE: `http://127.0.0.1:${typeof address === "object" && address ? address.port : 0}/v1`,
        };
        const config = { ...defaults, ...(live ? {} : { provider: "openai-compatible", endpoint_alias: "fake" }),
            retries: 0, settings: { ...defaults.settings, max_output_tokens: 256 } };
        const adapter = createAdapter(config, { env, runId: "smoke" });
        let toolResults = 0;
        let turns = 0;
        const agent = new Agent({ streamFn: adapter.streamFn,
            initialState: { model: adapter.model, systemPrompt: "Call echo once with value meter, then repeat its result without calling tools again.",
                tools: [{ name: "echo", label: "Echo", description: "Return a diagnostic value",
                        parameters: { type: "object", properties: { value: { type: "string" } }, required: ["value"], additionalProperties: false },
                        execute: async () => { toolResults++; return { content: [{ type: "text", text: "meter" }], details: {} }; } }] },
            finishTurn: () => ++turns >= 2 ? { action: "end" } : undefined,
        });
        await agent.prompt("Run the tool diagnostic.");
        const timeout = createAdapter({ ...config, timeout_ms: live ? 5 : 30 }, { env, runId: "timeout" });
        // StreamFn can return a stream or a promise. Consume result, including a typed timeout error.
        const timeoutStream = await timeout.streamFn(timeout.model, normalizeContext({ messages: [{ role: "user", content: "Reply briefly.", timestamp: Date.now() }] }));
        await timeoutStream.result();
        const costs = [...adapter.events, ...timeout.events].map(e => costUSD(e.usage));
        const success = toolResults === 1 && adapter.events.length === 2 && adapter.events.every(e => e.status === "ok") &&
            timeout.events.some(e => e.error?.code === "timeout");
        const invalid = [
            { ...config, provider: "unsupported" },
            { ...config, settings: { ...config.settings, temperature: .5 } },
        ].map(c => {
            try {
                parseConfig(c);
                return "unexpected pass";
            }
            catch (error) {
                return error.message;
            }
        });
        return { success, date: new Date().toISOString(), evidence_kind: live ? "captured_live" : "synthetic",
            versions: { pi_ai: "1.5.2", pi_agent_core: "1.5.2", node: process.version },
            config: adapter.config, model: adapter.model.id,
            auth: adapter.effectiveSettings[0]?.http_status === 200 ? "accepted" : "not verified (inspect sanitized HTTP status)",
            tool_results: toolResults, continuation: adapter.events.length === 2 && adapter.events[1].status === "ok",
            timeout: timeout.events.some(e => e.error?.code === "timeout"),
            trace: [...adapter.events, ...timeout.events],
            effective_settings: [...adapter.effectiveSettings, ...timeout.effectiveSettings],
            // A timeout with unknown usage prevents a complete cost; known subtotal stays explicitly labelled.
            cost_usd: costs.every(c => c !== null) ? costs.reduce((a, c) => a + c, 0) : null,
            known_cost_subtotal_usd: costs.reduce((a, c) => a + (c ?? 0), 0),
            pricing_date: "2026-11-14", invalid_configuration_diagnoses: invalid,
            offline_continuation_received: server ? bodies[1]?.input.some((x) => x.type === "function_call_output" && x.output === "meter") : null,
        };
    }
    finally {
        if (server) {
            server.closeAllConnections();
            await new Promise(resolve => server.close(() => resolve()));
        }
    }
}

try {
  if (process.argv[1] === '--invalid') parseConfig({ ...defaults, provider: 'unsupported' });
  else {
    const report = await smoke(process.argv[1] === '--live');
    console.log(JSON.stringify(report, null, 2));
    if (!report.success) process.exitCode = 1;
  }
} catch {
  console.error(process.argv[1] === '--invalid' ? 'provider must use the OpenAI Responses protocol; requests sent: 0' : 'Adapter diagnostic failed. Check environment credentials/configuration; no raw provider error was saved.');
  process.exitCode = 2;
}
'''

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=Path,
                        default=Path(__file__).resolve().parents[1] / "sessions/02-research-agents")
    parser.add_argument("--adapter-smoke", action="store_true", help="run the supplied adapter diagnostic")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true", help="use a local fake Responses endpoint")
    mode.add_argument("--live", action="store_true", help="opt in to separately billed OpenAI API calls")
    mode.add_argument("--invalid", action="store_true", help="diagnose an unsupported provider (exits 2)")
    args = parser.parse_args()
    session = args.session.resolve()
    if args.adapter_smoke:
        if not (args.offline or args.live or args.invalid):
            parser.error("--adapter-smoke requires --offline or explicit paid --live opt-in")
        # Student setup uses mise's session pin; CI already puts its selected Node
        # on PATH and need not install a second runtime manager for diagnostics.
        node = ["mise", "exec", "--", "node"] if shutil.which("mise") else ["node"]
        code, output = run_quiet([*node, "--input-type=module", "--eval", ADAPTER_SMOKE,
                                  "--", "--invalid" if args.invalid else "--live" if args.live else "--offline"], session)
        print(output, end="")
        return code
    if args.offline or args.live or args.invalid:
        parser.error("--offline/--live require --adapter-smoke")
    if sync(session.parent, session, RETRY_DELAYS_S):
        return 1
    code, output = run_quiet(["mise", "exec", "--", "uv", "run", "--locked", "python",
                              "exercises/check_setup.py"], session)
    print(output, end="")
    return code


if __name__ == "__main__":
    sys.exit(main())
