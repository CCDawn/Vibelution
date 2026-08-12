export function isBrokenPipeError(error: unknown): boolean {
  return Boolean(
    error &&
      typeof error === "object" &&
      "code" in error &&
      (error as { code?: unknown }).code === "EPIPE"
  );
}

type ConsoleMethod = "log" | "info" | "warn" | "error";

export type BrokenPipeStream = {
  on(event: "error", listener: (error: Error) => void): unknown;
};

export type BrokenPipeGuardTarget = {
  stdout?: BrokenPipeStream | null;
  stderr?: BrokenPipeStream | null;
  console: Pick<Console, ConsoleMethod>;
};

export function installBrokenPipeGuards(
  target: BrokenPipeGuardTarget = {
    stdout: process.stdout,
    stderr: process.stderr,
    console
  }
): void {
  const ignoreBrokenPipe = (error: Error): void => {
    if (!isBrokenPipeError(error)) {
      throw error;
    }
  };
  target.stdout?.on("error", ignoreBrokenPipe);
  target.stderr?.on("error", ignoreBrokenPipe);

  for (const method of ["log", "info", "warn", "error"] as const) {
    const original = target.console[method].bind(target.console);
    target.console[method] = ((...args: unknown[]) => {
      try {
        original(...args);
      } catch (error) {
        if (!isBrokenPipeError(error)) {
          throw error;
        }
      }
    }) as Console[typeof method];
  }
}
