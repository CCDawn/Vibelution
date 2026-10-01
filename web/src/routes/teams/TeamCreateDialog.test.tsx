import { describe, expect, it } from "vitest";

import { teamCreateCopy } from "./TeamCreateDialog";
import dialogSource from "./TeamCreateDialog.tsx?raw";
import toolbarSource from "./TeamCreateToolbarActions.tsx?raw";
import actionsSource from "./useTeamCreateActions.ts?raw";

describe("TeamCreateDialog", () => {
  it("uses VUI dialog/input/buttons only (no raw button element, no shadcn direct import)", () => {
    expect(dialogSource).toContain("<VDialog");
    expect(dialogSource).toContain('size="xl"');
    expect(dialogSource).toContain("VButton");
    expect(dialogSource).toContain("VNativeInput");
    expect(dialogSource).toContain('from "../../components/vui"');
    expect(dialogSource).not.toMatch(/<button[\s>]/);
    expect(dialogSource).not.toContain("renderers/shadcn");
    expect(dialogSource).not.toContain("components/ui/");
    expect(dialogSource).not.toContain("@heroui/react");
    for (const source of [dialogSource, toolbarSource, actionsSource]) {
      expect(source).not.toMatch(/['"`]\/api\//);
    }
  });

  it("keeps mutations in the create actions hook, not the dialog", () => {
    expect(dialogSource).not.toContain("useMutation");
    expect(actionsSource.match(/\buseMutation\(/g) ?? []).toHaveLength(2);
    expect(actionsSource).toContain("instantiateTeamTemplate(");
    expect(actionsSource).toContain("createTeam(");
    expect(actionsSource).toContain("afterTeamChanged");
    expect(actionsSource).toContain('startUserAction("team_create"');
    expect(actionsSource).toContain("onTeamCreated");
  });

  it("guards closing with a discard confirm and returns focus to the trigger", () => {
    expect(dialogSource).toContain("discardConfirmOpen");
    expect(dialogSource).toContain("triggerRef?.current");
    expect(dialogSource).toContain("document.getElementById(triggerId)");
    expect(dialogSource).toContain("requestAnimationFrame");
    expect(toolbarSource).toContain("triggerRef={triggerRef}");
  });

  it("renders the three flow states (template select, name, success)", () => {
    expect(dialogSource).toContain('draft.step === "name"');
    expect(dialogSource).toContain("outcome ?");
    expect(dialogSource).toContain("onGoToTeam");
    expect(dialogSource).toContain("templatesQuery");
  });

  it("provides a pure zh/en copy table", () => {
    expect(teamCreateCopy("zh").title).toBe("新建团队");
    expect(teamCreateCopy("en").title).toBe("New team");
    expect(teamCreateCopy("zh").goToTeam).toBe("前往团队");
    expect(teamCreateCopy("en").goToTeam).toBe("Go to team");
    expect(teamCreateCopy("zh").blankTeamName).toBe("空白团队");
    expect(teamCreateCopy("en").blankTeamName).toBe("Blank team");
  });

  it("toolbar mounts the create dialog and hands the created team to the shell", () => {
    expect(toolbarSource).toContain("TeamCreateDialog");
    expect(toolbarSource).toContain("useTeamCreateActions");
    expect(toolbarSource).toContain("onTeamCreated");
    expect(toolbarSource).toContain("新建团队");
  });
});
