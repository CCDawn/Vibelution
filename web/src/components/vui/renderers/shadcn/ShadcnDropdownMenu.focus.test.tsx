// @vitest-environment happy-dom
import React, { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { VDropdownMenu } from "../../index";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | undefined;
let container: HTMLElement;
let original: HTMLButtonElement;
let destination: HTMLInputElement;

function mount() {
  container = document.createElement("div");
  original = document.createElement("button");
  destination = document.createElement("input");
  document.body.append(original, destination, container);
  original.focus();
  root = createRoot(container);
  function Menu() {
    const [open, setOpen] = useState(true);
    return open ? (
      <VDropdownMenu
        open
        position={{ x: 10, y: 10 }}
        onOpenChange={setOpen}
        items={[{ id: "edit", label: "Edit", onSelect: () => destination.focus() }]}
      />
    ) : null;
  }
  act(() => root?.render(<Menu />));
}

afterEach(() => {
  act(() => root?.unmount());
  root = undefined;
  container?.remove();
  original?.remove();
  destination?.remove();
});

describe("anchored dropdown focus", () => {
  it("returns Escape focus to the original control instead of the virtual anchor", async () => {
    mount();
    const menu = document.querySelector('[role="menu"]');
    expect(menu).not.toBeNull();
    await act(async () => {
      menu?.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
      await new Promise((resolve) => setTimeout(resolve, 10));
    });
    expect(document.querySelector('[role="menu"]')).toBeNull();
    expect(document.activeElement).toBe(original);
  });

  it("keeps focus on the destination when a menu action opens an editor", async () => {
    mount();
    await act(async () => {
      document.querySelector('[role="menuitem"]')?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await new Promise((resolve) => setTimeout(resolve, 10));
    });
    expect(document.querySelector('[role="menu"]')).toBeNull();
    expect(document.activeElement).toBe(destination);
  });
});
