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

## A-share periodic reports

`official_filings.py` looks up cninfo periodic-report PDFs. Screening attaches
the annual, semi-annual, first-quarter, and third-quarter reports whose
announcement day is on or before the analysis date. A missing kind is omitted
from the screen payload. The stock overview list, with no date cutoff, shows
the latest annual report,
semi-annual report, first-quarter report, and third-quarter report, and drops
East Money rows for those reports. A missing original is named in the list and
its reprint is omitted. Other notices stay on East Money. Each result is a
title, announcement date, and `static.cninfo.com.cn` URL. It is not a page
number. Summaries and any other host are left out. A lookup failure does not
fail the screen or hide the remaining notices. The research prompt keeps a
dated public figure and adds the cninfo original for that same period
(31 March, 30 June, 30 September, or 31 December, same year, announced on
or after the period end and on or before the analysis date). Any other
period, year, or missing filing is 没有这一项 beside the figure. The figure
stays labeled as a snapshot. The read reuses the one-code screen lookup
and does not download the PDF.
