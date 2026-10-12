// @vitest-environment happy-dom
/**
 * Semantic-index status badge on the knowledge search tab: tone/label mapping
 * (same as MemoryKnowledgeRagPanel), tooltip count interpolation, and the
 * no-data/undefined case rendering no badge at all. ModeTabs stays a pure
 * component — health data arrives via props, never useQuery/fetchJson.
 */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import modeTabsSource from "./MemoryKnowledgeModeTabs.tsx?raw";
import { MemoryKnowledgeModeTabs, type MemoryKnowledgeModeTabsCopy } from "./MemoryKnowledgeModeTabs";
import { VuiProvider } from "../components/vui";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const copy: MemoryKnowledgeModeTabsCopy = {
  governance: "Governance",
  ownerSourceInbox: "Source inbox",
  centralSources: "Central sources",
  knowledgeSearch: "Knowledge search",
  ragRetrieval: "RAG retrieval",
  pendingProposals: "Pending proposals",
  ratingSuggestions: "Rating suggestions",
  operationsHealth: "Operations health",
  governanceTasks: "Governance tasks",
  permissionAudit: "Permission audit",
  ingestionAdapters: "Ingestion adapters",
  semanticIndex: "Semantic index",
  semanticIndexReady: "Ready",
  semanticIndexDegraded: "Partially available",
  semanticIndexUnknown: "Unknown status",
  semanticIndexUnavailable: "Unavailable",
  semanticIndexIndexed: "Indexed",
  semanticIndexTotal: "Indexable",
};

let root: Root | null = null;
let container: HTMLElement;

function mountModeTabs(semanticIndexHealth?: { status: string; indexedItemCount?: number; indexableItemCount?: number }) {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => {
    root?.render(
      <VuiProvider>
        <MemoryKnowledgeModeTabs
          copy={copy}
          lang="en"
          activeMode="sources"
          sourceCount={0}
          centralSourceCount={0}
          searchResultCount={0}
          ragContextCount={0}
          pendingProposalCount={0}
          ratingSuggestionCount={0}
          operationsFindingCount={0}
          openGovernanceTaskCount={0}
          permissionKnowledgeBaseCount={0}
          ingestionAdapterCount={0}
          semanticIndexHealth={semanticIndexHealth}
          onModeChange={() => {}}
        />
      </VuiProvider>,
    );
  });
}

afterEach(() => {
  vi.useRealTimers();
  act(() => {
    root?.unmount();
  });
  root = null;
  container?.remove();
});

function statusChip(): HTMLElement | null {
  return container.querySelector<HTMLElement>('[data-vui="status-chip"]');
}

function hoverChip(chip: Element) {
  // React maps onPointerEnter to bubbling pointerover, not pointerenter.
  act(() => {
    chip.dispatchEvent(new MouseEvent("pointerover", { bubbles: true }));
  });
  act(() => {
    vi.advanceTimersByTime(400);
  });
}

describe("MemoryKnowledgeModeTabs semantic index badge", () => {
  it("renders a success chip for ready health with tooltip counts", () => {
    vi.useFakeTimers();
    mountModeTabs({ status: "ready", indexedItemCount: 8, indexableItemCount: 10 });

    const chip = statusChip();
    expect(chip).not.toBeNull();
    expect(chip?.getAttribute("data-tone")).toBe("success");
    expect(chip?.textContent).toBe("Ready");

    hoverChip(chip as Element);
    const tooltip = document.querySelector('[data-vui="tooltip-content"]');
    expect(tooltip?.textContent).toContain("Semantic index: Ready");
    expect(tooltip?.textContent).toContain("Indexed: 8");
    expect(tooltip?.textContent).toContain("Indexable: 10");
  });

  it("renders a warning chip with degraded label for degraded health", () => {
    mountModeTabs({ status: "degraded", indexedItemCount: 3, indexableItemCount: 9 });

    const chip = statusChip();
    expect(chip?.getAttribute("data-tone")).toBe("warning");
    expect(chip?.textContent).toBe("Partially available");
  });

  it("renders a danger chip with unavailable label for unavailable health", () => {
    mountModeTabs({ status: "unavailable", indexedItemCount: 0, indexableItemCount: 5 });

    const chip = statusChip();
    expect(chip?.getAttribute("data-tone")).toBe("danger");
    expect(chip?.textContent).toBe("Unavailable");
  });

  it("falls back to warning tone and unknown label for unrecognized status", () => {
    mountModeTabs({ status: "building", indexedItemCount: 1, indexableItemCount: 4 });

    const chip = statusChip();
    expect(chip?.getAttribute("data-tone")).toBe("warning");
    expect(chip?.textContent).toBe("Unknown status");
  });

  it("renders no badge while health is undefined (query pending or disabled)", () => {
    mountModeTabs(undefined);

    expect(statusChip()).toBeNull();
    // The tab strip itself is untouched: five triggers still render.
    expect(container.querySelectorAll('[data-slot="tabs-trigger"]')).toHaveLength(5);
  });

  it("keeps ModeTabs free of data fetching (props-only, per layout contract)", () => {
    expect(modeTabsSource).not.toContain("useQuery");
    expect(modeTabsSource).not.toContain("useMutation");
    expect(modeTabsSource).not.toContain("fetchJson");
  });
});
