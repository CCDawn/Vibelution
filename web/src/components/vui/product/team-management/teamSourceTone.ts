import type { VuiTone } from "../../index";

/** Domain tone used by source-collection result rows and candidate cards. */
export type TeamSourceResultTone = "ready" | "warning" | "danger" | "neutral";

/** Map domain status tone onto the stable VUI chip tone contract. */
export function teamSourceResultToneToVuiTone(tone: TeamSourceResultTone): VuiTone {
  if (tone === "ready") {
    return "success";
  }
  if (tone === "warning") {
    return "warning";
  }
  if (tone === "danger") {
    return "danger";
  }
  return "neutral";
}
