// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  AgentPermissionPresetControl,
  agentPermissionPresetOptions,
} from "./AgentPermissionPresetControl";
import controlSource from "./AgentPermissionPresetControl.tsx?raw";

let root: Root | undefined;
let container: HTMLDivElement;
afterEach(async () => { await act(async () => root?.unmount()); root = undefined; container?.remove(); vi.unstubAllGlobals(); });

describe("AgentPermissionPresetControl", () => {
  it("uses Launcher-only descriptions without changing the default Agent wording", () => {
    const defaults = agentPermissionPresetOptions("zh");
    expect(defaults[2].description).toContain("此电脑上的文件");
    const launcher = agentPermissionPresetOptions("zh", "launcher");
    expect(launcher.map(option => option.value)).toEqual(defaults.map(option => option.value));
    expect(launcher[0].description).toContain("创建团队");
    expect(launcher[1].description).toContain("高风险操作仍需确认");
    expect(launcher[2].description).toContain("不会扩大访问范围");
    const html = renderToStaticMarkup(<AgentPermissionPresetControl value={null} context="launcher" lang="zh"
      surface="composer" disabled pending={false} onChange={() => undefined} />);
    expect(html).toContain("权限暂不可用");
    expect(html).not.toContain('data-preset="request_approval"');
    expect(html).not.toContain('data-preset="auto_review"');
  });

  it("opens upward from the left and navigates all presets with the keyboard", async () => {
    vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
    const onChange = vi.fn();
    container = document.createElement("div"); document.body.append(container); root = createRoot(container);
    await act(async () => root!.render(<AgentPermissionPresetControl value="request_approval" context="launcher"
      lang="zh" surface="composer" side="top" align="start" disabled={false} pending={false} onChange={onChange} />));
    const trigger = container.querySelector<HTMLButtonElement>("button")!;
    await act(async () => trigger.click());
    const menu = document.querySelector<HTMLElement>('[data-testid="agent-permission-preset-menu"]')!;
    const floating = menu.closest('[data-vui="agent-permission-preset-menu"]')!;
    expect(floating.getAttribute("data-side")).toBe("top");
    expect(floating.getAttribute("data-align")).toBe("start");
    expect(menu.textContent).toContain("仅 Launcher 助理");
    const items = [...menu.querySelectorAll<HTMLButtonElement>('[role="option"]')];
    const key = async (value: string) => act(async () => {
      document.activeElement?.dispatchEvent(new KeyboardEvent("keydown", { key: value, bubbles: true }));
    });
    items[0].focus();
    await key("ArrowDown"); expect(document.activeElement).toBe(items[1]);
    await key("End"); expect(document.activeElement).toBe(items[2]);
    await key("ArrowDown"); expect(document.activeElement).toBe(items[0]);
    await key("ArrowUp"); expect(document.activeElement).toBe(items[2]);
    await key("Home"); expect(document.activeElement).toBe(items[0]);
    await act(async () => items[1].click());
    expect(onChange).toHaveBeenCalledExactlyOnceWith("auto_review");
    expect(document.querySelector('[data-testid="agent-permission-preset-menu"]')).toBeNull();
  });
  it("exposes exactly the three Agent-owned permission presets", () => {
    expect(agentPermissionPresetOptions("zh").map((option) => option.value)).toEqual([
      "request_approval",
      "auto_review",
      "full_access",
    ]);
    expect(agentPermissionPresetOptions("zh").map((option) => option.label)).toEqual([
      "请求批准",
      "替我审批",
      "完全访问权限",
    ]);
    expect(agentPermissionPresetOptions("zh")).toHaveLength(3);
  });

  it("renders a compact Codex-style trigger without a custom mode", () => {
    const html = renderToStaticMarkup(
      <AgentPermissionPresetControl
        value="full_access"
        lang="zh"
        surface="composer"
        disabled={false}
        pending={false}
        onChange={() => undefined}
      />,
    );

    expect(html).toContain("完全访问权限");
    expect(html).toContain('aria-haspopup="listbox"');
    expect(html).toContain('data-surface="composer"');
    expect(html).not.toContain("自定义");
    expect(html).not.toContain("config.toml");
  });

  it("hosts the permission menu on VPopover instead of a hand-placed portal", () => {
    expect(controlSource).toContain("<VPopover");
    expect(controlSource).toContain('data-vui="agent-permission-preset-menu"');
    expect(controlSource).toContain("contentClassName={styles.menu}");
    expect(controlSource).not.toContain("createPortal(");
    expect(controlSource).not.toContain("placePermissionMenu");
  });
});
