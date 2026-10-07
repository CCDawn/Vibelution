# Financial report export helpers

`financial_report_service.py` is the public facade. It authorizes the financial Agent and exact native Session/Turn, requires a successful completed research Turn, and returns bounded export data without creating a second report store.

This pack owns read projections and format rendering:

- `formats.py` renders Markdown as escaped standalone print HTML and dependency-free OOXML DOCX.
- `catalog.py` projects individual successfully completed native Turns, with market/date/title/code/preview filters and bounded session scanning. Its cursor retains the complete native directory cursor (including pinned-row tokens) and the report offset within a session; order follows session activity, not a global report completion timeline.
- JSON and Markdown are assembled by the facade from the canonical `final_answer`. Every export format then applies the conclusion check: an amount stays only when it is on a cited filing page or a program-checked calculation, otherwise it is shown as 没有这一项. A canonical screening request that has a usable `financial_market_screen_tool` result also projects a comparison table. Each row is a tool candidate. The filing-page cell comes only from a same-turn `financial_evidence_search_tool` call for that ticker. The announcement cell comes only from that screen result's `officialFiling` when it is an allowlisted cninfo or exchange annual-report PDF on or before the analysis date. Otherwise either cell is 没有这一项. Quote fields are omitted. An empty or analysis-date-cleared screen does not keep model-invented candidates. No usable screen payload leaves the answer unchanged. The stored Turn is not rewritten.
- The `pdf` option returns sandbox-ready print HTML. The browser print dialog is responsible for saving it as PDF; the API never claims to generate a PDF file.

Raw assistant HTML is always escaped. Export sizes are bounded at both the service and browser-adapter boundaries.

Same-Turn `financial_market_snapshot_tool` results also verify raw share-price,
signed change-percent and PE/PB occurrences by their exact fields. A report with
one unambiguous stock and quote observation may reuse its labelled quote date
and source paragraph, so dated close summaries remain readable. Wrong dates,
currencies, other stocks, forecasts, field collisions and arithmetic are not
authorized by that quote. Price ranges and derived returns still require their
own evidence; source-provided PE/PB values do not verify their calculation basis.

Batch export reuses the same exact-Turn authorization and validation for every
member. It accepts at most 20 distinct reports, limits uncompressed content to
8 MB, and returns a ZIP in memory. Reports and ZIP packages are not persisted.
