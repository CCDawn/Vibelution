export const ISOLATED_INSTANCE_READY_WAIT_MS = 180_000;

export type IsolatedInstanceSuperviseResult = "opened" | "error";

export type IsolatedInstanceSuperviseInput = {
  instanceId: string;
  url: string;
  generation: number;
  timeoutMs?: number;
  waitForHttp: (url: string, timeoutMs: number) => Promise<void>;
  openWindow: () => Promise<void>;
  markReady: (generation: number) => Promise<void>;
  markError: (generation: number, message: string) => Promise<void>;
};

export async function superviseIsolatedInstanceStart(
  input: IsolatedInstanceSuperviseInput
): Promise<IsolatedInstanceSuperviseResult> {
  const timeoutMs = Math.max(1, input.timeoutMs ?? ISOLATED_INSTANCE_READY_WAIT_MS);
  try {
    await input.waitForHttp(input.url, timeoutMs);
    await input.openWindow();
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : String(error);
    await input.markError(input.generation, message);
    return "error";
  }
  await input.markReady(input.generation);
  return "opened";
}
