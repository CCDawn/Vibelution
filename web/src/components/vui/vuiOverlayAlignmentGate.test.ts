import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join, relative, resolve } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * Overlay / floating-surface alignment gate (VUI Radix lift campaign closure).
 *
 * Intentional keep (do not force onto VDialog/VPopover):
 * - ChatToolApprovalDialog: banner/inline in-session confirm (not a modal stack)
 * - ChatCodingRoute.styles overlayBackdrop: responsive side-panel dimmer (VButton)
 * - challenge-cup-platform-home-preview-tooltips: design preview only
 * - ShadcnDialog overlay: renderer implementation of VDialog
 * - VNativeSelect / VNative*: reserved dense dual track; product routes currently
 *   prefer VStringSelect for form-like selects
 */

const sourceRoot = resolve(import.meta.dirname, "../..");

function walkFiles(dir: string): string[] {
  if (!existsSync(dir)) return [];
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === "node_modules" || entry.name === "dist") return [];
      return walkFiles(path);
    }
    return entry.isFile() ? [path] : [];
  });
}

function sourcePath(path: string): string {
  return relative(sourceRoot, path).replaceAll("\\", "/");
}

function read(rel: string): string {
  return readFileSync(resolve(sourceRoot, rel), "utf8");
}

const productScanRoots = ["app", "routes", "components"] as const;

const createPortalAllowlist = new Set([
  "design/challenge-cup-platform-home-preview-tooltips.tsx",
]);

const fixedInsetAllowlist = new Set([
  "components/vui/renderers/shadcn/ShadcnDialog.tsx",
  "routes/ChatCodingRoute.styles.ts",
]);

const handRolledDialogAllowlist = new Set([
  "routes/chat/ChatToolApprovalDialog.tsx",
]);

