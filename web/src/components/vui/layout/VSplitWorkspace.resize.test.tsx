import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { VSplitWorkspace } from "./VSplitWorkspace";

describe("VSplitWorkspace resizable", () => {
  it("renders drag separators and layout id when resize.layoutId is set", () => {
    const store = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => {
        store.set(key, value);
      },
      removeItem: (key: string) => {
        store.delete(key);
      },
    });
    vi.stubGlobal("window", { localStorage: globalThis.localStorage });

    const html = renderToStaticMarkup(
      <VSplitWorkspace
        resize={{ layoutId: "skills" }}
        sidebar={<div>list</div>}
        main={<div>detail</div>}
      />,
    );

    expect(html).toContain('data-vui-resizable="true"');
    expect(html).toContain('data-vui-layout-id="skills"');
    expect(html).toContain('role="separator"');
    expect(html).toContain("调整左侧栏宽度");
    expect(html).toContain("list");
    expect(html).toContain("detail");
  });

  it("keeps fixed grid mode when resize is omitted", () => {
    const html = renderToStaticMarkup(
      <VSplitWorkspace sidebar={<div>list</div>} main={<div>detail</div>} />,
    );
    expect(html).not.toContain("data-vui-resizable");
    expect(html).toContain("grid-cols-");
  });
});
