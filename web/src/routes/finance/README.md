# Desktop stock research

The approved reference is TradingAgents-CN v3.0 at `51060a7682cf51810b4bc3a704829438d18cd8dc`, specifically its stock detail, single-analysis, reports and favorites surfaces. Its frontend is restricted Source Available: this implementation borrows information architecture only, and uses existing VUI APIs throughout. The user explicitly requested desktop only; there is no mobile layout or mobile acceptance scope.

- `FinanceResearchFrame` owns the desktop three-column shell; `WORKBENCH_LAYOUT_IDS.finance` owns persisted widths and VSplitWorkspace provides resizing/collapse.
- `FinanceResearchWorkspace` composes stock search, selected-stock overview, watchlist preferences, native research and report history. Preferences store only validated stock identities, never market data or transcripts.
- `financialMarket` API → `financial_assistant` route → `financial_market_service` reads Tencent public A-share quotes and OHLC. It preserves quote time, provider, yuan and lot units, and fails visibly. There are no account or order endpoints.
- `FinancialResearchBridge` prepares a native composer draft and optionally requests native submission after that exact draft commits. Native Session, Journal, worker and SSE remain all conversation authorities. The live projection subscribes to the existing active-turn store at the presentation edge.
- `stockResearchModel` renders completed canonical final-answer items as a report and uses their original questions to keep stock context. It never turns reasoning, commentary or tool output into a report. Report chapters reflect actual answer headings.
- `FinanceReportLibrary` links a selected citation to active, owned source metadata and the original PDF page. Library text remains plain untrusted data.

Research configuration changes the actual native request: stock, as-of date, report period, research scope and answer depth. It does not claim unsupported analyst orchestration, screening, trading, portfolio simulation or Pro-only automation.

Verification includes market parser/HTTP tests, finance entry/bridge/library/report projections, VUI and layout contracts, TypeScript/build and isolated desktop browser acceptance. A public provider read does not prove exchange-grade real-time data.
