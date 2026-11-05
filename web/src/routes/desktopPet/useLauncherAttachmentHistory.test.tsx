// @vitest-environment happy-dom
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import type { ConversationMessage } from "../../api/types";
import { useLauncherAttachmentHistory } from "./useLauncherAttachmentHistory";

vi.mock("../../api/launcherAssistant", () => ({ readLauncherAttachment: vi.fn() }));
import { readLauncherAttachment } from "../../api/launcherAssistant";
const read = vi.mocked(readLauncherAttachment);
let root: ReturnType<typeof createRoot>;
let result: ReturnType<typeof useLauncherAttachmentHistory>;
let rerender: (ids: string[], messages?: ConversationMessage[], options?: { sessionId?: string; enabled?: boolean }) => Promise<void>;
const row = (n: number) => ({ id: `m${n}`, role: "user", content: "", attachments: [{ artifactId: `i${n}.png`, kind: "user_image", url: "/old", imageUrl: "/old", downloadUrl: "/old" }] }) as unknown as ConversationMessage;
afterEach(async () => { if (root) await act(async () => root.unmount()); document.body.innerHTML = ""; vi.resetAllMocks(); });
async function setup(initial: ConversationMessage[]) {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  const div = document.createElement("div"); document.body.append(div); root = createRoot(div);
  let messages = initial;
  let sessionId = "s";
  let enabled = true;
  function Harness({ ids, rows, sessionId, enabled }: { ids: string[]; rows: ConversationMessage[]; sessionId: string; enabled: boolean }) { result = useLauncherAttachmentHistory(rows, sessionId, enabled, ids); return null; }
  rerender = async (ids, next, options) => {
    messages = next || messages;
    sessionId = options?.sessionId ?? sessionId;
    enabled = options?.enabled ?? enabled;
    await act(async () => { root.render(createElement(Harness, { ids, rows: messages, sessionId, enabled })); await new Promise(resolve => setTimeout(resolve, 0)); });
  };
  await rerender([]);
}
it("loads only visible history, bounds the cache and reloads an evicted old row", async () => {
  const rows = Array.from({ length: 35 }, (_, i) => row(i));
  read.mockImplementation(async id => `data:image/png;base64,${id}`);
  await setup(rows);
  expect(read).not.toHaveBeenCalled();
  for (let i = 0; i < 34; i++) await rerender([`m${i}`]);
  expect(read).toHaveBeenCalledTimes(34);
  expect((result.messages[0] as any).attachments[0].imageUrl).toBe("");
  await rerender(["m0"]);
  expect(read).toHaveBeenCalledTimes(35);
  expect((result.messages[0] as any).attachments[0].imageUrl).toBe("data:image/png;base64,i0.png");
  await rerender(["m34"]);
  expect(read).toHaveBeenLastCalledWith("i34.png");
});
it("serializes visible reads, discards stale results and resolves generated images by ID", async () => {
  let resolveFirst!: (value: string) => void;
  read.mockImplementationOnce(() => new Promise(resolve => { resolveFirst = resolve; })).mockResolvedValue("data:image/png;base64,AQI=");
  const generated = { id: "g", role: "assistant", metadata: { kind: "image2_generation", status: "succeeded", artifactId: "generated.png", artifactPath: "secret", imageUrl: "https://untrusted", downloadUrl: "/old" } } as unknown as ConversationMessage;
  await setup([row(0), row(1), generated]);
  await rerender(["m0", "m1"]);
  expect(read).toHaveBeenCalledTimes(1);
  await rerender(["g"]);
  expect(read).toHaveBeenCalledTimes(1);
  await act(async () => { resolveFirst("data:image/png;base64,OLD"); await new Promise(resolve => setTimeout(resolve, 0)); });
  expect(read).toHaveBeenCalledTimes(2);
  expect(read).toHaveBeenLastCalledWith("generated.png");
  const metadata = result.messages[2].metadata!;
  expect(metadata.imageUrl).toBe("data:image/png;base64,AQI=");
  expect(metadata.downloadUrl).toBe(metadata.imageUrl);
  expect(metadata.artifactPath).toBe("");
  expect((result.messages[0] as any).attachments[0].imageUrl).toBe("");
});
it("reports an unavailable generated image and retries its fixed ID", async () => {
  read.mockRejectedValueOnce(new Error("oversize or unavailable")).mockResolvedValue("data:image/png;base64,AQI=");
  const generated = { id: "g", role: "assistant", metadata: { kind: "image2_generation", status: "succeeded", artifactId: "generated.png", imageUrl: "https://untrusted" } } as unknown as ConversationMessage;
  await setup([generated]);
  await rerender(["g"]);
  expect(result.failed).toBe(true);
  expect(result.messages[0].metadata?.imageUrl).toBe("");
  await act(async () => { result.retry(); await new Promise(resolve => setTimeout(resolve, 0)); });
  expect(result.failed).toBe(false);
  expect(result.messages[0].metadata?.imageUrl).toBe("data:image/png;base64,AQI=");
  expect(read).toHaveBeenCalledTimes(2);
});

