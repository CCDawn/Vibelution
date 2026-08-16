import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const composerSource = readFileSync(join(here, "useChatComposerSubmit.ts"), "utf8");

describe("chat composer user-action telemetry contract", () => {
  it("tracks composer turn mutations through startUserAction", () => {
    expect(composerSource).toContain('startUserAction("session_message_submit"');
    expect(composerSource).toContain('startUserAction("session_edit_resubmit"');
    expect(composerSource).toContain('startUserAction("session_turn_stop"');
    expect(composerSource).toContain('startUserAction("session_guidance_submit"');
    expect(composerSource).toContain("telemetry?.succeeded({");
    expect(composerSource).toContain("telemetry?.failed(error");
  });

  it("records composer guard blocks as user_action blocked events", () => {
    expect(composerSource).toContain('.blocked("image_input_unsupported"');
    expect(composerSource).toContain(".blocked(guardReason");
  });
});
