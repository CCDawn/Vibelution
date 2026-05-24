import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import configRouteSource from "./src/routes/ConfigRoute.tsx?raw";

const configRouteCss = readFileSync(new URL("./src/routes/ConfigRoute.module.css", import.meta.url), "utf-8");

function cssRule(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return configRouteCss.match(new RegExp(`${escaped}\\s*\\{[^}]*\\}`, "s"))?.[0] ?? "";
}

function cssBetween(start: string, end: string): string {
  const startIndex = configRouteCss.indexOf(start);
  const endIndex = end ? configRouteCss.indexOf(end, startIndex + start.length) : -1;
  if (startIndex < 0) {
    return "";
  }
  return configRouteCss.slice(startIndex, endIndex < 0 ? undefined : endIndex);
}

describe("ConfigRoute layout density contract", () => {
  it("uses separate compact view and edit field card classes", () => {
    expect(configRouteSource).toContain("styles.treeFieldCardView");
    expect(configRouteSource).toContain("styles.treeFieldCardEdit");
  });

  it("keeps read-only config fields in dense label-value rows on wide screens", () => {
    const treeGrid = cssRule(".treeGrid");
    const viewCard = cssRule(".treeFieldCardView");
    const overviewGrid = cssRule(".hashGrid");

    expect(overviewGrid).toContain("minmax(360px, 1.6fr) minmax(180px, 0.7fr)");
    expect(treeGrid).toContain("repeat(auto-fit, minmax(230px, 1fr))");
    expect(viewCard).toContain("grid-template-columns: minmax(108px, 0.42fr) minmax(0, 1fr)");
    expect(viewCard).toContain("min-height: 40px");
  });

  it("does not collapse the config tree to one column until phone width", () => {
    const tabletRules = cssBetween("@media (max-width: 1120px)", "@media (max-width: 720px)");
    const phoneRules = cssBetween("@media (max-width: 720px)", "");

    expect(tabletRules).toContain("repeat(auto-fit, minmax(210px, 1fr))");
    expect(tabletRules).not.toMatch(/\.treeGrid\s*{[^}]*grid-template-columns:\s*1fr/s);
    expect(phoneRules).toMatch(/\.treeGrid\s*{[^}]*grid-template-columns:\s*1fr/s);
  });
});

describe("ConfigRoute content experience contract", () => {
  it("frames the overview as save/apply status instead of an internal config source", () => {
    expect(configRouteSource).toContain('sourceTitle: "保存与生效"');
    expect(configRouteSource).toContain('sourceBody: "这里显示当前修改是否已经保存，以及哪些系统级设置需要重启后才会生效。"');
    expect(configRouteSource).not.toContain('sourceTitle: "配置源"');
  });

  it("keeps low-value field-type badges out of read-only config cards", () => {
    const viewStart = configRouteSource.indexOf("function renderFieldView");
    const editStart = configRouteSource.indexOf("function renderFieldEditor");
    const renderFieldViewSource = configRouteSource.slice(viewStart, editStart);

    expect(renderFieldViewSource).toContain("styles.treeFieldCardView");
    expect(renderFieldViewSource).not.toContain("meta?.badge");
  });

  it("keeps restart timing visible for workbench ports", () => {
    const schemaSource = readFileSync(new URL("../core/web/services/config_editor_schema.py", import.meta.url), "utf-8");

    expect(schemaSource).toContain("修改后下次启动或重启生效");
    expect(schemaSource).toContain("Restart the workbench after changing it");
  });

  it("shows model edit failures inside the model editor instead of relying only on the page notice", () => {
    expect(configRouteSource).toContain("modelEditorError");
    expect(configRouteSource).toContain('role="alert"');
    expect(configRouteSource).toContain("styles.inlineFormError");
    expect(configRouteSource).toContain("setModelEditorError(markError(error))");
  });

  it("guards internal route changes when config changes have not been saved to disk", () => {
    expect(configRouteSource).toContain("useBlocker");
    expect(configRouteSource).toContain("shouldBlockConfigLeave");
    expect(configRouteSource).toContain('leaveBlocker.state === "blocked"');
    expect(configRouteSource).toContain("handleSaveAndLeave");
    expect(configRouteSource).toContain("copy.leaveGuardSave");
    expect(configRouteSource).toContain("copy.leaveGuardDiscard");
    expect(configRouteSource).toContain("copy.leaveGuardCancel");

    expect(configRouteCss).toContain(".leaveGuardOverlay");
    expect(configRouteCss).toContain(".leaveGuardPanel");
  });
});
