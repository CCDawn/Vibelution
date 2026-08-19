/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SourceCollectionStageModule } from "../stageModulesModel";
import type { SourceCollectionStageCardProjection } from "../stageProjection";
import { TeamSourceCollectionActiveStageWorkspacePanel } from "./TeamSourceCollectionActiveStageWorkspacePanel";
import type { TeamSourceCollectionActiveStageWorkspacePanelProps } from "./TeamSourceCollectionActiveStageWorkspacePanel";

type Props = TeamSourceCollectionActiveStageWorkspacePanelProps;

function stageModule(overrides: Partial<SourceCollectionStageModule> = {}): SourceCollectionStageModule {
  return {
    id: "finding",
    label: "资料发现",
    metric: "",
    summary: "",
    inputLabel: "",
    outputLabel: "",
    nextLabel: "",
    state: "active",
    status: "进行中",
    detailLabel: "",
    actionLabel: "开始搜集",
    actionDisabled: false,
    actionTone: "primary",
    actionIcon: "play",
    onAction: vi.fn(),
    onDetail: vi.fn(),
    ...overrides,
  };
}

function baseProps(overrides: Partial<Props> = {}): Props {
  return {
    lang: "zh",
    sourceCollectionStageModules: [stageModule()],
    selectedSourceCollectionStageId: "finding",
    sourceCollectionStageAgentChatState: (() => ({ status: "ready", route: "/chat/agent-1" })) as unknown as Props["sourceCollectionStageAgentChatState"],
    repairChallengeCupTeamAgentsMutation: { isPending: false } as unknown as Props["repairChallengeCupTeamAgentsMutation"],
    sourceCollectionActionDisabledTitle: () => undefined,
    sourceCollectionStageActionReadinessFor: (() => ({ disabled: false })) as unknown as Props["sourceCollectionStageActionReadinessFor"],
    sourceCollectionStagePrimaryAgentBinding: (() => null) as unknown as Props["sourceCollectionStagePrimaryAgentBinding"],
    stageChatLabels: {
      finding: { zh: "资料发现 Agent 私聊", en: "Finding agent chat" },
      extraction: { zh: "资料提炼 Agent 私聊", en: "Extraction agent chat" },
      relations: { zh: "关系整理 Agent 私聊", en: "Relations agent chat" },
      ingestion: { zh: "入库 Agent 私聊", en: "Ingestion agent chat" },
    },
    openSourceCollectionStageAgentChat: vi.fn(),
    startSourceCollectionStageSessionTask: vi.fn(),
    sourceCollectionRunAvailable: true,
    sourceCollectionFindingStageCompact: false,
    selectedTeamStartSourceCollectionStageTaskError: null,
    renderSourceCollectionConversation: () => null,
    renderSourceCollectionScreeningPanel: () => null,
    renderSourceCollectionGraphPanel: () => null,
    renderSourceCollectionMemoryPanel: () => null,
    ...overrides,
  };
}

async function renderPanel(props: Props) {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(
      <MemoryRouter>
        <TeamSourceCollectionActiveStageWorkspacePanel {...props} />
      </MemoryRouter>,
    );
  });
  return { container, root };
}

function primaryButton(container: HTMLElement, label: string): HTMLButtonElement {
  const button = Array.from(container.querySelectorAll("button"))
    .find((item) => item.textContent?.includes(label));
  expect(button, `primary action button containing "${label}"`).toBeTruthy();
  return button!;
}

describe("TeamSourceCollectionActiveStageWorkspacePanel", () => {
  let root: Root | null = null;

  afterEach(async () => {
    if (root) {
      await act(async () => root?.unmount());
      root = null;
    }
    document.body.innerHTML = "";
  });

  it("runs the stage action directly when nothing is blocked", async () => {
    const module = stageModule();
    const startStageTask = vi.fn();
    const rendered = await renderPanel(baseProps({
      sourceCollectionStageModules: [module],
      startSourceCollectionStageSessionTask: startStageTask,
    }));
    root = rendered.root;

    await act(async () => {
      primaryButton(rendered.container, "开始搜集").dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(module.onAction).toHaveBeenCalledTimes(1);
    expect(startStageTask).not.toHaveBeenCalled();
    expect(rendered.container.textContent).not.toContain("系统重试");
  });

  it("routes a blocked stage through a formal retry instead of the local action", async () => {
    const projection = {
      stageId: "finding",
      status: "agent_blocked",
      latestTask: {
        status: "blocked",
        closureSummary: { message: "上一轮没有产生可用产物。" },
      },
    } as unknown as SourceCollectionStageCardProjection;
    const module = stageModule({ projection });
    const startStageTask = vi.fn();
    const rendered = await renderPanel(baseProps({
      sourceCollectionStageModules: [module],
      startSourceCollectionStageSessionTask: startStageTask,
    }));
    root = rendered.root;

    expect(rendered.container.textContent).toContain("系统重试");
    expect(rendered.container.textContent).toContain("推进失败");
    expect(rendered.container.textContent).toContain("上一轮没有产生可用产物。");

    await act(async () => {
      primaryButton(rendered.container, "开始搜集").dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(startStageTask).toHaveBeenCalledTimes(1);
    expect(startStageTask).toHaveBeenCalledWith("finding", { formalRetry: true });
    expect(module.onAction).not.toHaveBeenCalled();
  });

  it("rewrites the relations CTA after a relations advance failure", async () => {
    const module = stageModule({
      id: "relations",
      label: "关系整理",
      actionLabel: "推进关系整理",
    });
    const rendered = await renderPanel(baseProps({
      sourceCollectionStageModules: [module],
      selectedSourceCollectionStageId: "relations",
      sourceCollectionStageAdvanceFailure: "推进失败：关系缺口 60 条",
    }));
    root = rendered.root;

    expect(primaryButton(rendered.container, "继续整理关系")).toBeTruthy();
  });
});
