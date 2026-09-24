import { describe, expect, it, vi } from "vitest";
import { createPetSettingsControl, petSettingsOrigin } from "../src/windows/petSettingsControl.js";
import { closedWindowState } from "../src/windows/windowProviderTypes.js";

describe("pet settings control", () => {
  it("admits only registered workbench settings routes", () => {
    expect(petSettingsOrigin("http://127.0.0.1:8001/config?section=avatar-pet", "branch-workbench")).toBe("http://127.0.0.1:8001");
    for (const role of ["launcher", "desktop-pet", "unknown"]) {
      expect(() => petSettingsOrigin("http://127.0.0.1:8000/config", role)).toThrow();
    }
    expect(() => petSettingsOrigin("http://127.0.0.1:8000/chat", "main-workbench")).toThrow();
  });
  it("reads actual state and closes or reopens using the requesting workspace", async () => {
    let pet = closedWindowState("pet");
    const owner = {
      snapshot: () => ({ pet }),
      openPet: vi.fn(async (url: string) => pet = { ...pet, open: true, url: `${url}/desktop-pet` }),
      closePet: vi.fn(async () => pet = closedWindowState("pet")),
    };
    const control = createPetSettingsControl(() => owner);
    expect(await control("http://127.0.0.1:8001", undefined)).toEqual({open:false,busyElsewhere:false});
    expect(owner.openPet).not.toHaveBeenCalled();
    expect(await control("http://127.0.0.1:8001", true)).toEqual({open:true,busyElsewhere:false});
    expect(owner.openPet).toHaveBeenCalledWith("http://127.0.0.1:8001");
    expect(await control("http://127.0.0.1:8000", false)).toEqual({open:false,busyElsewhere:true});
    expect(owner.closePet).not.toHaveBeenCalled();
    expect(await control("http://127.0.0.1:8001", false)).toEqual({open:false,busyElsewhere:false});
    expect(await control("http://127.0.0.1:8001", true)).toEqual({open:true,busyElsewhere:false});
  });
  it("serializes concurrent workspaces and rejects malformed operations", async () => {
    let pet = closedWindowState("pet");
    const control = createPetSettingsControl(() => ({
      snapshot: () => ({pet}),
      openPet: async url => pet = {...pet,open:true,url:`${url}/desktop-pet`},
      closePet: async () => pet = closedWindowState("pet"),
    }));
    await expect(control("http://127.0.0.1:8000", "true")).rejects.toThrow("Invalid");
    const [first,second] = await Promise.all([control("http://127.0.0.1:8000",true),control("http://127.0.0.1:8001",true)]);
    expect(first.open).toBe(true); expect(second.busyElsewhere).toBe(true);
    await expect(createPetSettingsControl(() => null)("http://127.0.0.1:8000", true)).rejects.toThrow("not ready");
  });
});
