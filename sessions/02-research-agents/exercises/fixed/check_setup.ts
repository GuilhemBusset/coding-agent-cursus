/** Import-only probe: no model selection, credentials, provider calls or global Pi setup. */
import { pathToFileURL } from "node:url";
import { Agent } from "@earendil-works/pi-agent-core";
import { PI_AI_VERSION } from "@earendil-works/pi-ai";

export function checkPi(): void {
  if (typeof Agent !== "function" || typeof PI_AI_VERSION !== "string") {
    throw new Error("Pi exports unavailable");
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  checkPi();
  console.log("Pi imports: offline ready (no provider call)");
}
