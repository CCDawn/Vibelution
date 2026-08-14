export function pythonBridgeEnv(base: NodeJS.ProcessEnv = process.env): NodeJS.ProcessEnv {
  return {
    ...base,
    VIBELUTION_ELECTRON_MAIN_ORCHESTRATES_WINDOWS: "1",
    PYTHONIOENCODING: "utf-8",
    PYTHONUTF8: "1"
  };
}
