# Desktop stock agent

The approved reference is TradingAgents-CN v3.0 community at `51060a7682cf51810b4bc3a704829438d18cd8dc`. Its application source has restricted Source Available terms. This implementation independently adapts capabilities and information architecture; it does not copy application code. Desktop acceptance covers 1280px and 1920px windows.

## Workspace and native authority

- `FinanceResearchFrame` owns the existing three-column VUI shell without a duplicate header. `WORKBENCH_LAYOUT_IDS.finance` and shared pane persistence own resizing, collapse and widths. Each pane shrinks within the desktop container; collection pages scroll in the center pane.
- `FinanceResearchWorkspace` composes stock/topic research, analyst collaboration, screening, watchlist quotes, reports, tasks, paper trading, portfolio research, review, memory, skills and learning. Watchlist preferences store validated identities only, never quotes or transcripts.
- `FinancialResearchBridge` commits the exact draft to the native composer before requesting native submission. Journal, native worker, SSE, message projection, stop and HTML export remain authoritative. Finance writes no second transcript and simulates no execution progress.
- `FinanceSessionMenu` and `useFinanceSessionLifecycle` reuse native archive, unarchive, deletion, cache invalidation and deletion tombstones. `FinanceRoute` keeps lifecycle reconciliation mounted while a direct binding changes. Running records fail closed. Delete uses standard VUI confirmation. Removing the viewed research selects only a verified surviving Session of the same Agent; late results do not override navigation. The native archive's missing task summary is rendered as an empty preview.
- The archive collection reads the native paginated index and filters by Agent. Archived records open in native read-only chat. `FinanceRoute` preserves an archived direct binding with `directSessionArchived` and offers native restore or a new research without cloning the Agent.
- Native deletion can empty the direct pointer. The pure projection reports `session_missing`; the explicit serialized financial setup POST reuses `ensure_agent_direct_session` for that same existing Agent. Existing archived or foreign pointers are never silently repaired. The lifecycle reads back the owner before repairing, so deleting the final direct research leaves an accessible workspace.

## Research and evidence

Stock and topic requests carry an actual date, period, scope and five depth levels. New full research uses a separate native Session. Reports derive only from completed canonical `final_answer` items; thinking, stopped turns and unrelated follow-ups do not replace a full report. Topic reports are independent of stock selection. Citations preserve PDF identity/page and match active sources in the same Agent-owned library.

Report search uses native `querySessions(q)` over titles and bodies. Outcome filters and task counts apply to loaded records, not an invented global count. Native `ready` is idle, not proof of success. Terminal metadata distinguishes completion, stop, failure and continuation. Empty unpersisted placeholders and deletion tombstones are excluded.

`FinanceAnalystTeam` uses five separate native Agents: market, fundamentals, news, bull and bear. Three primary reports feed two opposing reviews, then the financial owner synthesizes. Runs store only Session/Turn/submission references and stage metadata; answers remain in native Sessions. Roles derive narrow authorized tools/model from the owner. Identity, permission and Session ownership drift fail closed. Stops target the exact Turn. Unknown acceptance is read back before retry. Analyst links explicitly use native chat rather than bypassing the financial binding guard.

After explicit primary submissions are accepted, a finance-scoped coordinator reuses the native RuntimeTaskStore and managed web startup jobs to advance debate and synthesis while the page is closed. Startup recovers accepted runs without sending their known Turns again. Waiting/running status polls the persisted run projection; completed requires the exact synthesis final answer, and blocked surfaces the reason without automatic resubmission. Legacy runs without coordination status retain the existing client orchestration. GET does not create or start a run.

The team inspector follows the selected run rather than the assistant Session's historical title. It displays saved submission references and coordinator state; completion also requires all analyst and synthesis Turn references. Cards adapt to the actual desktop center-pane width with a single grid template, so later route utility chunks cannot override responsive column variants.

## Public market data

The existing Tencent adapter owns A-share quotes and adjusted day/week/month candles. Provider, quote/fetch times, yuan/lot units and missing values stay explicit. MA5/20, BOLL(20,2), MACD(12,26,9) and Wilder RSI(14) calculate on all loaded candles before slicing; missing warm-up values are never generated.

`financialResearch` owns bounded batch quotes, provider screening, news, announcements and fundamentals. The Sina universe is provider coverage, not complete exchange coverage. Partial pages/deadlines stay visible. Unknown market-cap units remain null; unavailable filters are omitted. A source time without a date is not a fabricated data date. Cache hits preserve source fetch time. Natural-language screening prepares real native research, not an AI result before model execution.

Public fundamentals are source snapshots, not verified PDF evidence. `FinanceReportLibrary` uses shared knowledge APIs with exact Agent/library identity and active owned sources. Intake/deletion stay in the existing knowledge workspace. Untrusted source text is plain data; external links use validated HTTP/HTTPS URLs.

## Paper account and portfolio

`financialPaper` owns a private Agent-scoped virtual ledger. GET never opens an account; explicit creation seeds RMB 1,000,000. Server-read public quotes, integer A-share lots, cash/holding checks, declared fees and Beijing calendar-day T+1 govern simulated orders. Client idempotency keys and synchronous UI gates prevent duplicate writes. These declared simulation rules do not provide an exchange calendar or broker connection.

Holdings use one bounded quote batch instead of candles per position. Unavailable quotes may retain the actual prior transaction quote with a visible stale/partial mark. Reviews use recorded trades/monthly aggregates, not invented historical NAV. AI review prepares a draft containing the actual ledger in a separate native topic Session, retaining existing stock reports.

`financialPortfolio` reuses the ledger and public data for holdings weights, cash allocation, concentration and bounded return correlations. Missing prices and insufficient overlapping candles remain missing. Portfolio research prepares a source-bearing draft in a separate native topic Session; it adds no account, backtest or portfolio writer. An unopened account has an explicit link to the existing paper-account setup instead of a retry dead end.

## Memory, skills and learning

`financialPreferences` stores validated preferences in the same Agent's native episodic personal memory with UUID references and bounded input. The runtime owns its loading window; saving does not guarantee inclusion in every Turn. Disabled memory rejects writes. Private data uses the same Agent/actor ACL.

Skills come from the installed native library and use slash commands. Native submission loads actual local skill body/version. Learning provides independently written five lessons, eight guides and checks; exercises prepare the real composer. No reference course prose is copied.

## Scope and verification

The surface targets desktop A-share community research. Broker trading, Pro strategy automation, scheduled/batch analysis and Word/PDF export are outside the implementation. Markdown/native HTML export remains. ETF, Hong Kong and US support is not implied by the reference name.

Verification uses domain/native lifecycle tests, VUI/API contracts, TypeScript/production build and isolated Launcher/browser acceptance with confirmed instance/code identity. Provider HTTP success does not prove exchange-grade realtime data; model configuration does not prove successful research.

Runtime diagnostics reuse native archive/delete, Turn and episodic-memory events. Finance adds bounded direct-binding repair and paper-account/order events, with stable IDs and outcomes; prompts, preference text, transaction reasons and report bodies are excluded. Public read-only data and visual projections add no persistence events.
