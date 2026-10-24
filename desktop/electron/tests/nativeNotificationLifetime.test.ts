import { EventEmitter } from "node:events";
import { expect, it } from "vitest";
import { NativeNotificationLifetime } from "../src/notifications/nativeNotificationLifetime.js";

it("keeps popup timeouts clickable while releasing completed and failed delegates", () => {
  const lifetime = new NativeNotificationLifetime();
  const notification = new EventEmitter();
  lifetime.retain(notification);
  notification.emit("close", {}, "timedOut");
  expect(lifetime.size).toBe(1);
  notification.emit("click");
  expect(lifetime.size).toBe(0);
  lifetime.retain(new EventEmitter().once("test", () => undefined));
  const failed = new EventEmitter();
  lifetime.retain(failed);
  failed.emit("failed");
  expect(lifetime.size).toBe(1);
});

it("bounds retained notification history", () => {
  const lifetime = new NativeNotificationLifetime(2);
  const oldest = new EventEmitter();
  lifetime.retain(oldest);
  lifetime.retain(new EventEmitter());
  lifetime.retain(new EventEmitter());
  expect(lifetime.size).toBe(2);
  oldest.emit("click");
  expect(lifetime.size).toBe(2);
});
