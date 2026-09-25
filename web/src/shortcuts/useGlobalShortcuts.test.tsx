/** @vitest-environment happy-dom */
import { act, createElement, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { resolveEffectiveBindings } from "./commands";
import {
  isShortcutRecordingActive,
  matchesShortcutBinding,
  recordShortcutBinding,
  useGlobalShortcuts,
} from "./useGlobalShortcuts";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function keyEvent(init: Partial<KeyboardEvent> = {}): KeyboardEvent {
  return new KeyboardEvent("keydown", {
    key: "k",
    code: "KeyK",
    ctrlKey: true,
    metaKey: false,
    altKey: false,
    shiftKey: false,
    bubbles: true,
    cancelable: true,
    ...init,
  });
}

describe("matchesShortcutBinding", () => {
  const base = { key: "k", code: "KeyK", metaKey: false, ctrlKey: true, shiftKey: false, altKey: false };

  it("win 上 Ctrl+K 命中 CmdOrCtrl+k，Meta+K 不命中", () => {
    expect(matchesShortcutBinding(base, "CmdOrCtrl+k", false)).toBe(true);
    expect(matchesShortcutBinding({ ...base, ctrlKey: false, metaKey: true }, "CmdOrCtrl+k", false)).toBe(false);
  });

  it("mac 上 Meta+K 命中，Ctrl+K 不命中", () => {
    expect(matchesShortcutBinding({ ...base, ctrlKey: false, metaKey: true }, "CmdOrCtrl+k", true)).toBe(true);
    expect(matchesShortcutBinding(base, "CmdOrCtrl+k", true)).toBe(false);
  });

  it("修饰键精确匹配：多余 shift 不命中", () => {
    expect(matchesShortcutBinding({ ...base, shiftKey: true }, "CmdOrCtrl+k", false)).toBe(false);
  });

  it("event.key 大写与被布局改写的 key 都能命中（code 兜底）", () => {
    expect(matchesShortcutBinding({ ...base, key: "K" }, "CmdOrCtrl+k", false)).toBe(true);
    expect(matchesShortcutBinding({ ...base, key: "œ" }, "CmdOrCtrl+k", false)).toBe(true);
  });

  it("长按 repeat 与 IME 组合事件不命中", () => {
    expect(matchesShortcutBinding({ ...base, repeat: true }, "CmdOrCtrl+k", false)).toBe(false);
    expect(matchesShortcutBinding({ ...base, key: "Process", keyCode: 229 }, "CmdOrCtrl+k", false)).toBe(false);
  });

  it("裸键绑定要求主修饰键抬起", () => {
    const bare = { key: "Enter", code: "Enter", metaKey: false, ctrlKey: false, shiftKey: false, altKey: false };
    expect(matchesShortcutBinding(bare, "Enter", false)).toBe(true);
    expect(matchesShortcutBinding({ ...bare, ctrlKey: true }, "Enter", false)).toBe(false);
  });
});

/** 用 happy-dom + createRoot 挂一个只装全局快捷键 hook 的宿主组件。 */
function HookHost(props: {
  effective: ReturnType<typeof resolveEffectiveBindings>;
  onCommand: (commandId: Parameters<Parameters<typeof useGlobalShortcuts>[0]["onCommand"]>[0], binding: string) => void;
}): { root: Root; container: HTMLElement } {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  function Host() {
    useGlobalShortcuts({
      effective: props.effective,
      isApple: false,
      recording: false,
      onCommand: props.onCommand,
      onRecord: () => undefined,
    });
    return null;
  }
  act(() => {
    root.render(createElement(Host));
  });
  return { root, container };
}

function unmountHost(host: { root: Root; container: HTMLElement }): void {
  act(() => {
    host.root.unmount();
  });
  host.container.remove();
}

describe("recordShortcutBinding（录制器，迁移自 preview logic-selftest）", () => {
  const bare = { metaKey: false, ctrlKey: false, shiftKey: false, altKey: false };

  it("纯修饰键按下返回 pending，等待完整组合", () => {
    expect(
      recordShortcutBinding({ key: "Control", code: "ControlLeft", ...bare, ctrlKey: true }, false),
    ).toEqual({ kind: "pending" });
  });

  it("win 上 Ctrl+J 录制为 CmdOrCtrl+j（平台归一）", () => {
    expect(
      recordShortcutBinding({ key: "j", code: "KeyJ", ...bare, ctrlKey: true }, false),
    ).toEqual({ kind: "binding", binding: "CmdOrCtrl+j" });
  });

  it("Shift+7 用 event.code 反查物理基键（布局无关）", () => {
    expect(
      recordShortcutBinding({ key: "&", code: "Digit7", ...bare, shiftKey: true }, false),
    ).toEqual({ kind: "binding", binding: "Shift+7" });
  });

  it("无修饰键的普通字符键拒绝（no-modifier）", () => {
    expect(recordShortcutBinding({ key: "g", code: "KeyG", ...bare }, false)).toEqual({
      kind: "invalid",
      reason: "no-modifier",
    });
  });

  it("win 上纯 Win 键组合拒绝：归一后主修饰键丢失，防裸键落盘", () => {
    expect(
      recordShortcutBinding({ key: "j", code: "KeyJ", ...bare, metaKey: true }, false).kind,
    ).toBe("invalid");
  });
});

describe("useGlobalShortcuts 分发（window capture 集成 smoke）", () => {
  const effective = resolveEffectiveBindings();

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("Ctrl+K 分发 openCommandPalette 并 preventDefault", () => {
    const onCommand = vi.fn();
    const host = HookHost({ effective, onCommand });
    try {
      const event = keyEvent();
      act(() => {
        window.dispatchEvent(event);
      });
      expect(onCommand).toHaveBeenCalledWith("openCommandPalette", "CmdOrCtrl+k");
      expect(event.defaultPrevented).toBe(true);
    } finally {
      unmountHost(host);
    }
  });

  it("Ctrl+P 分发 openSessionSearch", () => {
    const onCommand = vi.fn();
    const host = HookHost({ effective, onCommand });
    try {
      act(() => {
        window.dispatchEvent(keyEvent({ key: "p", code: "KeyP" }));
      });
      expect(onCommand).toHaveBeenCalledWith("openSessionSearch", "CmdOrCtrl+p");
    } finally {
      unmountHost(host);
    }
  });

  it("stopPropagation：路由级 bubble 监听不再收到命中的组合", () => {
    const onCommand = vi.fn();
    const bubbleListener = vi.fn();
    window.addEventListener("keydown", bubbleListener);
    const host = HookHost({ effective, onCommand });
    try {
      act(() => {
        window.dispatchEvent(keyEvent());
      });
      expect(onCommand).toHaveBeenCalled();
      expect(bubbleListener).not.toHaveBeenCalled();
    } finally {
      unmountHost(host);
      window.removeEventListener("keydown", bubbleListener);
    }
  });

  it("清除覆盖（空生效表）后组合不分发", () => {
    const onCommand = vi.fn();
    const cleared = resolveEffectiveBindings({ openCommandPalette: [], openSessionSearch: [] });
    const host = HookHost({ effective: cleared, onCommand });
    try {
      act(() => {
        window.dispatchEvent(keyEvent());
      });
      expect(onCommand).not.toHaveBeenCalled();
    } finally {
      unmountHost(host);
    }
  });

  it("覆盖改键后按新组合分发（整组替换语义）", () => {
    const onCommand = vi.fn();
    const rebound = resolveEffectiveBindings({ openCommandPalette: ["Ctrl+Alt+k"] });
    const host = HookHost({ effective: rebound, onCommand });
    try {
      act(() => {
        window.dispatchEvent(keyEvent());
      });
      expect(onCommand).not.toHaveBeenCalled();
      act(() => {
        window.dispatchEvent(keyEvent({ altKey: true }));
      });
      expect(onCommand).toHaveBeenCalledWith("openCommandPalette", "Ctrl+Alt+k");
    } finally {
      unmountHost(host);
    }
  });
});

/** 受控状态宿主：模拟 App 壳层用 onCommand 切 React state 开面板。 */
function StateHost(props: {
  effective: ReturnType<typeof resolveEffectiveBindings>;
}): { opened: () => boolean; container: HTMLElement; root: Root } {
  let opened = false;
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  function Host() {
    const [open, setOpen] = useState(false);
    opened = open;
    useGlobalShortcuts({
      effective: props.effective,
      isApple: false,
      recording: false,
      onCommand: (commandId) => {
        if (commandId === "openCommandPalette") {
          setOpen((current) => !current);
        }
      },
      onRecord: () => undefined,
    });
    return createElement("div", { "data-open": open ? "true" : "false" });
  }
  act(() => {
    root.render(createElement(Host));
  });
  return {
    opened: () => opened,
    container,
    root,
  };
}

describe("useGlobalShortcuts 状态接线 smoke", () => {
  it("两次 Ctrl+K 切换打开/关闭（全局 toggle 语义）", () => {
    const host = StateHost({ effective: resolveEffectiveBindings() });
    try {
      expect(host.opened()).toBe(false);
      act(() => {
        window.dispatchEvent(keyEvent());
      });
      expect(host.opened()).toBe(true);
      act(() => {
        window.dispatchEvent(keyEvent());
      });
      expect(host.opened()).toBe(false);
    } finally {
      unmountHost(host);
    }
  });
});

/** 录制宿主：recording=true 的 hook 实例（模拟设置页改键面板录制态）。 */
function RecorderHost(props: {
  effective: ReturnType<typeof resolveEffectiveBindings>;
  onRecord: (outcome: { kind: string; binding?: string }) => void;
  enabled?: boolean;
}): { root: Root; container: HTMLElement } {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  function Host() {
    useGlobalShortcuts({
      effective: props.effective,
      isApple: false,
      recording: true,
      enabled: props.enabled,
      onCommand: () => undefined,
      onRecord: props.onRecord as never,
    });
    return null;
  }
  act(() => {
    root.render(createElement(Host));
  });
  return { root, container };
}

describe("useGlobalShortcuts 录制门与 enabled（跨实例协调）", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("其他实例录制时分发让路，录制实例收到按键", () => {
    const onCommand = vi.fn();
    const onRecord = vi.fn();
    const dispatcher = HookHost({ effective: resolveEffectiveBindings(), onCommand });
    const recorder = RecorderHost({ effective: resolveEffectiveBindings(), onRecord });
    try {
      expect(isShortcutRecordingActive()).toBe(true);
      act(() => {
        window.dispatchEvent(keyEvent({ key: "j", code: "KeyJ" }));
      });
      expect(onRecord).toHaveBeenCalledWith({ kind: "binding", binding: "CmdOrCtrl+j" });
      expect(onCommand).not.toHaveBeenCalled();
    } finally {
      unmountHost(recorder);
    }
    expect(isShortcutRecordingActive()).toBe(false);
    act(() => {
      window.dispatchEvent(keyEvent());
    });
    expect(onCommand).toHaveBeenCalledWith("openCommandPalette", "CmdOrCtrl+k");
    unmountHost(dispatcher);
  });

  it("enabled=false 时不挂监听，按键不分发", () => {
    const onCommand = vi.fn();
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    function Host() {
      useGlobalShortcuts({
        effective: resolveEffectiveBindings(),
        isApple: false,
        recording: false,
        enabled: false,
        onCommand,
        onRecord: () => undefined,
      });
      return null;
    }
    try {
      act(() => {
        root.render(createElement(Host));
      });
      act(() => {
        window.dispatchEvent(keyEvent());
      });
      expect(onCommand).not.toHaveBeenCalled();
    } finally {
      act(() => {
        root.unmount();
      });
      container.remove();
    }
  });
});
