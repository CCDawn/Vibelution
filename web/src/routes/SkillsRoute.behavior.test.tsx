/** @vitest-environment happy-dom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "../api/queryKeys";
import type { SkillLibraryDetail, SkillLibraryItem, SkillLibraryPayload } from "../api/types";
import { SkillsRoute } from "./SkillsRoute";

vi.mock("../i18n/useShellI18n", () => ({ useShellI18n: () => ({ lang: "zh" }) }));

// The detail transport is mocked so a test can observe which (command, source)
// pair the route asks for. The list query is always pre-seeded, so the list
// transport must never be reached.
const { detailFetch } = vi.hoisted(() => ({
  detailFetch: vi.fn<(command: string, source?: string) => Promise<SkillLibraryDetail>>(),
}));
vi.mock("../api/skills", () => ({
  fetchSkillLibrary: vi.fn(() => Promise.reject(new Error("unexpected skill list fetch"))),
  fetchSkillLibraryDetail: detailFetch,
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function makeSkill(name: string, source: "codex" | "agents", command = `/${name.toLowerCase()}`): SkillLibraryItem {
  const rootPath = source === "codex" ? "C:/home/.codex/skills" : "C:/home/.agents/skills";
  return {
    name,
    aliases: [`${name.toLowerCase()}-alias`],
    command,
    description: `${name} description`,
    source,
    rootPath,
    path: `${rootPath}/${name}/SKILL.md`,
    directoryName: name,
    hash: `${name}-${source}-hash`,
    contentLength: 40,
    preview: `${name} preview`,
    previewTruncated: false,
  };
}

// Alpha/Beta keep distinct commands. The two "Shared" rows reproduce the
// real-world collision: one slash command installed under both roots.
const uniqueSkills: SkillLibraryItem[] = [makeSkill("Alpha", "codex"), makeSkill("Beta", "agents")];
const sharedCodex = makeSkill("Shared", "codex", "/shared");
const sharedAgents = makeSkill("Shared", "agents", "/shared");
const skills: SkillLibraryItem[] = [...uniqueSkills, sharedCodex, sharedAgents];

function commandOf(skill: SkillLibraryItem) {
  return skill.command.replace(/^\/+/, "");
}

function detailOf(skill: SkillLibraryItem): SkillLibraryDetail {
  return { ...skill, content: `${skill.name} ${skill.source} full content`, contentTruncated: false };
}

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
    counts: { total: 4, codex: 2, agents: 2, other: 0 },
    skills,
  });
  // Only the distinct-command rows are pre-seeded; the Shared pair must go
  // through the (mocked) detail transport so the request shape is asserted.
  uniqueSkills.forEach((skill) => client?.setQueryData(queryKeys.skill(commandOf(skill), skill.source), detailOf(skill)));
  detailFetch.mockReset();
  detailFetch.mockImplementation(async (command, source = "") => {
    const match = skills.find((skill) => commandOf(skill) === command && skill.source === source);
    if (!match) throw new Error(`unexpected detail fetch ${command}/${source}`);
    return detailOf(match);
  });
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

// Skill rows render "<strong>name</strong><small>source caption</small>"; two
// rows can share a name, so the pair identifies one row.
function skillRow(container: HTMLElement, name: string, sourceCaption: string) {
  const target = Array.from(container.querySelectorAll<HTMLButtonElement>("button[aria-pressed]")).find(
    (node) => node.querySelector("strong")?.textContent === name && node.querySelector("small")?.textContent === sourceCaption,
  );
  expect(target, `skill row ${name}/${sourceCaption}`).toBeDefined();
  return target!;
}

function pressedSkillRows(container: HTMLElement) {
  return Array.from(container.querySelectorAll<HTMLButtonElement>('button[aria-pressed="true"]')).filter((node) => node.querySelector("strong"));
}

async function click(element: HTMLElement) {
  await act(async () => element.click());
}

// The detail transport resolves immediately, so settling the pending query
// inside act() is deterministic; this keeps React from warning about updates
// escaping act().
async function flushQueries() {
  for (let i = 0; i < 4; i += 1) {
    await act(async () => {
      await Promise.resolve();
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  }
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
    expect(container.querySelector("pre")?.textContent).toBe("Alpha codex full content");
    await click(button(container, "复制指令"));
    expect(writeText).toHaveBeenLastCalledWith("/alpha ");

    await click(button(container, "批量选择"));
    expect(container.querySelectorAll('input[type="checkbox"]')).toHaveLength(4);
    expect(container.textContent).not.toContain("批量复制指令");
    await click(container.querySelector<HTMLInputElement>('input[aria-label="已选: Beta"]')!);
    await click(button(container, "批量复制指令"));
    expect(writeText).toHaveBeenLastCalledWith("/beta ");
    expect(container.querySelector("pre")?.textContent).toBe("Alpha codex full content");

    await click(button(container, "退出选择"));
    expect(container.querySelector('input[type="checkbox"]')).toBeNull();
    expect(container.querySelector('[data-vui="dense-toolbar"]')).toBeNull();
    await click(button(container, "批量选择"));
    expect(Array.from(container.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')).every((input) => !input.checked)).toBe(true);
    expect(container.textContent).not.toContain("批量复制指令");
    expect(detailFetch).not.toHaveBeenCalled();
  });

  it("selects visible rows and trims the selection after a source filter changes", async () => {
    const { container, writeText } = renderSkills();
    await click(button(container, "批量选择"));
    await click(button(container, "选择可见"));
    await click(button(container, "批量复制指令"));
    expect(writeText).toHaveBeenLastCalledWith("/alpha \n/beta \n/shared \n/shared ");

    const codexTab = Array.from(container.querySelectorAll<HTMLElement>('[role="tab"]')).find((tab) => tab.textContent === "Codex")!;
    await act(async () => {
      codexTab.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 }));
      codexTab.click();
    });
    expect(container.querySelectorAll('input[type="checkbox"]')).toHaveLength(2);
    expect(container.querySelector('input[aria-label="已选: Beta"]')).toBeNull();
    await click(button(container, "批量复制指令"));
    expect(writeText).toHaveBeenLastCalledWith("/alpha \n/shared ");
    await click(button(container, "清除选择"));
    expect(container.textContent).not.toContain("批量复制指令");
  });
});

describe("SkillsRoute same-command skills under different roots", () => {
  it("highlights, fetches and selects by (source, command) instead of the bare command", async () => {
    const { container, writeText } = renderSkills();
    const codexRow = skillRow(container, "Shared", "Codex");
    const agentsRow = skillRow(container, "Shared", "Agents 技能");

    // Reading mode: clicking the codex copy must press only that row and ask
    // the detail transport for the codex root, not whichever root wins
    // first-match on the server.
    await click(codexRow);
    expect(pressedSkillRows(container)).toHaveLength(1);
    expect(pressedSkillRows(container)[0]).toBe(codexRow);
    expect(agentsRow.getAttribute("aria-pressed")).toBe("false");
    await flushQueries();
    expect(container.querySelector("pre")?.textContent).toBe("Shared codex full content");
    expect(detailFetch).toHaveBeenCalledTimes(1);
    expect(detailFetch).toHaveBeenLastCalledWith("shared", "codex");

    // Switching to the agents copy must move the highlight and issue a second,
    // source-qualified request instead of reusing the codex cache entry.
    await click(agentsRow);
    expect(pressedSkillRows(container)).toHaveLength(1);
    expect(pressedSkillRows(container)[0]).toBe(agentsRow);
    expect(codexRow.getAttribute("aria-pressed")).toBe("false");
    await flushQueries();
    expect(container.querySelector("pre")?.textContent).toBe("Shared agents full content");
    expect(detailFetch).toHaveBeenCalledTimes(2);
    expect(detailFetch).toHaveBeenLastCalledWith("shared", "agents");

    // Going back is served from the per-source cache entry; no third request.
    await click(codexRow);
    await flushQueries();
    expect(container.querySelector("pre")?.textContent).toBe("Shared codex full content");
    expect(detailFetch).toHaveBeenCalledTimes(2);

    // Bulk mode: ticking one Shared row must not tick its same-command twin.
    await click(button(container, "批量选择"));
    const sharedChecks = Array.from(container.querySelectorAll<HTMLInputElement>('input[aria-label="已选: Shared"]'));
    expect(sharedChecks).toHaveLength(2);
    await click(sharedChecks[0]);
    expect(sharedChecks[0].checked).toBe(true);
    expect(sharedChecks[1].checked).toBe(false);
    expect(container.textContent).toContain("1 / 4");
    await click(button(container, "批量复制指令"));
    expect(writeText).toHaveBeenLastCalledWith("/shared ");

    await click(sharedChecks[1]);
    expect(sharedChecks[0].checked).toBe(true);
    expect(sharedChecks[1].checked).toBe(true);
    await click(sharedChecks[0]);
    expect(sharedChecks[0].checked).toBe(false);
    expect(sharedChecks[1].checked).toBe(true);
    await click(button(container, "批量复制指令"));
    expect(writeText).toHaveBeenLastCalledWith("/shared ");
  });
});
