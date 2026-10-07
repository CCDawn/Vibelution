# International financial disclosures

`fetch_international_facets(stock)` supplies independent announcements and
fundamentals projections to `financial_research_service.stock_research`.
Mainland research keeps its existing sources. No transcript or report is stored.

HK announcements use HKEXnews; financial metrics use Eastmoney public reports,
including the actual reporting currency rather than the stock quote currency.
US disclosures and XBRL facts use SEC EDGAR. If SEC fundamentals fail, bounded
Eastmoney USF10 metrics are explicitly marked as a third-party fallback without
SEC verification; an announcement failure remains separately visible.

Reads have timeouts, response limits and source identity checks. Missing currency,
period or independently reported quarter values remain missing. Fiscal quarter
values are never silently replaced with year-to-date values. Sources, report and
filing dates, units and provider errors accompany every projection.

The adapters require no provider credentials or new dependencies. Fixtures test
normalization and failures; live provider availability is verified separately.

## A-share annual reports

`official_filings.py` looks up one cninfo annual-report PDF. Screening attaches
it when the announcement day is on or before the analysis date. The stock
overview list uses the same lookup with no date cutoff, puts that PDF first,
and drops East Money rows whose titles contain 年度报告. If no original is
found, those reprints are omitted and the list says so. Other notices stay on
East Money. The result is a title, announcement date, and
`static.cninfo.com.cn` URL. It is not a page number. Summaries and any other
host are left out. A lookup failure does not fail the screen or hide the
remaining notices.
