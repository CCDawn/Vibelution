// @vitest-environment happy-dom
/**
 * Deterministic regression for the session-switch "Maximum update depth
 * exceeded" contributor in useChatCliAgentTerminal.
 *
 * With no CLI runs present, a no-op parent rerender must preserve the identity
 * of the derived `cliAgentRunTabs` and `mountedCliAgentRuns` arrays. Fresh empty
 * fallback collections (per-render `?? []` literals) invalidated the downstream
 * memo/effect dependencies on every render, which is what let session switches
 * cascade into an update loop.
 */
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import {
  useChatCliAgentTerminal,
  type UseChatCliAgentTerminalOptions,
} from "./useChatCliAgentTerminal";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

type DerivedSnapshot = {
  cliAgentRunTabs: ReturnType<typeof useChatCliAgentTerminal>["cliAgentRunTabs"];
  mountedCliAgentRuns: ReturnType<typeof useChatCliAgentTerminal>["mountedCliAgentRuns"];
};

let hookResults: DerivedSnapshot[] = [];

function Host({ options }: { options: UseChatCliAgentTerminalOptions }) {
  const { cliAgentRunTabs, mountedCliAgentRuns } = useChatCliAgentTerminal(options);
  hookResults.push({ cliAgentRunTabs, mountedCliAgentRuns });
  return null;
}

function baseOptions(overrides: Partial<UseChatCliAgentTerminalOptions> = {}): UseChatCliAgentTerminalOptions {
  return {
    activeSessionId: "s1",
    activeCliAgentRunId: null,
    groupPanelActive: false,
    detailMessages: undefined,
    lang: "en",
    describeError: (_error: unknown, fallback: string) => fallback,
    setActiveTab: () => undefined,
    refetchSessionDetail: () => undefined,
    ...overrides,
  };
}

describe("useChatCliAgentTerminal update-depth regression", () => {
  afterEach(() => {
    hookResults = [];
  });

  it("preserves cliAgentRunTabs and mountedCliAgentRuns references across a no-op parent rerender with no CLI runs", () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    const options = baseOptions();

    act(() => {
      root.render(<Host options={options} />);
    });
    const first = hookResults.at(-1)!;
    expect(first.cliAgentRunTabs).toEqual([]);
    expect(first.mountedCliAgentRuns).toEqual([]);

    // Same props by value, new props object: forces Host to re-render without
    // changing any hook input, which is the session-switch no-op rerender case.
    act(() => {
      root.render(<Host options={{ ...options }} />);
    });
    const second = hookResults.at(-1)!;
    expect(second.cliAgentRunTabs).toBe(first.cliAgentRunTabs);
    expect(second.mountedCliAgentRuns).toBe(first.mountedCliAgentRuns);

    act(() => {
      root.unmount();
    });
  });
});
