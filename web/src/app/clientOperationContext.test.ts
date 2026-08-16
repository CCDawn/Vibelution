import { afterEach, describe, expect, it } from "vitest";

import {
  CLIENT_OPERATION_ID_HEADER,
  currentClientOperationId,
  popClientOperationContext,
  pushClientOperationContext,
  resetClientOperationContextForTests,
} from "./clientOperationContext";

describe("clientOperationContext", () => {
  afterEach(() => {
    resetClientOperationContextForTests();
  });

  it("tracks nested client operation ids in stack order", () => {
    pushClientOperationContext("session_create-1");
    pushClientOperationContext("session_delete-2");
    expect(currentClientOperationId()).toBe("session_delete-2");
    popClientOperationContext();
    expect(currentClientOperationId()).toBe("session_create-1");
    popClientOperationContext();
    expect(currentClientOperationId()).toBe("");
  });

  it("exports the request header name", () => {
    expect(CLIENT_OPERATION_ID_HEADER).toBe("X-Vibelution-Client-Operation-Id");
  });
});
