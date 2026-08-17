/** @vitest-environment happy-dom */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { VuiProvider } from "../components/vui";
import { ChatComposerPlusMenuPreviewApp } from "./chat-composer-plus-menu-preview";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function buttonByLabel(label: string): HTMLButtonElement | null {
  return document.body.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`);
}

function buttonByText(text: string): HTMLButtonElement | null {
  return (
    Array.from(document.body.querySelectorAll("button")).find(
      (button) => button.textContent?.trim() === text,
    ) ?? null
  );
}

function setInputValue(element: HTMLInputElement | HTMLTextAreaElement, value: string) {
  const proto = Object.getOwnPropertyDescriptor(
    element instanceof HTMLTextAreaElement
      ? window.HTMLTextAreaElement.prototype
      : window.HTMLInputElement.prototype,
    "value",
  );
  proto?.set?.call(element, value);
  element.dispatchEvent(new Event("input", { bubbles: true }));
}

function composerToolbar(host: ParentNode) {
  return host.querySelector(".plus-menu-preview-composer-toolbar");
}

function toolbarHasRuntimeStatusButton(host: ParentNode) {
  const toolbar = composerToolbar(host);
  if (!toolbar) {
    return false;
  }
  return Array.from(toolbar.querySelectorAll("button")).some((button) =>
    (button.getAttribute("aria-label") ?? button.textContent ?? "").includes("运行状态"),
  );
}

describe("chat composer plus menu preview shell contract", () => {
  it("keeps the product Tailwind utility entry in the overlay import chain", () => {
    const previewSource = readFileSync(
      resolve(import.meta.dirname, "chat-composer-plus-menu-preview.tsx"),
      "utf8",
    );
    const tokenIndex = previewSource.indexOf('"./tokens.css"');
    const tailwindIndex = previewSource.indexOf('"./tailwind.css"');
    const providerThemeIndex = previewSource.indexOf('"./vui-provider-theme.css"');
    const nativeControlsIndex = previewSource.indexOf('"./vui-native-controls.css"');
    expect(tokenIndex).toBeGreaterThan(-1);
    expect(tailwindIndex).toBeGreaterThan(-1);
    expect(providerThemeIndex).toBeGreaterThan(-1);
    expect(nativeControlsIndex).toBeGreaterThan(-1);
    expect(tailwindIndex).toBeGreaterThan(tokenIndex);
    expect(providerThemeIndex).toBeGreaterThan(tailwindIndex);
    expect(nativeControlsIndex).toBeGreaterThan(providerThemeIndex);
  });

  it("keeps user-visible terminology free of Skill across the preview sources", () => {
    const forbidden = new RegExp("Sk" + "ill", "i");
    for (const file of [
      "chat-composer-plus-menu-preview.tsx",
      "chat-composer-plus-menu-preview.css",
      "chat-composer-plus-menu-preview.styles.ts",
    ]) {
      const source = readFileSync(resolve(import.meta.dirname, file), "utf8");
      expect(source).not.toMatch(forbidden);
    }
  });
});

describe("chat composer plus menu preview loop", () => {
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
  });

  async function mountPreview() {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(
        <VuiProvider>
          <ChatComposerPlusMenuPreviewApp />
        </VuiProvider>,
      );
    });
    return container;
  }

  it("does not render the removed operation-history pill strip", async () => {
    const host = await mountPreview();
    expect(host.querySelector('[aria-label="最近操作"]')).toBeNull();
    expect(host.querySelector(".plus-menu-preview-log-strip")).toBeNull();
  });

  it("does not expose a standalone runtime-status control in the composer toolbar", async () => {
    const host = await mountPreview();
    expect(toolbarHasRuntimeStatusButton(host)).toBe(false);
    expect(host.querySelector(".plus-menu-preview-status-trigger")).toBeNull();
    expect(document.body.querySelector('[aria-label="快速运行状态"]')).toBeNull();
  });

  it("does not render the narrow preview toggle button", async () => {
    await mountPreview();
    expect(buttonByText("窄屏预览")).toBeNull();
  });

  it("shows two-level conversation-capabilities toggles without a third menu level", async () => {
    const host = await mountPreview();

    expect(toolbarHasRuntimeStatusButton(host)).toBe(false);

    await act(async () => {
      buttonByLabel("更多操作")?.click();
    });

    const menu = document.body.querySelector('[role="menu"][aria-label="更多操作菜单"]');
    expect(menu).toBeTruthy();
    const panel = document.body.querySelector('[data-vui="popover"]');
    expect(panel?.className).toContain("plus-menu-preview-plus-menu");

    const clusterLabels = ["添加与引用", "对话能力", "会话与陪伴"];
    for (const label of clusterLabels) {
      expect(buttonByLabel(label)).toBeTruthy();
    }

    const menuText = menu?.textContent ?? "";
    expect(menuText).not.toContain("输入辅助");
    expect(menuText).not.toContain("斜杠指令");
    expect(menuText).not.toContain("图片附件");
    expect(menuText).not.toContain("引用会话");
    expect(menuText).not.toContain("运行状态 2/2");
    expect(menuText).not.toContain("运行状态 1/2");
    expect(menuText).not.toContain("运行状态 0/2");
    expect(menuText).not.toContain("上下文/缓存详情");
    expect(menuText).not.toMatch(/Skill/i);

    await act(async () => {
      buttonByLabel("对话能力")?.click();
    });

    const submenu = document.body.querySelector('[role="group"][aria-label="对话能力"]');
    expect(submenu).toBeTruthy();
    expect(submenu?.textContent).toContain("心智模型");
    expect(submenu?.textContent).toContain("运行状态注入");
    expect(submenu?.textContent).not.toContain("查看并切换运行开关");
    expect(submenu?.textContent).not.toContain("斜杠指令");
    expect(document.body.querySelector(".plus-menu-preview-menu-tertiary-flyout")).toBeNull();
    expect(document.body.querySelectorAll('[role="group"]').length).toBe(1);

    const mental = buttonByLabel("心智模型：开启");
    expect(mental?.getAttribute("aria-checked")).toBe("true");
    expect(buttonByLabel("运行状态注入：开启")?.getAttribute("aria-checked")).toBe("true");

    await act(async () => {
      mental?.click();
    });
    expect(buttonByLabel("心智模型：关闭")?.getAttribute("aria-checked")).toBe("false");

    await act(async () => {
      buttonByLabel("运行状态注入：开启")?.click();
    });
    expect(buttonByLabel("运行状态注入：关闭")?.getAttribute("aria-checked")).toBe("false");
    expect(toolbarHasRuntimeStatusButton(host)).toBe(false);

    await act(async () => {
      document.body.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    });
    expect(document.body.querySelector('[role="menu"]')).toBeNull();
  });

  it("keeps desktop flyout panels without drill-in back navigation or tertiary groups", async () => {
    await mountPreview();

    await act(async () => {
      buttonByLabel("更多操作")?.click();
    });
    expect(buttonByLabel("返回上一级菜单")).toBeNull();
    expect(document.body.querySelector(".plus-menu-preview-menu-tertiary-flyout")).toBeNull();

    await act(async () => {
      buttonByLabel("添加与引用")?.click();
    });
    expect(buttonByLabel("返回上一级菜单")).toBeNull();
    const submenu = document.body.querySelector('[role="group"][aria-label="添加与引用"]');
    expect(submenu).toBeTruthy();
    expect(submenu?.textContent).toContain("图片附件");
    expect(document.body.querySelector(".plus-menu-preview-plus-menu-primary")).toBeTruthy();
    expect(document.body.querySelectorAll('[role="group"]').length).toBe(1);
  });

  it("omits the removed mental-runtime rail section while keeping other read-only rail content", async () => {
    const host = await mountPreview();

    await act(async () => {
      buttonByText("状态栏")?.click();
    });

    const rail = host.querySelector('[aria-label="状态栏（只读）"]');
    expect(rail).toBeTruthy();
    expect(rail?.querySelector('[aria-label="心智与运行（只读）"]')).toBeNull();
    expect(rail?.textContent).not.toContain("心智与运行 · 下轮生效");
    expect(rail?.textContent).not.toContain("认知状态稳定，注意力集中在当前会话目标。");
    expect(rail?.querySelector('[aria-label="上下文与缓存（只读）"]')).toBeTruthy();
    expect(rail?.textContent).toContain("上下文与缓存");
    expect(rail?.querySelector('[aria-label="当前会话（只读）"]')).toBeTruthy();
    expect(rail?.textContent).toContain("Relay GPT-5.6 Luna");

    await act(async () => {
      buttonByLabel("更多操作")?.click();
    });
    await act(async () => {
      buttonByLabel("对话能力")?.click();
    });
    await act(async () => {
      buttonByLabel("心智模型：开启")?.click();
    });
    expect(buttonByLabel("心智模型：关闭")?.getAttribute("aria-checked")).toBe("false");
    await act(async () => {
      buttonByLabel("运行状态注入：开启")?.click();
    });
    expect(buttonByLabel("运行状态注入：关闭")?.getAttribute("aria-checked")).toBe("false");
    expect(toolbarHasRuntimeStatusButton(host)).toBe(false);
  });

  it("keeps model/permission/context/send controls outside the plus menu", async () => {
    const host = await mountPreview();

    await act(async () => {
      buttonByLabel("更多操作")?.click();
    });
    await act(async () => {
      buttonByLabel("对话能力")?.click();
    });
    const menuText = document.body.querySelector('[role="menu"]')?.textContent ?? "";
    expect(menuText).not.toContain("Relay GPT-5.6 Luna");
    expect(menuText).not.toContain("标准读写");
    expect(menuText).not.toContain("上下文 42%");
    expect(menuText).not.toContain("上下文/缓存详情");
    expect(menuText).not.toContain("运行状态 2/2");

    expect(host.querySelector('button[aria-label="模型：Relay GPT-5.6 Luna"]')).toBeTruthy();
    expect(host.querySelector('button[aria-label="权限预设：标准读写"]')).toBeTruthy();
    expect(host.querySelector('button[aria-label="上下文占用 42%，命中 67%"]')).toBeTruthy();
    expect(host.querySelector('textarea[aria-label="发送消息"]')).toBeTruthy();
    expect(Array.from(host.querySelectorAll("button")).some((button) => button.textContent === "停止")).toBe(true);
  });

  it("adds and removes session and workspace-file references through searchable pickers", async () => {
    const host = await mountPreview();

    await act(async () => {
      buttonByLabel("更多操作")?.click();
    });
    await act(async () => {
      buttonByLabel("添加与引用")?.click();
    });
    await act(async () => {
      buttonByLabel("引用会话")?.click();
    });
    let dialog = document.body.querySelector('[role="dialog"]');
    expect(dialog?.textContent).toContain("引用会话");
    expect(dialog?.querySelector('[role="listbox"]')).toBeTruthy();
    let search = dialog?.querySelector<HTMLInputElement>('input[aria-label="搜索会话"]');
    expect(search).toBeTruthy();
    expect(dialog?.textContent).toContain("代码审查 · 今天");
    expect(dialog?.textContent).toContain("资料提炼 · 08/08");

    await act(async () => {
      setInputValue(search!, "审查");
    });
    expect(dialog?.textContent).toContain("代码审查 · 今天");
    expect(dialog?.textContent).not.toContain("资料提炼 · 08/08");

    await act(async () => {
      setInputValue(search!, "不存在的内容");
    });
    expect(dialog?.textContent).toContain("没有匹配的会话。");
    expect(buttonByLabel("代码审查 · 今天")).toBeNull();

    await act(async () => {
      setInputValue(search!, "");
    });
    await act(async () => {
      buttonByLabel("代码审查 · 今天")?.click();
    });
    expect(document.body.querySelector('[role="dialog"]')).toBeNull();
    expect(host.textContent).toContain("已引用会话：代码审查 · 今天");
    let refRow = host.querySelector('[aria-label="待发送引用"]');
    expect(refRow?.textContent).toContain("会话");
    expect(refRow?.textContent).toContain("代码审查 · 今天");

    await act(async () => {
      buttonByLabel("更多操作")?.click();
    });
    await act(async () => {
      buttonByLabel("添加与引用")?.click();
    });
    await act(async () => {
      buttonByLabel("引用会话")?.click();
    });
    dialog = document.body.querySelector('[role="dialog"]');
    expect(dialog?.querySelector<HTMLInputElement>('input[aria-label="搜索会话"]')?.value).toBe("");
    await act(async () => {
      buttonByLabel("代码审查 · 今天")?.click();
    });
    expect(document.body.querySelector('[role="dialog"]')).toBeNull();
    expect(host.textContent).toContain("已在引用中，未重复添加");
    expect(host.querySelectorAll('button[aria-label^="移除引用"]').length).toBe(1);

    await act(async () => {
      buttonByLabel("更多操作")?.click();
    });
    await act(async () => {
      buttonByLabel("添加与引用")?.click();
    });
    await act(async () => {
      buttonByLabel("引用工作区文件")?.click();
    });
    dialog = document.body.querySelector('[role="dialog"]');
    expect(dialog?.textContent).toContain("引用工作区文件");
    const fileSearch = dialog?.querySelector<HTMLInputElement>('input[aria-label="搜索工作区文件"]');
    expect(fileSearch).toBeTruthy();
    expect(dialog?.textContent).toContain("src/login/LoginPage.tsx");
    expect(dialog?.textContent).toContain("src/design/tokens.css");

    await act(async () => {
      setInputValue(fileSearch!, "tokens");
    });
    expect(dialog?.textContent).toContain("src/design/tokens.css");
    expect(dialog?.textContent).not.toContain("src/login/LoginPage.tsx");

    await act(async () => {
      setInputValue(fileSearch!, "");
    });
    await act(async () => {
      buttonByLabel("src/login/LoginPage.tsx")?.click();
    });
    expect(document.body.querySelector('[role="dialog"]')).toBeNull();
    refRow = host.querySelector('[aria-label="待发送引用"]');
    expect(refRow?.textContent).toContain("文件");
    expect(refRow?.textContent).toContain("src/login/LoginPage.tsx");

    const removeButtons = host.querySelectorAll('button[aria-label^="移除引用"]');
    expect(removeButtons.length).toBe(2);
    await act(async () => {
      removeButtons[0]?.click();
    });
    const refRowAfterRemove = host.querySelector('[aria-label="待发送引用"]');
    expect(refRowAfterRemove?.textContent).toContain("src/login/LoginPage.tsx");
    expect(refRowAfterRemove?.textContent).not.toContain("代码审查 · 今天");
  });

  it("opens the inline slash palette from composer typing and never from the plus menu", async () => {
    const host = await mountPreview();
    const textarea = host.querySelector<HTMLTextAreaElement>('textarea[aria-label="发送消息"]');
    expect(textarea).toBeTruthy();

    await act(async () => {
      buttonByLabel("更多操作")?.click();
    });
    expect(document.body.querySelector('[role="menu"]')?.textContent).not.toContain("斜杠指令");

    await act(async () => {
      document.body.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    });

    await act(async () => {
      setInputValue(textarea!, "/");
    });
    let palette = host.querySelector('[role="listbox"][aria-label="斜杠指令"]');
    expect(palette).toBeTruthy();
    expect(palette?.textContent).toContain("review");
    expect(palette?.textContent).toContain("test");

    await act(async () => {
      setInputValue(textarea!, "/zzzz");
    });
    palette = host.querySelector('[role="listbox"][aria-label="斜杠指令"]');
    expect(palette?.textContent).toContain("没有匹配的指令。");

    await act(async () => {
      setInputValue(textarea!, "/te");
    });
    palette = host.querySelector('[role="listbox"][aria-label="斜杠指令"]');
    expect(palette?.textContent).toContain("test");
    expect(palette?.textContent).not.toContain("review");

    await act(async () => {
      buttonByLabel("/test")?.click();
    });
    expect(textarea?.value).toBe("/test ");
    expect(host.textContent).toContain("已插入斜杠指令：/test");
    expect(host.querySelector('[role="listbox"][aria-label="斜杠指令"]')).toBeNull();

    await act(async () => {
      setInputValue(textarea!, "prefix /te");
    });
    expect(host.querySelector('[role="listbox"][aria-label="斜杠指令"]')).toBeTruthy();

    await act(async () => {
      textarea?.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    });
    expect(host.querySelector('[role="listbox"][aria-label="斜杠指令"]')).toBeNull();
  });

  it("group scene exposes four clusters, desktop flyout second level, and confirms destructive management", async () => {
    const host = await mountPreview();

    await act(async () => {
      buttonByText("群聊会话")?.click();
    });
    expect(host.textContent).toContain("产品周会 · 团队讨论");
    expect(toolbarHasRuntimeStatusButton(host)).toBe(false);
    expect(Array.from(host.querySelectorAll("button")).some((button) => button.textContent === "发送")).toBe(true);

    await act(async () => {
      buttonByLabel("更多操作")?.click();
    });
    const menu = document.body.querySelector('[role="menu"][aria-label="更多操作菜单"]');
    expect(menu?.textContent).toContain("添加与引用");
    expect(menu?.textContent).toContain("对话能力");
    expect(menu?.textContent).toContain("会话与陪伴");
    expect(menu?.textContent).toContain("群聊与团队");
    expect(menu?.textContent).not.toContain("管理群聊");
    expect(menu?.textContent).not.toContain("打开团队");

    await act(async () => {
      buttonByLabel("群聊与团队")?.click();
    });
    const groupSubmenu = document.body.querySelector('[role="group"][aria-label="群聊与团队"]');
    expect(groupSubmenu?.textContent).toContain("管理群聊");
    expect(groupSubmenu?.textContent).toContain("打开团队");
    expect(buttonByLabel("返回上一级菜单")).toBeNull();

    await act(async () => {
      buttonByLabel("管理群聊")?.click();
    });
    const groupDialog = document.body.querySelector('[role="dialog"]');
    expect(groupDialog).toBeTruthy();
    expect(groupDialog?.textContent).toContain("群聊管理");
    expect(groupDialog?.textContent).toContain("round_robin");

    await act(async () => {
      buttonByText("重置消息")?.click();
    });
    const resetConfirm = document.body.querySelector('[role="dialog"]');
    expect(resetConfirm?.textContent).toContain("重置群聊消息？");
    await act(async () => {
      buttonByText("确认重置")?.click();
    });
    expect(host.textContent).toContain("已重置群聊消息（模拟完成）");

    await act(async () => {
      buttonByLabel("更多操作")?.click();
    });
    await act(async () => {
      buttonByLabel("群聊与团队")?.click();
    });
    await act(async () => {
      buttonByLabel("管理群聊")?.click();
    });
    await act(async () => {
      buttonByText("删除群聊")?.click();
    });
    const deleteConfirm = document.body.querySelector('[role="dialog"]');
    expect(deleteConfirm?.textContent).toContain("删除群聊？");
    await act(async () => {
      buttonByText("确认删除")?.click();
    });
    expect(host.textContent).toContain("已删除群聊（模拟完成）");
  });
});
