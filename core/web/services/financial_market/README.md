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

The adapter only reads public Tencent endpoints. An endpoint response that is
missing, malformed, or has an unrecognized time/currency format is unavailable;
the parser does not synthesize quote values or relabel raw bars as adjusted.
