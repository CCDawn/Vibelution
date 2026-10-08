/** Keep user-authored lessons and result notices inside the reference boundary. */
export function evaluationReferenceBlock(value: unknown): string {
  const json = JSON.stringify(value).replace(/UNTRUSTED_REFERENCE_MATERIALS_JSON_(BEGIN|END)/g, marker => marker.replace("JSON", "\\u004aSON"));
  return `UNTRUSTED_REFERENCE_MATERIALS_JSON_BEGIN\n${json}\nUNTRUSTED_REFERENCE_MATERIALS_JSON_END`;
}
