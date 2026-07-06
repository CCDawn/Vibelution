import { describe, expect, it } from "vitest";

import styles from "./ChatRuntimeNoticeStack.styles";
import source from "./ChatRuntimeNoticeStack.tsx?raw";

describe("ChatRuntimeNoticeStack layout contract", () => {
  it("renders runtime notices as an announced semantic list", () => {
    expect(source).toContain('role="status"');
    expect(source).toContain('aria-live="polite"');
    expect(source).toContain('role="list"');
    expect(source).toContain('role="listitem"');
    expect(source).toContain('<CircleDot size={13} aria-hidden="true" />');
  });

  it("wraps long runtime messages inside the notice body", () => {
    expect(styles.notice).toContain("min-w-0");
    expect(styles.body).toContain("min-w-0");
    expect(styles.message).toContain("break-words");
    expect(styles.message).toContain("[overflow-wrap:anywhere]");
  });
});
