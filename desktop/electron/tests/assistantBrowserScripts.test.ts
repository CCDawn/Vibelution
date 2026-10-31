import { runInNewContext, createContext } from "node:vm";
import { describe, expect, it } from "vitest";
import { SNAPSHOT_SCRIPT, snapshotScript, targetScript } from "../src/browser/pageScripts.js";
function fixture() {
  class Element {
    clickCount = 0; isConnected = true; disabled = false; readOnly = false; innerText = ""; type = ""; labels: Array<{ innerText: string }> = []; attrs: Record<string, string> = {};
    constructor(public tagName: string) {}
    getAttribute(n: string) { return this.attrs[n] ?? null; } hasAttribute(n: string) { return Object.hasOwn(this.attrs, n); } closest() { return null; }
    getBoundingClientRect() { return { width: 100, height: 30, left: 10, top: 10, right: 110, bottom: 40 }; }
    contains(other: unknown) { return other === this; }
    focus() { doc.activeElement = this; } select() {} click() { this.clickCount++; doc.elementFromPoint = () => ({}); }
  }
  class Input extends Element { private current = ""; get value() { return this.current; } set value(v: string) { this.current = v; } constructor(type: string) { super("INPUT"); this.type = type; } dispatchEvent() { return true; } }
  class Textarea extends Element { value = ""; constructor() { super("TEXTAREA"); } }
  class Anchor extends Element { target = "_blank"; href = "https://example.com/path?q=1#part"; constructor() { super("A"); this.attrs.href = "/path?q=1#part"; this.innerText = "Open"; } }
  const password = new Input("password"); password.value = "secret"; password.attrs["aria-label"] = "Password";
  const field = new Input("text"); field.value = "private input value"; field.attrs["aria-label"] = "Search";
  const button = new Element("BUTTON"); button.innerText = "Search now";
  const nodes = [password, field, button];
  const doc: any = { body: { innerText: "Visible page text" }, activeElement: null, querySelectorAll: () => nodes, elementFromPoint: () => button };
  const context = createContext({ Event: class { constructor(..._args: unknown[]) {} }, document: doc, innerWidth: 600, innerHeight: 400, HTMLElement: Element, HTMLAnchorElement: Anchor, HTMLInputElement: Input, HTMLTextAreaElement: Textarea,
    getComputedStyle: () => ({ visibility: "visible", display: "block", opacity: "1" }) });
  const run = (script: string) => runInNewContext(script, context);
  return { password, field, button, doc, run, nodes, Anchor };
}
describe("isolated browser page scripts", () => {
  it("omits password controls and all text input values", () => {
    const f = fixture(); const snap = f.run(SNAPSHOT_SCRIPT);
    expect(JSON.stringify(snap)).not.toContain("secret"); expect(JSON.stringify(snap)).not.toContain("private input value");
    expect(snap.elements.map((e: { name: string }) => e.name)).toEqual(["Search", "Search now"]);
    f.doc.activeElement = f.password; f.doc.elementFromPoint = () => f.field; expect(f.run(targetScript("1", "fill", "query"))).toEqual({ filled: true });
    expect(f.field.value).toBe("query"); expect(f.password.value).toBe("secret"); expect(f.doc.activeElement).toBe(f.password);
    f.field.type = "password"; expect(f.run(targetScript("1", "fill"))).toBeNull();
  });
  it("reports uncertain fill when the page replaces the target or cancels an event", () => {
    const f = fixture(); f.doc.elementFromPoint = () => f.field; f.run(SNAPSHOT_SCRIPT);
    f.field.dispatchEvent = () => { f.field.isConnected = false; return true; };
    expect(f.run(targetScript("1", "fill", "query"))).toEqual({ filled: false });
    f.field.isConnected = true; f.run(SNAPSHOT_SCRIPT); f.field.dispatchEvent = () => false;
    expect(f.run(targetScript("1", "fill", "query"))).toEqual({ filled: false });
  });
  it("clicks the validated element itself even if the hit location changes", () => {
    const f = fixture(); f.run(SNAPSHOT_SCRIPT);
    expect(f.run(targetScript("2", "click"))).toEqual({ clicked: true });
    expect(f.button.clickCount).toBe(1); expect(f.doc.elementFromPoint()).not.toBe(f.button);
  });
  it("returns only the approved blank-target anchor URL without activating a popup", () => {
    const f = fixture(), link = new f.Anchor(); f.nodes.push(link); f.doc.elementFromPoint = () => link; f.run(SNAPSHOT_SCRIPT);
    expect(f.run(targetScript("3", "click"))).toEqual({ navigateUrl: "https://example.com/path?q=1#part" }); expect(link.clickCount).toBe(0);
    link.attrs.href = "https://example.com/\nsecret"; expect(f.run(targetScript("3", "click"))).toEqual({ invalidUrl: true });
  });
  it("rejects a stale renderer snapshot token even when the element reference is reused", () => {
    const f = fixture(); f.run(snapshotScript("old")); f.run(snapshotScript("new"));
    expect(f.run(targetScript("2", "click", "", "old"))).toBeNull(); expect(f.button.clickCount).toBe(0);
    expect(f.run(targetScript("2", "click", "", "new"))).toEqual({ clicked: true });
  });
  it("rejects detached, renamed, replaced or obscured elements", () => {
    const f = fixture(); f.run(SNAPSHOT_SCRIPT); expect(f.run(targetScript("2", "preview"))).toMatchObject({ name: "Search now", role: "button" });
    f.button.innerText = "changed"; expect(f.run(targetScript("2", "click"))).toBeNull();
    f.button.innerText = "Search now"; f.button.isConnected = false; expect(f.run(targetScript("2", "click"))).toBeNull();
    f.button.isConnected = true; f.doc.elementFromPoint = () => ({}); expect(f.run(targetScript("2", "click"))).toBeNull();
  });
});
