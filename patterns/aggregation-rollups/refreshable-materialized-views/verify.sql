-- The revalued book after the refresh. Positions are deduped to the latest
-- trade version (BTC 125, not 150; trade 4 cancelled), and each is valued at the
-- moved price (BTC 101, ETH 99), so unrealized P&L reflects a price move that
-- happened with no trade.
SELECT symbol, position, cost_basis, price, market_value, unrealized_pnl
FROM demo.position_pnl
ORDER BY symbol;
