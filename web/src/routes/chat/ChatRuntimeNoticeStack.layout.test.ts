import { describe, expect, it } from "vitest";

import styles from "./ChatRuntimeNoticeStack.styles";
import source from "./ChatRuntimeNoticeStack.tsx?raw";

describe("ChatRuntimeNoticeStack layout contract", () => {
  it("renders runtime notices as an announced semantic list", () => {
    expect(source).toContain('role="status"');
    expect(source).toContain('aria-live="polite"');
    expect(source).toContain('role="list"');
    expect(source).toContain('role="listitem"');
    expect(source).toContain("VErrorSummary");
    expect(source).toContain("summarizeErrorText");
    expect(source).toContain('<CircleDot size={13} aria-hidden="true" />');
  });

  it("uses compact VUI error summaries for alert and long notices", () => {
    expect(source).toContain("runtimeNoticeIsAlert(notice.level)");
    expect(source).toContain("summarizeErrorText(message");
    expect(source).toContain('openLabel={lang === "zh" ? "详情" : "Details"}');
    expect(styles.summaryItem).toContain("min-w-0");
    expect(styles.stack).toContain("bg-transparent");
    expect(styles.stack).toContain("shadow-none");
  });

  it("wraps long runtime messages inside the notice body", () => {
    expect(styles.notice).toContain("min-w-0");
    expect(styles.body).toContain("min-w-0");
    expect(styles.message).toContain("break-words");
    expect(styles.message).toContain("[overflow-wrap:anywhere]");
  });
});
