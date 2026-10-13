/** @vitest-environment happy-dom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ProjectAgentBusEvent, ProjectAgentBusTimeline } from "../../api/types";
import { ProjectNotificationsPanel } from "./ProjectNotificationsPanel";

const api = vi.hoisted(() => ({
  listProjectAgentBusTimeline: vi.fn(),
  sendProjectAgentBusMessage: vi.fn(),
}));

vi.mock("../../api/projectAgentBus", async (importOriginal) => {
  const original = await importOriginal<typeof import("../../api/projectAgentBus")>();
  return {
    ...original,
    listProjectAgentBusTimeline: api.listProjectAgentBusTimeline,
    sendProjectAgentBusMessage: api.sendProjectAgentBusMessage,
  };
});

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const noticeTime = "2026-10-13T07:10:00.000Z";

function event(overrides: Partial<ProjectAgentBusEvent> = {}): ProjectAgentBusEvent {
  return {
    eventId: "event-1",
    messageType: "agent_broadcast",
    targetScope: "all",
    targetAgentIds: [],
    targetAgentCodes: [],
    targetAgentNames: [],
    mentionedTokens: [],
    unresolvedMentions: [],
    content: "助手通知内容",
    summary: "通知摘要",
    createdBy: "agent-1",
    createdAt: noticeTime,
    updatedAt: noticeTime,
    metadata: {},
    deliveries: [],
    interruptions: [],
    ...overrides,
  };
}

function timeline(events: ProjectAgentBusEvent[] = [event()]): ProjectAgentBusTimeline {
  return { events, activeAgentCount: 1, updatedAt: noticeTime };
}

let root: Root | undefined;
let host: HTMLDivElement;
let client: QueryClient | undefined;

async function mount(props: { onSeen?: (latestEventMs: number) => void } = {}) {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  await act(async () => root?.render(
    <QueryClientProvider client={client!}>
      <ProjectNotificationsPanel lang="zh" {...props} />
    </QueryClientProvider>,
  ));
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 10));
  });
}

function button(label: string) {
  const found = [...document.querySelectorAll("button")]
    .find((item) => item.textContent?.trim() === label);
  expect(found, `button: ${label}`).toBeTruthy();
  return found!;
}

async function click(label: string) {
  await act(async () => {
    button(label).click();
    await new Promise((resolve) => setTimeout(resolve, 10));
  });
}

beforeEach(() => {
  api.listProjectAgentBusTimeline.mockReset().mockResolvedValue(timeline());
  api.sendProjectAgentBusMessage.mockReset().mockResolvedValue(event({ eventId: "sent-event" }));
});

afterEach(async () => {
  await act(async () => root?.unmount());
  root = undefined;
  host?.remove();
  client?.clear();
  client = undefined;
});

describe("ProjectNotificationsPanel", () => {
  it("reports the read cursor after a successful timeline is visible", async () => {
    const onSeen = vi.fn();
    await mount({ onSeen });

    expect(host.textContent).toContain("通知摘要");
    expect(onSeen).toHaveBeenCalledOnce();
    expect(onSeen).toHaveBeenCalledWith(Date.parse(noticeTime));
  });

  it("shows a retryable error and does not advance the read cursor when loading fails", async () => {
    const onSeen = vi.fn();
    api.listProjectAgentBusTimeline.mockRejectedValue(new Error("network unavailable"));
    await mount({ onSeen });

    expect(host.querySelector('[data-testid="project-notifications-error"]')).toBeTruthy();
    expect(host.textContent).toContain("通知加载失败");
    expect(host.textContent).not.toContain("暂时没有通知");
    expect(onSeen).not.toHaveBeenCalled();
  });

  it("opens a secondary broadcast dialog and sends without requesting interruption", async () => {
    api.listProjectAgentBusTimeline.mockResolvedValue(timeline([]));
    await mount();
    await click("发广播");

    expect(document.body.textContent).toContain("发送项目广播");
    expect(document.body.textContent).toContain("不会请求中断目标 Agent");
    expect(document.body.textContent).not.toContain("打断目标助手");
    const textarea = document.querySelector("textarea");
    expect(textarea).toBeTruthy();
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
      setter?.call(textarea, "请检查构建结果");
      textarea?.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await click("发送广播");

    expect(api.sendProjectAgentBusMessage).toHaveBeenCalledWith({ content: "请检查构建结果" });
    expect(document.body.textContent).not.toContain("发送项目广播");
  });
});
