/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { KnowledgeInvocationBadge } from "../../../api/types/research-workflow/core";
import { NodeKnowledgeCollectionSection } from "./NodeKnowledgeCollectionSection";
import styles from "./NodeKnowledgeCollectionSection.styles";

function badgeWith(overrides: {
  status?: string;
  knowledgeChildRunId?: string | null;
  childNodeStates?: Record<string, string>;
}): KnowledgeInvocationBadge {
  return {
    nodeId: "hypothesis_design",
    totalCount: 1,
    runningCount: 0,
    awaitingHandoffCount: 0,
    absorbedCount: 0,
    latest: {
      invocationId: "inv-1",
      parentNodeId: "hypothesis_design",
      status: overrides.status ?? "blocked",
      handoffState: null,
      currentKnowledgeNodeId: null,
      knowledgeChildRunId: overrides.knowledgeChildRunId !== undefined
        ? overrides.knowledgeChildRunId
        : "child-run-1",
      updatedAtMs: 10,
      childNodeStates: overrides.childNodeStates
        ?? { source_finding: "succeeded", source_extraction: "blocked" },
    },
  } as KnowledgeInvocationBadge;
}

async function renderSection(props: {
  badge: KnowledgeInvocationBadge | null;
  onOpenSideflowNode?: (sideflowNodeId: string) => void;
  lang?: "zh" | "en";
}) {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(
      <NodeKnowledgeCollectionSection
        badge={props.badge}
        offers={[]}
        busy={false}
        onOffer={async () => undefined}
        onOpenSideflowNode={props.onOpenSideflowNode}
        lang={props.lang ?? "zh"}
      />,
    );
  });
  return { container, root };
}

const openButton = (container: HTMLElement) =>
  container.querySelector<HTMLButtonElement>('[data-testid="knowledge-sideflow-open-node"]');

describe("NodeKnowledgeCollectionSection blocked sideflow recovery entry", () => {
  let root: Root | null = null;

  afterEach(async () => {
    if (root) {
      await act(async () => root?.unmount());
      root = null;
    }
    document.body.innerHTML = "";
  });

  it("renders the deep-link button for the first blocked card and navigates on click", async () => {
    const onOpenSideflowNode = vi.fn();
    const rendered = await renderSection({
      badge: badgeWith({}),
      onOpenSideflowNode,
    });
    root = rendered.root;
    const { container } = rendered;

    const blockedCard = container.querySelector('[data-sideflow-status="blocked"]');
    expect(blockedCard).not.toBeNull();
    // Blocked card carries the danger emphasis without changing the layout.
    expect(blockedCard!.className).toContain(styles.cardBlocked);
    expect(blockedCard!.className).not.toBe(styles.card);

    const button = openButton(container);
    expect(button).not.toBeNull();
    expect(button!.textContent).toContain("打开知识子流程节点");
    await act(async () => button!.click());
    // Navigation target is the first blocked step in canonical order.
    expect(onOpenSideflowNode).toHaveBeenCalledWith("source_extraction");
  });

  it("localizes the entry label to English", async () => {
    const rendered = await renderSection({
      badge: badgeWith({}),
      onOpenSideflowNode: () => undefined,
      lang: "en",
    });
    root = rendered.root;
    expect(openButton(rendered.container)!.textContent).toContain("Open knowledge sideflow node");
  });

  it("hides the entry when no card is blocked", async () => {
    const onOpenSideflowNode = vi.fn();
    const rendered = await renderSection({
      badge: badgeWith({
        status: "running",
        knowledgeChildRunId: "child-run-1",
        childNodeStates: { source_finding: "succeeded", source_extraction: "running" },
      }),
      onOpenSideflowNode,
    });
    root = rendered.root;
    expect(openButton(rendered.container)).toBeNull();
    expect(onOpenSideflowNode).not.toHaveBeenCalled();
  });

  it("hides the entry when the child run id is missing (no resolvable target)", async () => {
    const onOpenSideflowNode = vi.fn();
    const rendered = await renderSection({
      badge: badgeWith({ knowledgeChildRunId: null }),
      onOpenSideflowNode,
    });
    root = rendered.root;
    expect(rendered.container.querySelector('[data-sideflow-status="blocked"]')).not.toBeNull();
    expect(openButton(rendered.container)).toBeNull();
  });

  it("hides the entry when no navigation handler is wired (fail-closed)", async () => {
    const rendered = await renderSection({ badge: badgeWith({}) });
    root = rendered.root;
    expect(openButton(rendered.container)).toBeNull();
  });
});
