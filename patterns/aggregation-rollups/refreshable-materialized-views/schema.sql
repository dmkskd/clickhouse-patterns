-- Your executed trades, versioned so amendments and cancellations dedup to the
-- latest row per trade. FINAL (used by the view) keeps the highest version.
CREATE DATABASE IF NOT EXISTS demo;

CREATE TABLE demo.trades
(
    trade_id  UInt64,
    symbol    String,
    side      Int8,        -- +1 buy, -1 sell
    qty       UInt32,
    price     Float64,
    version   UInt64,      -- higher wins on dedup
    cancelled UInt8 DEFAULT 0
)
ENGINE = ReplacingMergeTree(version)
ORDER BY trade_id;

-- Latest price per symbol, updated continuously by a price feed. The row with
-- the newest ts wins. This is the price each position is valued at.
CREATE TABLE demo.prices
(
    symbol String,
    price  Float64,
    ts     DateTime
)
ENGINE = ReplacingMergeTree(ts)
ORDER BY symbol;

-- The revaluation, recomputed on a schedule. Unlike an insert-triggered view,
-- this reruns a full query every refresh, so it can dedup trades with FINAL and
-- JOIN to the prices table. Positions come from the deduped book; each is valued
-- at the current price, so unrealized P&L moves whenever a price changes even
-- though no trade was booked. A real deployment would refresh every minute or
-- few minutes; 5s here keeps the test fast. Without APPEND, each refresh
-- atomically replaces the whole result.
CREATE MATERIALIZED VIEW demo.position_pnl
REFRESH EVERY 5 SECOND
ENGINE = MergeTree ORDER BY symbol
AS
WITH
    positions AS
    (
        SELECT
            symbol,
            sum(toInt64(side) * toInt64(qty))         AS position,
            sum(toInt64(side) * toInt64(qty) * price) AS cost_basis
        FROM demo.trades FINAL
        WHERE cancelled = 0
        GROUP BY symbol
    ),
    latest_prices AS
    (
        SELECT symbol, price
        FROM demo.prices FINAL
    )
SELECT
    symbol,
    position,
    cost_basis,
    price,
    position * price              AS market_value,
    position * price - cost_basis AS unrealized_pnl
FROM positions
INNER JOIN latest_prices USING (symbol);
