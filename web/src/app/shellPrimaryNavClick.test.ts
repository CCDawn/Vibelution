/** @vitest-environment happy-dom */

import { describe, expect, it } from "vitest";

import {
  isModifiedPrimaryNavClick,
  resolveUnmodifiedShellNavHref,
  shellNavAnchorFromEventTarget,
} from "./shellPrimaryNavClick";

describe("shellPrimaryNavClick", () => {
  it("keeps modifier and non-primary clicks on the native link behavior", () => {
    expect(isModifiedPrimaryNavClick({ metaKey: false, ctrlKey: false, shiftKey: false, altKey: false, button: 0 })).toBe(false);
    expect(isModifiedPrimaryNavClick({ metaKey: true, ctrlKey: false, shiftKey: false, altKey: false, button: 0 })).toBe(true);
    expect(isModifiedPrimaryNavClick({ metaKey: false, ctrlKey: true, shiftKey: false, altKey: false, button: 0 })).toBe(true);
    expect(isModifiedPrimaryNavClick({ metaKey: false, ctrlKey: false, shiftKey: false, altKey: false, button: 1 })).toBe(true);
  });

  it("resolves same-origin shell hrefs to router locations and rejects foreign urls", () => {
    expect(resolveUnmodifiedShellNavHref("/teams", "http://127.0.0.1:8002")).toBe("/teams");
    expect(resolveUnmodifiedShellNavHref("http://127.0.0.1:8002/teams?teamId=research-team", "http://127.0.0.1:8002")).toBe(
      "/teams?teamId=research-team",
    );
    expect(resolveUnmodifiedShellNavHref("https://example.com/teams", "http://127.0.0.1:8002")).toBeNull();
    expect(resolveUnmodifiedShellNavHref("javascript:void(0)", "http://127.0.0.1:8002")).toBeNull();
    expect(resolveUnmodifiedShellNavHref("#main", "http://127.0.0.1:8002")).toBeNull();
  });

  it("finds the shell nav anchor from a nested click target", () => {
    const nav = document.createElement("nav");
    nav.setAttribute("data-shell-group", "navigation");
    const link = document.createElement("a");
    link.setAttribute("href", "/teams");
    const label = document.createElement("span");
    label.textContent = "团队";
    link.appendChild(label);
    nav.appendChild(link);
    document.body.appendChild(nav);
    expect(shellNavAnchorFromEventTarget(label)).toBe(link);
    expect(shellNavAnchorFromEventTarget(document.body)).toBeNull();
    nav.remove();
  });
});
