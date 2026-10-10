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
and does not download the PDF. When a query page lacks one of the four
periodic report kinds and CNINFO says more results exist, the lookup reads
additional pages up to a four-page limit.

The shared issuer resolver requires the exact six-digit A-share code and
`A股` category. It accepts bounded CNINFO legacy, numeric, and `GD` identifiers;
opaque IDs do not determine the exchange. The existing A-share symbol normalizer
owns the `sse`/`szse`/`bj` directory selection. Conflicting legacy exchange prefixes
and ambiguous same-priority identities fail closed. Current listings take
precedence over delisted records. Historical PDF and cash-dividend queries reuse
this resolver; old Beijing security codes are not silently aliased.

## Historical research cutoff

An explicit analysis date is captured before stock-research loaders are sent to
the thread pool and is passed to each source adapter. News and announcement
items are shown only when `publishedAt` is parseable and on or before that date;
current and dated results use separate cache keys. The cutoff also reaches the
cninfo query's `seDate` range, so future reports are excluded at the source as
well as in the final projection. The projection copies the item list and never
removes rows from a shared cached response.

For historical requests, Eastmoney news and A-share notice search walk up to
eight source pages instead of filtering only the current first page. Those APIs
do not expose a verified as-of parameter; when the source total cannot be
exhausted within the page budget, or a returned publication date cannot be
parsed, the facet's `error` says the historical coverage is incomplete. A
returned `available` facet with that warning is a partial sample, not a claim
that the source contains every item published by the analysis date. HKEX
announcements receive the cutoff as the source-side `toDate`; reaching HKEX's
12-row result limit is also reported as incomplete coverage.

US announcement and financial-filing search use SEC Submissions `recent` plus
applicable `filings.files` archives until enough eligible filings are found. Archive paths, CIKs, accession
numbers, filing dates, response size, and the cutoff are checked before rows
are used. Archive reads are bounded to four files; a missing, invalid, failed,
or insufficient archive read is reported as incomplete coverage. More than 12
matching announcements also warns that only the latest 12 are shown.
The accession prefix may identify a third-party filing agent. Issuer identity
comes from the official archive index/path and an optional payload CIK, not
from requiring that prefix to equal the issuer's CIK.

Eastmoney's A-share and HK/US F10 summaries do not provide a trustworthy
point-in-time version history, so historical requests return those
fundamentals as unavailable instead of showing today's summary. US fundamentals
remain available only from SEC filings submitted on or before the cutoff and
facts tied to the selected filing accession. If SEC cannot provide those
historical fundamentals, the current Eastmoney fallback is not used.
Eligible `10-Q/A` and `10-K/A` filings are treated as revisions of their base
form. CompanyFacts matching accepts either the amendment form or its base form,
while requiring the amendment's own accession and excluding revisions filed
after the cutoff.