it("retains a failed history notice during retry and prevents repeated reads while pending", async () => {
  let resolve!: (url: string) => void;
  read.mockRejectedValueOnce(new Error("unavailable"))
    .mockImplementationOnce(() => new Promise(done => { resolve = done; }));
  await setup([row(0)]);
  await rerender(["m0"]);
  expect(result.failed).toBe(true);
  await act(async () => result.retry());
  expect(result.failed).toBe(true);
  expect(result.pending).toBe(true);
  await act(async () => result.retry());
  expect(read).toHaveBeenCalledTimes(2);
  await act(async () => { resolve("data:image/png;base64,AQI="); await new Promise(done => setTimeout(done, 0)); });
  expect(result.failed).toBe(false);
  expect(result.pending).toBe(false);
  expect(read).toHaveBeenCalledTimes(2);
});

it.each(["succeeded", "failed"])("automatically reloads the same artifact after a %s read in the previous session", async outcome => {
  let resolveNext!: (url: string) => void;
  if (outcome === "succeeded") read.mockResolvedValueOnce("data:image/png;base64,OLD");
  else read.mockRejectedValueOnce(new Error("old session unavailable"));
  read.mockImplementationOnce(() => new Promise(resolve => { resolveNext = resolve; }));
  await setup([row(0)]);
  await rerender(["m0"]);
  expect(result.failed).toBe(outcome === "failed");
  expect(result.pending).toBe(false);

  await rerender(["m0"], undefined, { sessionId: "next" });
  expect(read).toHaveBeenCalledTimes(2);
  expect(read).toHaveBeenLastCalledWith("i0.png");
  expect(result.messages[0].attachments?.[0].imageUrl).toBe("");
  expect(result.failed).toBe(false);
  expect(result.pending).toBe(true);

  await act(async () => { resolveNext("data:image/png;base64,NEW"); await new Promise(resolve => setTimeout(resolve, 0)); });
  expect(result.messages[0].attachments?.[0].imageUrl).toBe("data:image/png;base64,NEW");
  expect(result.failed).toBe(false);
  expect(result.pending).toBe(false);
  expect(read).toHaveBeenCalledTimes(2);
});

it.each(["succeeded", "failed"])("discards a late %s read from the previous session while serializing the next read", async outcome => {
  let resolveOld!: (url: string) => void;
  let rejectOld!: (error: Error) => void;
  let resolveNext!: (url: string) => void;
  read.mockImplementationOnce(() => new Promise((resolve, reject) => { resolveOld = resolve; rejectOld = reject; }))
    .mockImplementationOnce(() => new Promise(resolve => { resolveNext = resolve; }));
  await setup([row(0)]);
  await rerender(["m0"]);
  expect(result.pending).toBe(true);
  await rerender(["m0"], undefined, { sessionId: "next" });
  expect(read).toHaveBeenCalledTimes(1);
  expect(result.messages[0].attachments?.[0].imageUrl).toBe("");

  await act(async () => {
    if (outcome === "succeeded") resolveOld("data:image/png;base64,OLD");
    else rejectOld(new Error("old session unavailable"));
    await new Promise(resolve => setTimeout(resolve, 0));
  });
  expect(read).toHaveBeenCalledTimes(2);
  expect(result.messages[0].attachments?.[0].imageUrl).toBe("");
  expect(result.failed).toBe(false);
  expect(result.pending).toBe(true);

  await act(async () => { resolveNext("data:image/png;base64,NEW"); await new Promise(resolve => setTimeout(resolve, 0)); });
  expect(result.messages[0].attachments?.[0].imageUrl).toBe("data:image/png;base64,NEW");
  expect(result.failed).toBe(false);
  expect(result.pending).toBe(false);
  expect(read).toHaveBeenCalledTimes(2);
});

it("clears cached attachments while disabled and reloads when enabled again", async () => {
  read.mockResolvedValueOnce("data:image/png;base64,OLD").mockResolvedValueOnce("data:image/png;base64,NEW");
  await setup([row(0)]);
  await rerender(["m0"]);
  await rerender(["m0"], undefined, { enabled: false });
  expect(read).toHaveBeenCalledTimes(1);
  expect(result.messages[0].attachments?.[0].imageUrl).toBe("");
  expect(result.failed).toBe(false);
  expect(result.pending).toBe(false);
  await rerender(["m0"], undefined, { sessionId: "next" });
  expect(read).toHaveBeenCalledTimes(1);
  await rerender(["m0"], undefined, { enabled: true });
  expect(read).toHaveBeenCalledTimes(2);
  expect(result.messages[0].attachments?.[0].imageUrl).toBe("data:image/png;base64,NEW");
  expect(result.failed).toBe(false);
  expect(result.pending).toBe(false);
});
