import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { SessionLlmPayloadTrace } from "../../api/types";
import { LlmPayloadTracePanel } from "./LlmPayloadTracePanel";

describe("LlmPayloadTracePanel", () => {
  it("renders safe payload facts without raw prompt metadata", () => {
    const trace = {
      traceId: "trace-safe-1",
      provider: "relay",
      model: "gpt-5.5",
      selectedProtocol: "relay_responses",
      dialogueChainMode: "responses_agent",
      messageCount: 2,
      toolCount: 1,
      imageBlockCount: 0,
      promptCache: {
        promptCacheMode: "automatic",
        promptCachePartitionHash: "hash-safe",
      },
      thinking: {
        thinkingRequested: true,
        thinkingType: "enabled",
      },
      metadata: {
        promptPreview: "secret raw prompt",
      },
    } as SessionLlmPayloadTrace & { metadata: { promptPreview: string } };

    const html = renderToStaticMarkup(
      React.createElement(LlmPayloadTracePanel, {
        lang: "zh",
        trace,
      }),
    );

    expect(html).toContain('role="status"');
    expect(html).toContain("relay");
    expect(html).toContain("gpt-5.5");
    expect(html).toContain("relay_responses");
    expect(html).toContain("responses_agent");
    expect(html).toContain("automatic");
    expect(html).toContain("enabled");
    expect(html).not.toContain("secret raw prompt");
  });

  it("renders nothing when no trace is available", () => {
    const html = renderToStaticMarkup(
      React.createElement(LlmPayloadTracePanel, {
        lang: "en",
        trace: null,
      }),
    );

    expect(html).toBe("");
  });
});
