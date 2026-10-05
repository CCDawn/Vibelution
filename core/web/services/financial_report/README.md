# Financial report export helpers

`financial_report_service.py` is the public facade. It authorizes the financial Agent and exact native Session/Turn, requires a successful completed research Turn, and returns bounded export data without creating a second report store.

This pack owns only format rendering:

- `formats.py` renders Markdown as escaped standalone print HTML and dependency-free OOXML DOCX.
- JSON and Markdown are assembled by the facade from the canonical `final_answer`.
- The `pdf` option returns sandbox-ready print HTML. The browser print dialog is responsible for saving it as PDF; the API never claims to generate a PDF file.

Raw assistant HTML is always escaped. Export sizes are bounded at both the service and browser-adapter boundaries.
