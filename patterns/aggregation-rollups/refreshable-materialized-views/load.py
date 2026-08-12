"""Build a small book, then change the world around it in ways an insert-triggered
view could not absorb, and let the scheduled refresh recompute from raw.

  1. book trades:   BTC long 150, ETH short 50, all at 100
  2. initial prices: BTC 100, ETH 100  -> unrealized P&L is zero
  3. move prices:    BTC 100->101, ETH 100->99  (NO new trades)
  4. amend + cancel: correct one BTC trade (20 -> 25) and cancel another (-30)

The refresh reads demo.trades FINAL (latest version per trade, cancels excluded)
joined to demo.prices FINAL (latest price), so the final valuation reflects both
the moved prices and the amended book. Step 3 is the point: P&L moves with no trade.
"""
from datetime import datetime

from pattern_explorer.orchestration.nodes import connect

ch = connect("ch")

TRADE_COLS = ["trade_id", "symbol", "side", "qty", "price", "version", "cancelled"]
PRICE_COLS = ["symbol", "price", "ts"]


def t(second: int) -> datetime:
    return datetime(2024, 1, 1, 12, 0, second)


# 1. Book the trades (version 1). BTC: +100, +20, +30 = 150 long. ETH: -50 short.
ch.insert("demo.trades", [
    [1, "BTC", 1, 100, 100.0, 1, 0],
    [2, "BTC", 1, 20, 100.0, 1, 0],
    [3, "ETH", -1, 50, 100.0, 1, 0],
    [4, "BTC", 1, 30, 100.0, 1, 0],
], column_names=TRADE_COLS)
print("1. booked 4 trades: BTC +150, ETH -50")

# 2. Initial prices at cost: valuation starts flat.
ch.insert("demo.prices", [
    ["BTC", 100.0, t(0)],
    ["ETH", 100.0, t(0)],
], column_names=PRICE_COLS)
print("2. initial prices BTC 100, ETH 100")

# 3. The price moves. No trades are booked, so an insert-triggered view has
#    nothing to fire on and could never revalue. The refresh will.
ch.insert("demo.prices", [
    ["BTC", 101.0, t(5)],
    ["ETH", 99.0, t(5)],
], column_names=PRICE_COLS)
print("3. prices moved BTC 100->101, ETH 100->99 (no trades booked)")

# 4. Amend trade 2 (20 -> 25) and cancel trade 4 (-30 from BTC). Higher versions
#    win under ReplacingMergeTree; FINAL + cancelled=0 leaves BTC at 125.
ch.insert("demo.trades", [
    [2, "BTC", 1, 25, 100.0, 2, 0],   # amend: qty 20 -> 25
    [4, "BTC", 1, 30, 100.0, 2, 1],   # cancel trade 4
], column_names=TRADE_COLS)
print("4. amended trade 2 (20->25) and cancelled trade 4; BTC position now 125")
print("loaded; the next scheduled refresh revalues the book from raw")
