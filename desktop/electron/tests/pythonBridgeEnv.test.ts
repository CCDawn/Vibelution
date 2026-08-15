import { describe, expect, it } from "vitest";

import { pythonBridgeEnv } from "../src/process/pythonBridgeEnv.js";

describe("pythonBridgeEnv", () => {
  it("forces UTF-8 stdio and Electron-owned windows on spawned Python", () => {
    const env = pythonBridgeEnv({ PATH: "C:/Windows", PYTHON: "python.exe" });
    expect(env.PATH).toBe("C:/Windows");
    expect(env.PYTHON).toBe("python.exe");
    expect(env.VIBELUTION_ELECTRON_MAIN_ORCHESTRATES_WINDOWS).toBe("1");
    expect(env.PYTHONIOENCODING).toBe("utf-8");
    expect(env.PYTHONUTF8).toBe("1");
  });
});