describe("VUI overlay alignment gate", () => {
  it("forbids product createPortal outside intentional allowlist", () => {
    const hits: string[] = [];
    for (const root of productScanRoots) {
      for (const file of walkFiles(resolve(sourceRoot, root))) {
        if (!/\.(tsx|ts)$/.test(file)) continue;
        if (file.endsWith(".test.ts") || file.endsWith(".test.tsx")) continue;
        const rel = sourcePath(file);
        if (createPortalAllowlist.has(rel)) continue;
        // VUI renderers may portal internally via Radix, not react-dom createPortal.
        if (rel.startsWith("components/vui/renderers/")) continue;
        const text = readFileSync(file, "utf8");
        if (text.includes("createPortal(") || text.includes('from "react-dom"') && text.includes("createPortal")) {
          if (/\bcreatePortal\b/.test(text)) hits.push(rel);
        }
      }
    }
    expect(hits).toEqual([]);
  });

  it("forbids product fixed inset-0 overlays outside intentional allowlist", () => {
    const hits: string[] = [];
    for (const root of productScanRoots) {
      for (const file of walkFiles(resolve(sourceRoot, root))) {
        if (!/\.(tsx|ts)$/.test(file)) continue;
        if (file.endsWith(".test.ts") || file.endsWith(".test.tsx")) continue;
        const rel = sourcePath(file);
        if (fixedInsetAllowlist.has(rel)) continue;
        if (rel.startsWith("components/vui/renderers/")) continue;
        const text = readFileSync(file, "utf8");
        if (/fixed\s+inset-0|fixed inset-0|\[position:fixed\][^\n]*\[inset:0\]/.test(text)) {
          hits.push(rel);
        }
      }
    }
    expect(hits).toEqual([]);
  });

  it("forbids hand-rolled role=dialog product shells outside ChatToolApproval", () => {
    const hits: string[] = [];
    for (const root of productScanRoots) {
      for (const file of walkFiles(resolve(sourceRoot, root))) {
        if (!/\.tsx$/.test(file)) continue;
        if (file.endsWith(".test.tsx")) continue;
        const rel = sourcePath(file);
        if (handRolledDialogAllowlist.has(rel)) continue;
        if (rel.startsWith("components/vui/")) continue;
        const text = readFileSync(file, "utf8");
        // VDialog/VConfirmDialog hosts own role=dialog via Radix; product sources should not declare it.
        if (/role=["']dialog["']/.test(text) && !text.includes("<VDialog") && !text.includes("<VConfirmDialog")) {
          hits.push(rel);
        } else if (/role=["']dialog["']/.test(text) && !text.includes("ChatToolApproval")) {
          // Even with VDialog import, product should not re-declare role=dialog on custom shells.
          if (/role=["']dialog["']/.test(text) && /aria-modal/.test(text) && !rel.includes("ChatToolApproval")) {
            // Flag only if role=dialog is a JSX attribute not inside a string comment about VDialog.
            const withoutComments = text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
            if (/role=\{?["']dialog["']\}?/.test(withoutComments)) {
              // Allowed only when the only dialog roles come from consuming primitives indirectly.
              // Product files that still write role="dialog" fail.
              if (withoutComments.includes('role="dialog"') || withoutComments.includes("role='dialog'")) {
                hits.push(rel);
              }
            }
          }
        }
      }
    }
    expect(hits).toEqual([]);
  });

  it("locks modal product hosts on VDialog", () => {
    expect(read("routes/agent-create/AgentCreateWizardDialog.tsx")).toContain("<VDialog");
    expect(read("routes/AgentModelPicker.tsx")).toContain("<VDialog");
    expect(read("routes/chat/CacheDetailDialog.tsx")).toContain("<VDialog");
    expect(read("components/conversation/ConversationImagePreviewDialog.tsx")).toContain("<VDialog");
    expect(read("routes/ConfigRoute.tsx")).toContain("open={leaveGuardOpen}");
    expect(read("routes/ConfigRoute.tsx")).toContain("<VDialog");
  });

  it("locks shell floating panels on VPopover", () => {
    const shell = read("app/AppShell.tsx");
    expect(shell).toContain('data-vui="active-work-popover"');
    expect(shell).toContain('data-vui="status-guide-popover"');
    expect(shell).toContain("contentClassName={styles.utilityPopoverContent}");
    expect(shell).toContain("<VPopover");
    expect(read("components/conversation/ConversationInferenceControl.tsx")).toContain("<VPopover");
    expect(read("components/vui/product/agent-management/AgentPermissionPresetControl.tsx")).toContain("<VPopover");
  });

  it("locks context menus on VDropdownMenu and shell power on VWorkbenchPowerMenu", () => {
    expect(read("routes/AgentContextMenu.tsx")).toContain("<VDropdownMenu");
    expect(read("routes/SessionContextMenu.tsx")).toContain("<VDropdownMenu");
    // AppShell power lifecycle uses the unified product composition (not a bare VDropdownMenu).
    expect(read("app/AppShell.tsx")).toContain("<VWorkbenchPowerMenu");
    expect(read("components/vui/product/workbench-shell/VWorkbenchPowerMenu.tsx")).toContain("<VDropdownMenu");
  });

  it("keeps product routes free of VNativeSelect (form selects use VStringSelect)", () => {
    const hits: string[] = [];
    for (const file of walkFiles(resolve(sourceRoot, "routes"))) {
      if (!/\.tsx$/.test(file) || file.endsWith(".test.tsx")) continue;
      const rel = sourcePath(file);
      const text = readFileSync(file, "utf8");
      if (text.includes("VNativeSelect") || text.includes("<select")) {
        // allow none: VNativeSelect reserved, no product consumer after lift
        if (/\bVNativeSelect\b/.test(text) || /<select\b/.test(text)) {
          hits.push(rel);
        }
      }
    }
    // Also app shell
    for (const file of walkFiles(resolve(sourceRoot, "app"))) {
      if (!/\.tsx$/.test(file) || file.endsWith(".test.tsx")) continue;
      const text = readFileSync(file, "utf8");
      if (/\bVNativeSelect\b/.test(text) || /<select\b/.test(text)) {
        hits.push(sourcePath(file));
      }
    }
    expect(hits).toEqual([]);
  });

  it("documents intentional keep surfaces still present", () => {
    expect(read("routes/chat/ChatToolApprovalDialog.tsx")).toContain('role="dialog"');
    expect(read("routes/chat/ChatToolApprovalDialog.tsx")).toContain('variant === "banner"');
    expect(read("routes/ChatCodingRoute.styles.ts")).toContain("overlayBackdrop");
    expect(read("routes/ChatCodingRoute.styles.ts")).toContain("fixed inset-0");
    expect(existsSync(resolve(sourceRoot, "design/challenge-cup-platform-home-preview-tooltips.tsx"))).toBe(true);
    expect(existsSync(resolve(sourceRoot, "components/vui/forms/VNativeSelect.tsx"))).toBe(true);
  });
});
