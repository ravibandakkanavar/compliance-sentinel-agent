from __future__ import annotations

from sentinel.config import Settings
from sentinel.store.base import Store, SyncResult
from sentinel.store.memory import MemoryStore

__all__ = ["MemoryStore", "Store", "SyncResult", "open_store"]


def open_store(settings: Settings) -> Store:
    if not settings.database_url:
        return MemoryStore()
    from sentinel.store.postgres import PostgresStore

    return PostgresStore(settings.database_url)
