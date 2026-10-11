# Financial report export helpers

`financial_report_service.py` is the public facade. It authorizes the financial Agent and exact native Session/Turn, requires a successful completed research Turn, and returns bounded export data without creating a second report store.

This pack owns read projections and format rendering:

- `validation.py` owns explicit report-claim rules and outcome/confirmed-lesson metadata in the same Agent's private territory. It binds a successful native report without copying its body, distinguishes prospective from retrospective claims, checks two completed closes from one qfq snapshot, and retains evidence hashes. The existing managed financial-job lifecycle performs bounded due checks. Native topic Sessions remain the only AI review transcript; confirmed lessons use canonical episodic memory and are read by subsequent same-stock research only after their evidence date.
- `backtest.py` owns a pure MA long/cash indicator strategy using the latest 120 CN qfq daily bars. Signals use the completed close and execute at the next open; strategy and buy-and-hold benchmark share costs/slippage. It rejects insufficient coverage/warm-up and does not write paper orders. Fractional adjusted units, present-day adjusted data and missing exchange/corporate-action execution rules limit it to indicator research, not point-in-time AI performance or live trading simulation.

- `formats.py` renders Markdown as escaped standalone print HTML and dependency-free OOXML DOCX.
- `catalog.py` projects individual successfully completed native Turns, with market/date/title/code/preview filters and bounded session scanning. Its cursor retains the complete native directory cursor (including pinned-row tokens) and the report offset within a session; order follows session activity, not a global report completion timeline.
- JSON and Markdown are assembled by the facade from the canonical `final_answer`. Every export format then applies the conclusion check: an amount stays only when it is on a cited filing page or a program-checked calculation, otherwise it is shown as 没有这一项. A canonical screening request with successful `financial_market_screen_tool` results projects each distinct filter batch separately, showing its actual thresholds, source time, match count, returned count, truncation, and candidate rows. A retry is deduplicated only when its complete request (filters, sort, direction, page and limit) and source snapshot match; the latest payload for that exact request is kept. Different request windows, filters or snapshots are never merged into one candidate set. If the result omits its requested filters, the batch renders them from the original tool input. Each row is a tool candidate. The filing-page cell comes only from a same-turn `financial_evidence_search_tool` call for that ticker. The announcement cell comes only from that screen result's `officialFiling` when it is an allowlisted cninfo or exchange annual-report PDF on or before the analysis date. Otherwise either cell is 没有这一项. Quote fields are omitted. An empty or analysis-date-cleared screen does not keep model-invented candidates. No usable screen payload leaves the answer unchanged. When candidate rows are usable, the canonical final answer remains visible under 模型正文（未经工具候选校验）. The stored Turn is not rewritten.
- The `pdf` option returns sandbox-ready print HTML. The browser print dialog is responsible for saving it as PDF; the API never claims to generate a PDF file.

Raw assistant HTML is always escaped. Export sizes are bounded at both the service and browser-adapter boundaries.

`team_evidence.py` adds read-only original tool records to an owner-scoped
multi-analyst summary. It resolves the exact summary Session/Turn to one of at
most 40 runs, rechecks current team/role permissions, and verifies each native
role's owner, submission ID, successful terminal and committed final answer.
Only role Turns completed strictly before summary submission can contribute;
equal timestamps cannot prove ordering. The active Journal branch, latest
committed answer revision and latest outcome for each original tool call are
used. Provisional/nonterminal answers and failed items cannot contribute. Ordinary
reports and legacy summaries without this source binding retain same-Turn
grounding. Missing or changed provenance fails closed without modifying the
Journal or blocking export.

Borrowed PDF excerpts require the run's ticker, an explicitly cited exact source
URL and report period, valid original-PDF metadata including an exact excerpt
hash match, and publication no later than
the research date. Market snapshots require the run's exact symbol and a dated
quote on or before that date, then pass the existing quote/calculation checks.
Analyst opinions, news prose and public fundamentals summaries do not authorize
numbers. Truncated excerpts whose original hash cannot be verified are rejected.
Each tool output is bounded to 32,000 characters and combined borrowed
records to 60. Duplicate observations are folded; conflicting page excerpts or
quote observations cannot authorize either version's numbers. Quote conflicts
compare the full quote and stock/source/market/currency/unit metadata; different
K-line request windows, candle errors, transport status and fetch times do not
erase an otherwise identical quote. The original candle records remain separate:
calculations still require one unambiguous complete snapshot, with no merging or
selection of a preferred analyst's candle window. All export formats
and report catalog previews use the same projection. No external project code
is copied and no second evidence/report store is created.

