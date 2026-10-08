# backend/db/client.py
"""Thin wrapper over the synchronous supabase client (BE-09). Owner: Coder 3.
Only db/ talks to Supabase (contract 8.4). The service-role key stays in this object: errors are
redacted before anything is logged, and nothing here is ever returned to an API caller.
Every method blocks; callers run them with asyncio.to_thread."""
from typing import Any

TIMEOUT_S = 5


def redact(text: str, *secrets: str) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text


class SupabaseClient:
    def __init__(self, url: str, key: str, timeout_s: float = TIMEOUT_S) -> None:
        from supabase import ClientOptions, create_client

        self._key = key
        self._client = create_client(url, key, options=ClientOptions(
            postgrest_client_timeout=timeout_s, auto_refresh_token=False, persist_session=False))

    def safe_error(self, exc: BaseException) -> str:
        """Exception text that is safe to log."""
        return redact(f"{type(exc).__name__}: {exc}", self._key)

    def select(self, table: str, columns: str = "*", eq: dict[str, Any] | None = None,
               in_: dict[str, list[Any]] | None = None) -> list[dict[str, Any]]:
        query = self._client.table(table).select(columns)
        for column, value in (eq or {}).items():
            query = query.eq(column, value)
        for column, values in (in_ or {}).items():
            query = query.in_(column, values)
        return query.execute().data

    def insert(self, table: str, row: dict[str, Any]) -> None:
        self._client.table(table).insert(row).execute()

    def update(self, table: str, values: dict[str, Any], eq: dict[str, Any]) -> None:
        query = self._client.table(table).update(values)
        for column, value in eq.items():
            query = query.eq(column, value)
        query.execute()

    def delete(self, table: str, eq: dict[str, Any]) -> None:
        """Only used by tools and tests to clean up their own rows."""
        query = self._client.table(table).delete()
        for column, value in eq.items():
            query = query.eq(column, value)
        query.execute()
