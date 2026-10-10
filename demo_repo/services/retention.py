from datetime import datetime, timedelta

import config
import db


def purge_expired():
    """Scheduled daily. Removes order history and access logs past the retention period."""
    if config.RETENTION_DAYS is None:
        return 0
    cutoff = (datetime.utcnow() - timedelta(days=config.RETENTION_DAYS)).isoformat()
    with db.connect() as conn:
        orders = conn.execute("DELETE FROM orders WHERE created_at < ?", (cutoff,)).rowcount
        logs = conn.execute("DELETE FROM access_log WHERE created_at < ?", (cutoff,)).rowcount
    return orders + logs
