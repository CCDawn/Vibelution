# Financial report export helpers

`financial_report_service.py` is the public facade. It authorizes the financial Agent and exact native Session/Turn, requires a successful completed research Turn, and returns bounded export data without creating a second report store.

This pack owns read projections and format rendering:

- `formats.py` renders Markdown as escaped standalone print HTML and dependency-free OOXML DOCX.
- `catalog.py` projects individual successfully completed native Turns, with market/date/title/code/preview filters and bounded session scanning. Its cursor retains the complete native directory cursor (including pinned-row tokens) and the report offset within a session; order follows session activity, not a global report completion timeline.
- JSON and Markdown are assembled by the facade from the canonical `final_answer`. Every export format then applies the conclusion check: an amount stays only when it is on a cited filing page or a program-checked calculation, otherwise it is shown as 没有这一项. The stored Turn is not rewritten.
- The `pdf` option returns sandbox-ready print HTML. The browser print dialog is responsible for saving it as PDF; the API never claims to generate a PDF file.

Raw assistant HTML is always escaped. Export sizes are bounded at both the service and browser-adapter boundaries.

Batch export reuses the same exact-Turn authorization and validation for every
member. It accepts at most 20 distinct reports, limits uncompressed content to
8 MB, and returns a ZIP in memory. Reports and ZIP packages are not persisted.
