/** @vitest-environment happy-dom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "../api/queryKeys";
import type { SkillLibraryItem, SkillLibraryPayload } from "../api/types";
import { SkillsRoute } from "./SkillsRoute";

vi.mock("../i18n/useShellI18n", () => ({ useShellI18n: () => ({ lang: "zh" }) }));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const skills: SkillLibraryItem[] = ["Alpha", "Beta"].map((name, index) => ({
  name,
  aliases: [`${name.toLowerCase()}-alias`],
  command: `/${name.toLowerCase()}`,
  description: `${name} description`,
  source: index ? "agents" : "codex",
  rootPath: "C:/skills",
  path: `C:/skills/${name}/SKILL.md`,
  directoryName: name,
  hash: `${name}-hash`,
  contentLength: 40,
  preview: `${name} preview`,
  previewTruncated: false,
}));

let host: HTMLDivElement | null = null;
let root: Root | null = null;
let client: QueryClient | null = null;
let clipboardDescriptor: PropertyDescriptor | undefined;

function renderSkills() {
  client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  client.setQueryData<SkillLibraryPayload>(queryKeys.skills(), {
    schemaVersion: 1,
    mode: "read_only",
    roots: [],
    counts: { total: 2, codex: 1, agents: 1, other: 0 },
    skills,
  });
  skills.forEach((skill) => client?.setQueryData(queryKeys.skill(skill.command), {
    ...skill,
    content: `${skill.name} full content`,
    contentTruncated: false,
  }));
  const writeText = vi.fn().mockResolvedValue(undefined);
  clipboardDescriptor = Object.getOwnPropertyDescriptor(navigator, "clipboard");
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  act(() => root?.render(
    <QueryClientProvider client={client!}>
      <MemoryRouter><SkillsRoute /></MemoryRouter>
    </QueryClientProvider>,
  ));
  return { container: host, writeText };
}

function button(container: HTMLElement, text: string) {
  const target = Array.from(container.querySelectorAll("button")).find((node) => node.textContent?.trim() === text);
  expect(target, `button ${text}`).toBeDefined();
  return target!;
}

async function click(element: HTMLElement) {
  await act(async () => element.click());
}

afterEach(async () => {
  await act(async () => root?.unmount());
  client?.clear();
  host?.remove();
  root = null;
  client = null;
  host = null;
  if (clipboardDescriptor) Object.defineProperty(navigator, "clipboard", clipboardDescriptor);
  else Reflect.deleteProperty(navigator, "clipboard");
});

describe("SkillsRoute bulk selection", () => {
  it("starts in reading mode, copies only chosen commands and clears selection on exit", async () => {
    const { container, writeText } = renderSkills();
    expect(container.querySelector('input[type="checkbox"]')).toBeNull();
    expect(container.querySelector('[data-vui="dense-toolbar"]')).toBeNull();
    expect(container.textContent).toContain("技能库当前是只读索引");
    expect(container.querySelector("pre")?.textContent).toBe("Alpha full content");
    await click(button(container, "复制指令"));
    expect(writeText).toHaveBeenLastCalledWith("/alpha ");

    await click(button(container, "批量选择"));
    expect(container.querySelectorAll('input[type="checkbox"]')).toHaveLength(2);
    expect(container.textContent).not.toContain("批量复制指令");
    await click(container.querySelector<HTMLInputElement>('input[aria-label="已选: Beta"]')!);
    await click(button(container, "批量复制指令"));
    expect(writeText).toHaveBeenLastCalledWith("/beta ");
    expect(container.querySelector("pre")?.textContent).toBe("Alpha full content");

    await click(button(container, "退出选择"));
    expect(container.querySelector('input[type="checkbox"]')).toBeNull();
    expect(container.querySelector('[data-vui="dense-toolbar"]')).toBeNull();
    await click(button(container, "批量选择"));
    expect(Array.from(container.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')).every((input) => !input.checked)).toBe(true);
    expect(container.textContent).not.toContain("批量复制指令");
  });

  it("selects visible rows and trims the selection after a source filter changes", async () => {
    const { container, writeText } = renderSkills();
    await click(button(container, "批量选择"));
    await click(button(container, "选择可见"));
    await click(button(container, "批量复制指令"));
    expect(writeText).toHaveBeenLastCalledWith("/alpha \n/beta ");

    const codexTab = Array.from(container.querySelectorAll<HTMLElement>('[role="tab"]')).find((tab) => tab.textContent === "Codex")!;
    await act(async () => {
      codexTab.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 }));
      codexTab.click();
    });
    expect(container.querySelectorAll('input[type="checkbox"]')).toHaveLength(1);
    expect(container.querySelector('input[aria-label="已选: Beta"]')).toBeNull();
    await click(button(container, "批量复制指令"));
    expect(writeText).toHaveBeenLastCalledWith("/alpha ");
    await click(button(container, "清除选择"));
    expect(container.textContent).not.toContain("批量复制指令");
  });
});
