import { describe, expect, it } from "vitest";

import {
  nextDesktopPetCharacter,
  whaleRigStateForPetAnimation,
} from "./desktopPetCharacterModel";

describe("desktop pet character model", () => {
  it("toggles between the two approved characters", () => {
    expect(nextDesktopPetCharacter("xiaoluo")).toBe("dafeiyu");
    expect(nextDesktopPetCharacter("dafeiyu")).toBe("xiaoluo");
  });

  it("maps native pet activity to the whale rig's real motion states", () => {
    expect(whaleRigStateForPetAnimation("idle")).toBe("idle");
    expect(whaleRigStateForPetAnimation("waiting")).toBe("waiting");
    expect(whaleRigStateForPetAnimation("alert")).toBe("failed");
    expect(whaleRigStateForPetAnimation("thinking")).toBe("thinking");
    expect(whaleRigStateForPetAnimation("reading")).toBe("reading");
    expect(whaleRigStateForPetAnimation("tooling")).toBe("running");
    expect(whaleRigStateForPetAnimation("verifying")).toBe("verifying");
    expect(whaleRigStateForPetAnimation("answering")).toBe("answering");
    expect(whaleRigStateForPetAnimation("celebrating")).toBe("jumping");
  });
});
