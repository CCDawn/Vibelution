// @vitest-environment happy-dom
/**
 * Session helper entry navigation: clicking a session helper card's chat
 * entry performs in-app SPA navigation to "/chat?session=<id>" instead of a
 * bare-href full page reload, and a helper route without a parsable session
 * id surfaces a visible error state instead of silently opening the chat
 * shell (ISS-093 regression).
 */
import React from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { createMemoryRouter, RouterProvider, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";

import type { HealthDiagnostics, SessionHelper } from "../api/types";
import { ConfigHealthDiagnosticsPanel, type ConfigHealthDiagnosticsPanelCopy } from "./ConfigHealthDiagnosticsPanel";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const copy: ConfigHealthDiagnosticsPanelCopy = {
  healthTitle: "健康诊断",
  healthBody: "诊断说明",
  healthLoading: "加载中",
  healthEmpty: "暂无",
  healthRefresh: "刷新",
  healthPriority: "优先项",
  healthQuickActions: "快捷操作",
  healthEvidence: "证据",
  healthRecommended: "建议",
  healthRelatedFindings: "相关发现",
  healthNoFindings: "无发现",
  healthOpenLogs: "打开日志",
  healthOpenChat: "打开会话页",
  healthOpenLauncher: "打开 Launcher",
  healthOpen: "打开",
  healthFiles: "文件",
  healthDirs: "目录",
  healthSessions: "会话",
  healthBusy: "忙碌",
  healthFailed: "失败",
  healthStale: "过期",
  healthPhase: "阶段",
  healthLatest: "最新信号",
  healthUpdated: "更新时间",
  healthSize: "大小",
  healthProtected: "受保护",
  healthMaintenanceAvailable: "可维护",
  healthStatusOk: "正常",
  healthStatusWarning: "警告",
  healthStatusBlocked: "受阻",
  healthMissing: "未记录",
  healthNotRecorded: "未记录",
};

function sessionHelperFixture(route: string): SessionHelper {
  return {
    id: "helper-1",
    title: "自进化执行者",
    description: "诊断描述",
    status: "warning",
    statusLabel: "",
    sessionCount: 2,
    busyCount: 0,
    failedCount: 0,
    staleCount: 0,
    activeSessionId: "s-1",
    activeTitle: "活动标题",
    currentPhase: "",
    updatedAt: "2026-11-06T00:00:00Z",
    latestSignal: "",
    recommendedAction: "",
    route,
    protected: true,
    protectedReason: "",
    findingIds: [],
    primaryFindingId: "",
  };
}

function diagnosticsFixture(sessionHelpers: SessionHelper[]): HealthDiagnostics {
  return {
    status: "warning",
    summary: "",
    counts: { ok: 0, warning: 1, blocked: 0 },
    findings: [],
    quickActions: [],
    sessionHelpers,
    logHelpers: [],
  };
}

describe("ConfigHealthDiagnosticsPanel session helper navigation", () => {
  let host: HTMLDivElement;
  let root: Root | undefined;

  afterEach(() => {
    act(() => root?.unmount());
    host?.remove();
    root = undefined;
  });

  function renderPanel(helper: SessionHelper) {
    host = document.createElement("div");
    document.body.appendChild(host);
    let chatLocation = "";
    function ChatProbe() {
      const location = useLocation();
      chatLocation = `${location.pathname}${location.search}`;
      return <output>chat-probe</output>;
    }
    const router = createMemoryRouter(
      [
        {
          path: "/config",
          element: (
            <ConfigHealthDiagnosticsPanel
              diagnostics={diagnosticsFixture([helper])}
              loading={false}
              lang="zh"
              copy={copy}
              onRefresh={() => undefined}
            />
          ),
        },
        { path: "/chat", element: <ChatProbe /> },
      ],
      { initialEntries: ["/config"] },
    );
    act(() => {
      root = createRoot(host);
      root?.render(<RouterProvider router={router} />);
    });
    return () => chatLocation;
  }

  it("navigates in-app to the helper session instead of a full reload", () => {
    const readChatLocation = renderPanel(sessionHelperFixture("/chat?session=s-1"));

    const entry = host.querySelector<HTMLAnchorElement>("a[href='/chat?session=s-1']");
    expect(entry, "session helper entry renders as a link").not.toBeNull();
    expect(entry?.textContent).toContain("打开会话页");

    act(() => {
      entry?.click();
    });

    expect(readChatLocation()).toBe("/chat?session=s-1");
  });

  it("shows a visible error state when the helper route has no session target", () => {
    const readChatLocation = renderPanel(sessionHelperFixture(""));

    const entry = host.querySelector("a");
    expect(entry, "invalid target renders no live link").toBeNull();
    expect(host.querySelector("[role='alert']")?.textContent).toContain("会话入口无效");

    act(() => {
      host.querySelector<HTMLElement>("[aria-disabled='true']")?.click();
    });

    expect(readChatLocation()).toBe("");
  });
});
