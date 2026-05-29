import { describe, expect, it } from "vitest";

import { resolveLegacyChatRoomsRedirect } from "./LegacyChatRoomsRedirect";
import routerSource from "../app/router.tsx?raw";

describe("LegacyChatRoomsRedirect", () => {
  it("keeps /chat-rooms as a compatibility redirect into the chat workspace", () => {
    expect(resolveLegacyChatRoomsRedirect("")).toBe("/chat");
    expect(resolveLegacyChatRoomsRedirect("?room=room-123")).toBe("/chat?room=room-123");
    expect(resolveLegacyChatRoomsRedirect("?room=room id")).toBe("/chat?room=room%20id");
  });

  it("does not mount the obsolete ChatRoomsRoute as a second group-chat workspace", () => {
    expect(routerSource).toContain('path: "chat-rooms"');
    expect(routerSource).toContain("<LegacyChatRoomsRedirect />");
    expect(routerSource).not.toContain("ChatRoomsRoute");
  });
});
