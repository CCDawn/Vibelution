/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { VCommandPalette } from "./VCommandPalette";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function items() {
  return [
    {
      id: "cmd:current",
      group: "命令",
      label: "前往当前任务",
      onRun: vi.fn(),
    },
    {
      id: "question:SCI-001",
      group: "题目",
      label: "SCI-001",
      detail: "What makes prime numbers so special?",
      keywords: "SCI-001 primes",
      onRun: vi.fn(),
    },
    {
      id: "question:SCI-096",
      group: "题目",
      label: "SCI-096",
      detail: "What are the coding principles embedded in neuronal spike trains?",
      keywords: "SCI-096 neurons",
      onRun: vi.fn(),
    },
  ];
}

describe("VCommandPalette", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
  });

  it("filters by substring and fuzzy subsequence, then runs the active item on Enter", async () => {
    const list = items();
    act(() => {
      root.render(
        <VCommandPalette
          open
          onOpenChange={() => {}}
          items={list}
          labels={{ searchPlaceholder: "搜索", emptyTitle: "无匹配", hint: "hint" }}
        />,
      );
    });
    const input = await vi.waitFor(() => {
      const found = document.querySelector("input");
      expect(found).not.toBeNull();
      return found as HTMLInputElement;
    });
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype,
      "value",
    )?.set;
    await act(async () => {
      setter?.call(input, "neurons");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await vi.waitFor(() => {
      expect(document.body.textContent).toContain("SCI-096");
    });
    expect(document.body.textContent).not.toContain("SCI-001");

    const active = document.querySelector('[data-active="true"]') as HTMLElement;
    await act(async () => {
      active?.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Enter", bubbles: true }),
      );
    });
    expect(list[2].onRun).toHaveBeenCalledTimes(1);
    expect(list[0].onRun).not.toHaveBeenCalled();
  });

  it("shows the empty state for unmatched queries", async () => {
    act(() => {
      root.render(
        <VCommandPalette
          open
          onOpenChange={() => {}}
          items={items()}
          labels={{ searchPlaceholder: "搜索", emptyTitle: "没有匹配项", hint: "hint" }}
        />,
      );
    });
    const input = await vi.waitFor(() => {
      const found = document.querySelector("input");
      expect(found).not.toBeNull();
      return found as HTMLInputElement;
    });
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype,
      "value",
    )?.set;
    await act(async () => {
      setter?.call(input, "zzzz");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await vi.waitFor(() => {
      expect(document.body.textContent).toContain("没有匹配项");
    });
  });

  it("keeps keyboard selections rendered beyond the former result cap", async () => {
    const list = Array.from({ length: 40 }, (_, index) => ({
      id: String(index), group: "Tasks", label: `Task ${index}`, onRun: vi.fn(),
    }));
    await act(async () => root.render(
      <VCommandPalette open onOpenChange={() => {}} items={list} maxVisible={7}
        labels={{ searchPlaceholder: "Search", emptyTitle: "Empty", hint: "hint" }} />,
    ));
    const input = document.querySelector("input")!;
    for (let index = 0; index < 35; index += 1) {
      await act(async () => input.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true })));
      expect(document.querySelector('[data-active="true"]')?.textContent).toBe(`Task ${index + 1}`);
    }
    await act(async () => input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })));
    expect(list[35].onRun).toHaveBeenCalledOnce();
  });

  it("runs the focused row and clamps selection when results shrink", async () => {
    const list = items();
    const render = (next: typeof list) => root.render(
      <VCommandPalette open onOpenChange={() => {}} items={next}
        labels={{ searchPlaceholder: "Search", emptyTitle: "Empty", hint: "hint" }} />,
    );
    await act(async () => render(list));
    const row = document.querySelector<HTMLElement>('[data-index="2"]')!;
    await act(async () => row.focus());
    await act(async () => row.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })));
    expect(list[2].onRun).toHaveBeenCalledOnce();
    await act(async () => row.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowUp", bubbles: true })));
    expect(document.activeElement?.getAttribute("data-index")).toBe("1");
    await act(async () => document.activeElement!.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })));
    expect(list[1].onRun).toHaveBeenCalledOnce();
    await act(async () => render(list.slice(0, 1)));
    expect(document.querySelector('[data-active="true"]')?.textContent).toContain(list[0].label);
    await act(async () => document.querySelector("input")!.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })));
    expect(list[0].onRun).toHaveBeenCalledOnce();
  });
});
