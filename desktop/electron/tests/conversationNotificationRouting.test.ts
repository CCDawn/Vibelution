import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import ts from "typescript";
import { expect, it, vi } from "vitest";

it("replaces the sender's notification service when its registered origin changes", () => {
  const source = readFileSync(new URL("../src/main.ts", import.meta.url), "utf8");
  const start = source.indexOf("function resolveConversationNotificationService(");
  const end = source.indexOf("\nfunction resolveHumanAttentionNotificationService", start);
  const target = { origin: "http://127.0.0.1:8001" };
  const createService = vi.fn(({ windowProvider }) => ({ target: { ...windowProvider } }));
  const resolver = runInNewContext(ts.transpileModule(source.slice(start, end), {
    compilerOptions: { target: ts.ScriptTarget.ES2022 }
  }).outputText + "\nresolveConversationNotificationService", {
    URL,
    windowProvider: { notificationTargetForSender: () => ({ ...target }) },
    workbenchNotificationServices: new WeakMap(),
    createConversationNotificationService: createService,
    createConversationBadgeIcon: vi.fn(),
    IPC_CHANNELS: { conversationNotificationOpened: "opened" }
  });
  const sender = {};
  const event = () => ({ sender, senderFrame: { url: target.origin } });
  const first = resolver(event());
  expect(resolver(event())).toBe(first);
  target.origin = "http://127.0.0.1:8002";
  const replacement = resolver(event());
  expect(replacement).not.toBe(first);
  expect(replacement.target.origin).toBe(target.origin);
  expect(first.target.origin).toBe("http://127.0.0.1:8001");
  expect(createService).toHaveBeenCalledTimes(2);
});
