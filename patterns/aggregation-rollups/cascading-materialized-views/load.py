"""Load raw trades in several separate INSERTs so a single one-minute bucket is
split across multiple parts.

Each ch.insert() is one insert block: it becomes one part and fires mv_1m, whose
insert into candles_1m in turn fires the cascaded mv_5m. The three batches are
arranged so every minute's trades land in three different parts -- batch A the
opening prints, batch B the mid prints, batch C the closing prints.

The 1m candle for each minute is therefore assembled from partial states in
three parts, and the 5m candle is assembled by merging those 1m states across
minutes. Correct output proves the whole cascade recombines partial states
regardless of how the inserts were batched.
"""
from datetime import datetime

from pattern_explorer.orchestration.nodes import connect

COLUMNS = ["symbol", "price", "volume", "ts"]


def t(minute: int, second: int) -> datetime:
    return datetime(2024, 1, 1, 12, minute, second)


# Each inner list is one INSERT -> one block -> one part -> mv_1m -> mv_5m.
BATCHES = [
    # batch A: the opening print of each minute
    [
        ["BTC", 100.0, 1.0, t(0, 5)],
        ["BTC", 104.0, 2.0, t(1, 5)],
        ["BTC", 101.0, 1.0, t(2, 10)],
    ],
    # batch B: a mid-minute print (sets the high or the low)
    [
        ["BTC", 110.0, 2.0, t(0, 30)],
        ["BTC", 98.0, 1.0, t(1, 20)],
        ["BTC", 115.0, 4.0, t(2, 35)],
    ],
    # batch C: the closing print of each minute
    [
        ["BTC", 105.0, 3.0, t(0, 55)],
        ["BTC", 101.0, 2.0, t(1, 50)],
        ["BTC", 112.0, 2.0, t(2, 59)],
    ],
]

ch = connect("ch")
for i, batch in enumerate(BATCHES, 1):
    ch.insert("demo.trades", batch, column_names=COLUMNS)
    print(f"insert {i}: {len(batch)} trades -> demo.trades (part -> mv_1m -> mv_5m)")
print(f"loaded {sum(len(b) for b in BATCHES)} trades across {len(BATCHES)} parts")
