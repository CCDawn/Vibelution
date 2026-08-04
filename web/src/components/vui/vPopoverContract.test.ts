import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const vuiRoot = resolve(import.meta.dirname);

describe("VPopover contract", () => {
  it("exports Radix popover renderer and product facade", () => {
    const indexSource = readFileSync(resolve(vuiRoot, "index.ts"), "utf8");
    const facade = readFileSync(resolve(vuiRoot, "primitives/VPopover.tsx"), "utf8");
    const renderer = readFileSync(resolve(vuiRoot, "renderers/shadcn/ShadcnPopover.tsx"), "utf8");
    const catalog = readFileSync(resolve(vuiRoot, "designs/INDEX.md"), "utf8");
    const feedback = readFileSync(resolve(vuiRoot, "designs/primitives/feedback.md"), "utf8");

    expect(indexSource).toContain("VPopover");
    expect(facade).toContain("ShadcnPopover");
    expect(renderer).toContain("@radix-ui/react-popover");
    expect(renderer).toContain("PopoverPrimitive");
    expect(renderer).toContain('data-renderer="radix"');
    expect(catalog).toContain("`VPopover`");
    expect(feedback).toContain("## VPopover");
  });

  it("AppShell utility panel uses VPopover instead of hover cluster listeners", () => {
    const shell = readFileSync(resolve(vuiRoot, "../../app/AppShell.tsx"), "utf8");
    expect(shell).toContain("VPopover");
    expect(shell).toContain("contentClassName={styles.utilityPopoverContent}");
    expect(shell).toContain("LazyAppShellUtilityMenu");
    expect(shell).not.toContain("utilityMenuRef");
    expect(shell).not.toContain("onMouseEnter={() => setUtilityOpen(true)}");
  });

  it("AppShell active-work details use VPopover instead of CSS hover panel", () => {
    const shell = readFileSync(resolve(vuiRoot, "../../app/AppShell.tsx"), "utf8");
    const styles = readFileSync(resolve(vuiRoot, "../../app/AppShell.styles.ts"), "utf8");
    expect(shell).toContain('data-vui="active-work-popover"');
    expect(shell).toContain("contentClassName={styles.activeWorkPopoverContent}");
    expect(shell).toContain("activeWorkDetailPanel");
    expect(styles).toContain("activeWorkPopoverContent");
    expect(styles).not.toContain("[&:hover_.activeWorkDetailPanel]:visible");
  });

  it("composer permission and inference menus use VPopover instead of createPortal", () => {
    const permission = readFileSync(
      resolve(vuiRoot, "product/agent-management/AgentPermissionPresetControl.tsx"),
      "utf8",
    );
    const inference = readFileSync(
      resolve(vuiRoot, "../conversation/ConversationInferenceControl.tsx"),
      "utf8",
    );
    expect(permission).toContain("<VPopover");
    expect(permission).not.toContain("createPortal(");
    expect(inference).toContain("<VPopover");
    expect(inference).not.toContain("createPortal(");
  });
});
