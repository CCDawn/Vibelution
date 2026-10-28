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
let rerender: (ids: string[], messages?: ConversationMessage[]) => Promise<void>;
const row = (n: number) => ({ id: `m${n}`, role: "user", content: "", attachments: [{ artifactId: `i${n}.png`, kind: "user_image", url: "/old", imageUrl: "/old", downloadUrl: "/old" }] }) as unknown as ConversationMessage;
afterEach(async () => { if (root) await act(async () => root.unmount()); document.body.innerHTML = ""; vi.clearAllMocks(); });
async function setup(initial: ConversationMessage[]) {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  const div = document.createElement("div"); document.body.append(div); root = createRoot(div);
  let messages = initial;
  function Harness({ ids, rows }: { ids: string[]; rows: ConversationMessage[] }) { result = useLauncherAttachmentHistory(rows, "s", true, ids); return null; }
  rerender = async (ids, next) => { messages = next || messages; await act(async () => { root.render(createElement(Harness, { ids, rows: messages })); await new Promise(resolve => setTimeout(resolve, 0)); }); };
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
