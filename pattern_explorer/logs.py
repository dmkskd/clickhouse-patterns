"""Console logging setup shared by the CLI and the explorer service."""
from __future__ import annotations

import logging


class _DropGenericDriverWarning(logging.Filter):
    """Drop clickhouse-connect's content-free "Unexpected Http Driver Exception".

    The driver logs that line on every failed request while still raising the
    real error (host + underlying cause). Left alone it floods the console when a
    node is down and buries the actual reason, which we log ourselves instead.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return record.getMessage() != "Unexpected Http Driver Exception"


def configure_logging(level: int = logging.INFO) -> None:
    """Timestamp our console output and mute the driver's redundant warning."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("clickhouse_connect.driver.httpclient").addFilter(
        _DropGenericDriverWarning()
    )