Before an A-share team synthesis is submitted, that same pack also projects
bounded source references from the exact market, fundamental, and news analyst
Turns into the synthesis prompt. It requires a completed active-branch Turn,
the bound Agent and submission ID, and the run's exact A-share code and research
date. Market quotes must be for that code and on or before the cutoff. News is
passed only when the rendered result has a structured `news` source, a parseable
publication date on or before the cutoff, and the issuer name matches the title
or snippet; mentioning a six-digit code alone is insufficient. Financial report
query output must carry the exact ticker and report period, but remains marked
untrusted because it supplies no publication date and only checks citation
structure. The run's public-fundamentals snapshot is a separate, explicitly
unverified reference; its same-period CNINFO link does not establish that the
displayed value matches the PDF or that the value was preserved point in time.
All references stay inside the existing untrusted-materials JSON boundary,
carry truncation notices, and are read-only. This prompt context does not expand
the export rule: conclusion amounts still require a cited original-PDF excerpt
or a deterministic calculation, and the stored Session/Journal is unchanged.

Same-Turn `financial_market_snapshot_tool` results also verify raw share-price,
signed change-percent and PE/PB occurrences by their exact fields. A report with
one unambiguous stock and quote observation may reuse its labelled quote date
and source paragraph, so dated close summaries remain readable. Wrong dates,
currencies, other stocks, forecasts, field collisions and arithmetic are not
authorized by that quote. Price ranges and derived returns still require their
own evidence; source-provided PE/PB values do not verify their calculation basis.

The report projection can also recompute explicitly named MA5/MA10/MA20 values
from daily `close` rows, plus a close-to-close return whose start and end dates
are both named. It accepts only one successful same-Turn snapshot containing
the full requested candle window, with a matching stock, Tencent source, quote
date in the declared market time zone, currency, daily period and market
adjustment (`qfq` for CN; `raw` for HK/US), and at most 120 valid candles. Older
candles omitted by the tool's requested limit are allowed; output-length
trimming, analysis-date filtering and candle errors are not.
Moving averages use the latest N closes ending on the quote date. Date-range
returns use `(end close / start close - 1) × 100`; displayed amounts are checked
to at most two decimal places with `ROUND_HALF_UP`. Each matching conclusion
occurrence is verified independently. Incomplete request windows, missing
endpoint dates, ambiguous multi-stock context, forecasts, box ranges and fuzzy
periods such as “近30天” do not authorize values. The provider's rows are
checked for valid unique ascending dates and consistent tool counts; no
exchange calendar is inferred, so this does not prove that a provider omitted
no trading session.

An MA claim may include an immediately following parenthetical recomputation
note. The note's date tokens are exempt from the quote-date check only when it
explicitly lists trading dates and close prices, uses calculation/recalculation
wording, and its ordered dates exactly match the snapshot's final N rows.
Month/day abbreviations require a leading ISO date to anchor a same-year
window; every date must be ISO when the window crosses a year boundary. Any
other date in the claim remains subject to the quote-date check, and the note's
input closes, total, and unrounded mean are not independently authorized.

Batch export reuses the same exact-Turn authorization and validation for every
member. It accepts at most 20 distinct reports, limits uncompressed content to
8 MB, and returns a ZIP in memory. Reports and ZIP packages are not persisted.

`sector_evidence.py` whitelists optional current Eastmoney sector references
from the same guarded market-role snapshot. Classification observation must be
on the research day; a past stock quote never proves historical membership.
Provider taxonomy, board points, peer CNY/share and independent source times
remain separate. Exact stock/board source URLs, canonical identities and finite
values are checked; malformed optional context leaves the stock reference
intact. These are untrusted synthesis references, not verified filing values.
Concepts and historical membership remain unavailable, and no synchronized
close, fund flow or rotation is inferred. Session/Journal writing is unchanged.
