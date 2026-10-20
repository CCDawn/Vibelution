# Financial market data adapter

`tencent.py` owns Tencent's symbol conventions, field parsing, unit mapping, and
market-local timestamp parsing. `financial_market_service.py` remains the
service facade for bounded caching, request throttling, and the HTTP routes.

Canonical symbols are `sh600519` / `sz000001` / `bj430001` for CN, `hk00700`
for HK, and `usAAPL` for US. Quote prices are per share in their native
currency. The normalized `volume` field is shares; legacy `volumeLots`,
`turnoverYuan`, and `totalMarketCapYuan` retain their CN-only meanings and are
null for HK/US. HK/US daily bars are returned as raw bars because Tencent
returns no adjusted-series key for those markets; CN bars remain forward
adjusted (`qfq`).

Read-only listed ETF identifiers include `sh510300`, `sh510500`, `sh510880`
and `sz159915` (bare six-digit ETF codes resolve to the correct exchange).
ETF prices and normalized volume refer to fund units; the shared `share`
wire fields represent units and legacy lots are 100 units. Tools label those
units explicitly. Stock PE/PB/market-cap fields are null for ETFs. Public
quote support does not extend stock-only paper-ledger admission, quantity or
fee rules: `normalize_a_share_symbol` keeps the original stock allowlist.

The adapter only reads public Tencent endpoints. An endpoint response that is
missing, malformed, or has an unrecognized time/currency format is unavailable;
the parser does not synthesize quote values or relabel raw bars as adjusted.

`indices.py` owns the fixed A-share benchmark set and its independent Tencent
index parser. Index daily bars are raw index points, not stock qfq data. Its
historical mode sends the requested end date upstream and rejects any later
row locally; unverified index volume and turnover fields are never exposed.

`sectors.py` adds current-only A-share sector context from Eastmoney public
quotes. It exposes Eastmoney's vendor industry label, maps it to a board only
when the complete industry directory has one exact name match, and validates
the board timestamp (`f86`) and each peer timestamp (`f124`) independently.
The label is observed at fetch time; the stock quote time (`f124`) is not
historical industry-membership evidence. Non-current cutoffs make no request.
Concept coverage and historical board/constituent coverage remain explicitly
unavailable; current members must not be used as a backtest universe.
