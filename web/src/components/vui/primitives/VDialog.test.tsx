import { describe, expect, it } from "vitest";

// @ts-expect-error Vitest runs this contract in Node; the web project intentionally omits global Node types.
import { readFileSync } from "node:fs";
// @ts-expect-error Vitest runs this contract in Node; the web project intentionally omits global Node types.
import { resolve } from "node:path";

import { VConfirmDialog, VDialog } from "./VDialog";

describe("VDialog", () => {
  it("keeps product API on the Radix/shadcn renderer", () => {
    const dialogSource = readFileSync(resolve(import.meta.dirname, "VDialog.tsx"), "utf8");
    const rendererSource = readFileSync(
      resolve(import.meta.dirname, "../renderers/shadcn/ShadcnDialog.tsx"),
      "utf8",
    );

    expect(dialogSource).toContain('from "../renderers/shadcn/ShadcnDialog"');
    expect(dialogSource).toContain("export function VDialog");
    expect(dialogSource).toContain("export function VConfirmDialog");
    expect(dialogSource).toContain('variant={tone === "danger" ? "danger" : "primary"}');
    expect(rendererSource).toContain("@radix-ui/react-dialog");
    expect(rendererSource).toContain('data-vui="dialog-content"');
    expect(rendererSource).toContain('data-vui="dialog-overlay"');
    expect(rendererSource).toContain("DialogPrimitive.Title");
    expect(rendererSource).toContain("DialogPrimitive.Description");
  });

  it("exports stable product entrypoints", () => {
    expect(typeof VDialog).toBe("function");
    expect(typeof VConfirmDialog).toBe("function");
  });

  it("exposes compact workbench sizes on the renderer", () => {
    const rendererSource = readFileSync(
      resolve(import.meta.dirname, "../renderers/shadcn/ShadcnDialog.tsx"),
      "utf8",
    );
    expect(rendererSource).toContain('sm: "w-[min(100%,22rem)]"');
    expect(rendererSource).toContain('md: "w-[min(100%,28rem)]"');
    expect(rendererSource).toContain('lg: "w-[min(100%,36rem)]"');
    expect(rendererSource).toContain("fixed left-1/2 top-1/2");
  });
});
