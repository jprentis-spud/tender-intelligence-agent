"""Async Clay.com REST client wrapper.

Note:
- Clay's public REST surface can vary by account/workspace rollout.
- Endpoint paths below are implemented behind configurable defaults and should be
  validated against your workspace docs before production cutover.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class ClayApiPaths:
    """Configurable REST paths to reduce coupling to uncertain endpoint naming."""

    tables: str = "/api/v1/tables"
    table_rows: str = "/api/v1/tables/{table_id}/rows"


class ClayComClient:
    """Minimal async Clay REST API client.

    Authentication:
    - Sends API key as `Authorization: Bearer <api_key>`.
    - Also includes `X-API-Key` for compatibility with alternative gateway setups.
    """

    def __init__(self, api_key: str, base_url: str, paths: ClayApiPaths | None = None) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.paths = paths or ClayApiPaths()

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "X-API-Key": self.api_key,
            "Accept": "application/json",
        }

    async def list_tables(self) -> list[dict[str, Any]]:
        """List tables available in the workspace/project scope of the API key."""
        async with httpx.AsyncClient(base_url=self.base_url, headers=self._headers, timeout=30.0) as client:
            response = await client.get(self.paths.tables)
            response.raise_for_status()
            payload = response.json()

        if isinstance(payload, dict):
            if isinstance(payload.get("tables"), list):
                return payload["tables"]
            if isinstance(payload.get("data"), list):
                return payload["data"]
        if isinstance(payload, list):
            return payload
        return []

    async def get_by_field(
        self,
        table_id: str,
        field_name: str,
        field_value: str,
        *,
        limit: int = 1,
    ) -> dict[str, Any] | None:
        """Query table rows by a field value and return first match if present.

        This method uses conservative query parameters (`field`, `value`, `limit`) as
        a safe default pattern; adjust via API docs if your workspace uses different
        filter semantics.
        """
        endpoint = self.paths.table_rows.format(table_id=table_id)
        params = {
            "field": field_name,
            "value": field_value,
            "limit": max(1, limit),
        }

        async with httpx.AsyncClient(base_url=self.base_url, headers=self._headers, timeout=30.0) as client:
            response = await client.get(endpoint, params=params)
            response.raise_for_status()
            payload = response.json()

        rows: list[dict[str, Any]] = []
        if isinstance(payload, dict):
            if isinstance(payload.get("rows"), list):
                rows = payload["rows"]
            elif isinstance(payload.get("data"), list):
                rows = payload["data"]
        elif isinstance(payload, list):
            rows = payload

        return rows[0] if rows else None

    async def get_by_domain(self, table_id: str, domain: str) -> dict[str, Any] | None:
        """Return first row in a Clay table where `domain == <domain>`."""
        return await self.get_by_field(table_id=table_id, field_name="domain", field_value=domain, limit=1)
