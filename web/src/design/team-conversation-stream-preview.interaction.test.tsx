/** @vitest-environment happy-dom */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { VuiProvider } from "../components/vui";
import { TeamConversationStreamPreviewApp } from "./team-conversation-stream-preview";
import { LONG_INTERNAL_DISCUSSION } from "./teamConversationStreamModel";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe("team conversation stream preview", () => {
  let root: Root | null = null;
  let container: HTMLDivElement | null = null;

  afterEach(async () => {
    if (root) {
      await act(async () => {
        root?.unmount();
      });
    }
    container?.remove();
    root = null;
    container = null;
    window.history.replaceState(null, "", "/");
  });

  async function mountPreview() {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(
        <VuiProvider>
          <TeamConversationStreamPreviewApp />
        </VuiProvider>,
      );
    });
    return container;
  }

  it("keeps the product Tailwind utility entry in the overlay import chain", () => {
    const previewSource = readFileSync(
      resolve(import.meta.dirname, "team-conversation-stream-preview.tsx"),
      "utf8",
    );
    const tokenIndex = previewSource.indexOf('"./tokens.css"');
    const tailwindIndex = previewSource.indexOf('"./tailwind.css"');
    const providerThemeIndex = previewSource.indexOf('"./vui-provider-theme.css"');
    expect(tokenIndex).toBeGreaterThan(-1);
    expect(tailwindIndex).toBeGreaterThan(tokenIndex);
    expect(providerThemeIndex).toBeGreaterThan(tailwindIndex);
  });

  it("hides current discuss bodies and keeps proposed speech readable", async () => {
    const host = await mountPreview();
    const current = host.querySelector('[data-testid="current-timeline"]');
    const proposed = host.querySelector('[data-testid="proposed-timeline"]');
    expect(current).toBeTruthy();
    expect(proposed).toBeTruthy();
    expect(current?.querySelector(".groupBubbleBodyCollapsed")).toBeTruthy();
    expect(Array.from(current?.querySelectorAll("button") ?? []).some((button) => button.textContent === "展开讨论")).toBe(true);
    expect(proposed?.querySelector(".groupBubbleBodyCollapsed")).toBeNull();
    const clampedBody = proposed?.querySelector('[data-testid="stream-body-clamped-m-planner"]');
    expect(clampedBody).toBeTruthy();
    expect(clampedBody?.textContent).toContain(LONG_INTERNAL_DISCUSSION.slice(0, 24));
    expect(proposed?.textContent).toContain("已处理 2 个工具");
  });

  it("expands a clamped proposed body without using hidden", async () => {
    const host = await mountPreview();
    const expand = Array.from(host.querySelectorAll("button")).find((button) => (
      button.textContent?.trim() === "展开全文"
    ));
    expect(expand).toBeTruthy();
    await act(async () => {
      expand?.click();
    });
    expect(host.querySelector('[data-testid="stream-body-clamped-m-planner"]')).toBeNull();
    expect(host.querySelector('[data-testid="stream-body-m-planner"]')?.textContent).toBe(LONG_INTERNAL_DISCUSSION);
    expect(host.querySelector(".groupBubbleBodyCollapsed")).toBeTruthy();
  });

  it("keeps proposed avatar and speaker name as siblings on one identity row", async () => {
    const host = await mountPreview();
    const previewSource = readFileSync(
      resolve(import.meta.dirname, "team-conversation-stream-preview.tsx"),
      "utf8",
    );
    const previewCss = readFileSync(
      resolve(import.meta.dirname, "team-conversation-stream-preview.css"),
      "utf8",
    );
    const identity = host.querySelector('[data-testid="stream-identity-row"]');
    const avatar = identity?.querySelector(".tcs-stream-avatar");
    const header = identity?.querySelector('[data-testid="stream-speaker-header"]');
    expect(identity?.className).toContain("tcs-stream-identity");
    expect(avatar?.textContent).toBe("顾");
    expect(header?.textContent).toContain("顾言初");
    expect(avatar?.nextElementSibling).toBe(header);
    expect(previewSource).toContain('data-testid="stream-identity-row"');
    expect(previewCss).toMatch(/\.tcs-stream-identity\s*\{[^}]*display:\s*flex/s);
    expect(previewCss).toMatch(/flex-direction:\s*row/);
  });

  it("groups consecutive same-speaker rows in the proposed column", async () => {
    const host = await mountPreview();
    const consecutive = Array.from(host.querySelectorAll("button")).find((button) => button.textContent === "连续同说话人");
    await act(async () => {
      consecutive?.click();
    });
    const proposed = host.querySelector('[data-testid="proposed-timeline"]');
    const current = host.querySelector('[data-testid="current-timeline"]');
    expect(proposed?.querySelectorAll('[data-testid="stream-speaker-header"]').length).toBe(2);
    expect(current?.querySelectorAll("article").length).toBe(4);
    expect(proposed?.querySelectorAll('[data-testid="stream-cluster-agent-planner"] article').length).toBe(3);
  });

  it("puts the round digest in one proposed card after the stream", async () => {
    const host = await mountPreview();
    const summary = Array.from(host.querySelectorAll("button")).find((button) => button.textContent === "轮次摘要");
    await act(async () => {
      summary?.click();
    });
    expect(host.querySelector('[data-testid="proposed-digest"]')?.textContent).toContain("本轮纪要");
    expect(host.querySelector('[data-testid="proposed-round-hairline"]')?.textContent).toContain("已结束");
  });
});
