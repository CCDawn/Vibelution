/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";

import { useResearchWorkflowWorkspace } from "./useResearchWorkflowWorkspace";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function Harness() {
  const workspace = useResearchWorkflowWorkspace("research-team");
  const location = useLocation();
  return (
    <>
      <output data-testid="search">{location.search}</output>
      <output data-testid="inspector-open">{String(workspace.inspectorOpen)}</output>
      <button
        type="button"
        onClick={() => {
          workspace.openPanel("agents");
          // React Flow may synchronously repeat the already-selected node while
          // the toolbar navigation is still committing. It must not win.
          workspace.selectNode("source_extraction");
        }}
      >
        open agents
      </button>
      <button
        type="button"
        onClick={() => {
          workspace.replaceParams({ runId: "run-next" });
          workspace.replaceParams({ node: "hf_generation" });
        }}
      >
        merge route patches
      </button>
      <button type="button" onClick={() => workspace.replaceParams({ inspector: "closed" })}>
        close inspector
      </button>
      <button type="button" onClick={() => workspace.replaceParams({ inspector: null })}>
        open inspector
      </button>
    </>
  );
}

describe("useResearchWorkflowWorkspace", () => {
  let root: Root | null = null;
  let container: HTMLDivElement | null = null;

  afterEach(async () => {
    if (root) await act(async () => root?.unmount());
    container?.remove();
    root = null;
    container = null;
  });

  it("keeps toolbar panel navigation authoritative over a repeated canvas selection", async () => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(
        <MemoryRouter initialEntries={["/teams?teamId=research-team&panel=node&node=source_extraction"]}>
          <Harness />
        </MemoryRouter>,
      );
    });

    await act(async () => {
      (container?.querySelector("button") as HTMLButtonElement).click();
    });

    const search = container.querySelector('[data-testid="search"]')?.textContent ?? "";
    expect(search).toContain("panel=agents");
    expect(search).toContain("node=source_extraction");
  });

  it("merges route patches issued before React commits the next location", async () => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(
        <MemoryRouter initialEntries={["/teams?teamId=research-team&panel=node&questionId=SCI-002"]}>
          <Harness />
        </MemoryRouter>,
      );
    });

    await act(async () => {
      const buttons = container?.querySelectorAll("button");
      (buttons?.[1] as HTMLButtonElement).click();
    });

    const search = container.querySelector('[data-testid="search"]')?.textContent ?? "";
    expect(search).toContain("runId=run-next");
    expect(search).toContain("node=hf_generation");
    expect(search).toContain("questionId=SCI-002");
  });

  it("keeps responsive inspector close and reopen state in the route", async () => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(
        <MemoryRouter initialEntries={["/teams?teamId=research-team&panel=node&node=hf_generation"]}>
          <Harness />
        </MemoryRouter>,
      );
    });

    const buttons = container.querySelectorAll("button");
    await act(async () => (buttons[2] as HTMLButtonElement).click());
    expect(container.querySelector('[data-testid="search"]')?.textContent).toContain("inspector=closed");
    expect(container.querySelector('[data-testid="inspector-open"]')?.textContent).toBe("false");

    await act(async () => (buttons[3] as HTMLButtonElement).click());
    expect(container.querySelector('[data-testid="search"]')?.textContent).not.toContain("inspector=");
    expect(container.querySelector('[data-testid="inspector-open"]')?.textContent).toBe("true");
  });
});
