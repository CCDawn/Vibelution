import { existsSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

/**
 * Regenerates web/src/design/visualTokenEscalation.baseline.json from the current
 * tree by running the contract test in its update mode. The ratchet only tightens:
 * only run this to acknowledge real cleanups or audited exemptions.
 */

const webRoot = fileURLToPath(new URL("..", import.meta.url));
const vitest = join(webRoot, "node_modules", "vitest", "vitest.mjs");
if (!existsSync(vitest)) {
  throw new Error("vitest executable is missing: " + vitest);
}

const result = spawnSync(
  process.execPath,
  [vitest, "run", "src/design/visualTokenEscalationContract.test.ts"],
  {
    cwd: webRoot,
    env: { ...process.env, VISUAL_TOKEN_ESCALATION_UPDATE: "1" },
    stdio: "inherit",
    windowsHide: true,
  },
);

process.exit(result.status ?? 1);
