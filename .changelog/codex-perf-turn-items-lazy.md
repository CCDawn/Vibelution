# perf(session): bound historical turn-item bodies and load them on demand

Detail payloads for long sessions were dominated by `turnItems` text: one 35.9 MB
journal produced a 10.4 MB detail response in which reasoning bodies alone were
4.8 MB. The transcript renders those bodies collapsed, so most of that payload
was bytes the reader never expanded.

- Projection now bounds `reasoning.text` (400 chars) and `tool_call.input` /
  `output` (800 chars) for every turn except the newest three, tagging the item
  with `contentTruncated` / `contentLength` / `boundedFields`.
- `GET /api/sessions/{id}/turns/{turnId}/items/{itemId}` re-projects one turn at
  full length so an expanded disclosure can fetch the canonical body.
- The web transcript passes the canonical item id down to the reasoning cell and
  fetches the full body only when the reader opens it; a failed fetch keeps the
  bounded preview instead of blanking the disclosure.

Recent turns stay complete, so the live view and newly settled turns never pay a
second round trip. Cache entries added earlier stay keyed on the journal
signature and are skipped when the signature has no path.
