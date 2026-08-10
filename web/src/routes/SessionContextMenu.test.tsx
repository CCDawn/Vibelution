import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import sessionContextMenuStyles from "./SessionContextMenu.styles";
import { sessionContextMenuStyle } from "./SessionContextMenu";

const menuSource = readFileSync(resolve(import.meta.dirname, "SessionContextMenu.tsx"), "utf8");

describe("SessionContextMenu", () => {
  it("offers session actions through VDropdownMenu without agent-only items", () => {
    expect(menuSource).toContain("VDropdownMenu");
    expect(menuSource).toContain('aria-label={lang === "zh" ? "会话操作" : "Session actions"}');
    expect(menuSource).toContain('id: "add-to-review"');
    expect(menuSource).toContain('id: "rename"');
    expect(menuSource).toContain('id: "delete"');
    expect(menuSource).toContain('t("addSessionToReview")');
    expect(menuSource).toContain('t("renameSession")');
    expect(menuSource).toContain('t("deleteSession")');
    expect(menuSource).not.toContain('role="menuitem"');
  });

  it("shows the Agent configuration action for Agent-backed sessions", () => {
    expect(menuSource).toContain("session.agentId && onOpenAgentConfig");
    expect(menuSource).toContain('id: "open-agent-config"');
    expect(menuSource).toContain('lang === "zh" ? "打开 Agent 配置" : "Open Agent config"');
    expect(menuSource).toContain('t("clearSessionHistory")');
    expect(menuSource).not.toContain('role="menuitem"');
  });

  it("wires pending labels and busy aria for async actions", () => {
    expect(menuSource).toContain("const busy = addToReviewPending || clearHistoryPending");
    expect(menuSource).toContain('"aria-busy": busy ? "true" : undefined');
    expect(menuSource).toContain("addToReviewDisabled");
    expect(menuSource).toContain("clearHistoryDisabled");
    expect(menuSource).toContain("deleteDisabled");
    expect(menuSource).toContain('t("addingSessionToReview")');
    expect(menuSource).toContain('t("clearingSessionHistory")');
  });

  it("clamps the menu inside the visible viewport", () => {
    expect(sessionContextMenuStyle({ x: 900, y: 700 }, { width: 960, height: 720 })).toEqual({
      left: 772,
      top: 516,
    });
    expect(sessionContextMenuStyle({ x: 24, y: 32 }, undefined)).toEqual({
      left: 24,
      top: 32,
    });
  });

  it("renders as a floating overlay instead of a document-flow action block", () => {
    expect(menuSource).toContain("position={position}");
    expect(menuSource).toContain("contentClassName={styles.sessionContextMenu}");
    expect(menuSource).toContain("itemClassName={styles.sessionContextMenuItem}");
    expect(menuSource).toContain("dangerItemClassName={styles.sessionContextMenuDanger}");
    expect(sessionContextMenuStyles.sessionContextMenu).toContain("z-[80]");
    expect(sessionContextMenuStyles.sessionContextMenu).toContain("w-[188px]");
    expect(sessionContextMenuStyles.sessionContextMenuItem).toContain("!w-full");
    expect(sessionContextMenuStyles.sessionContextMenuItem).toContain("justify-start");
    expect(sessionContextMenuStyles.sessionContextMenuDanger).toContain("var(--state-error)");
    expect(sessionContextMenuStyles.sessionContextMenuDanger).not.toContain("accent-warm");
  });
});
