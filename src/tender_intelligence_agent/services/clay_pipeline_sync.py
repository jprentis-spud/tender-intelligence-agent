"""Minimal Clay row write helpers for Buyer/Tender pipeline using requests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests


@dataclass(frozen=True)
class ClaySyncConfig:
    api_key: str
    base_url: str
    buyer_table_id: str
    tender_table_id: str


class ClayPipelineSync:
    """Implements domain-based Buyer upsert and Tender creation flow."""

    def __init__(self, config: ClaySyncConfig) -> None:
        self.config = config

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.api_key}",
            "X-API-Key": self.config.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    @property
    def _rows_url(self) -> str:
        return f"{self.config.base_url.rstrip('/')}/api/v1/tables/{{table_id}}/rows"

    @staticmethod
    def normalize_domain(domain: str | None) -> str | None:
        if not domain:
            return None
        value = domain.strip().lower()
        value = value.removeprefix("http://").removeprefix("https://").removeprefix("www.")
        value = value.split("/")[0]
        return value or None

    @staticmethod
    def _extract_rows(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [r for r in payload if isinstance(r, dict)]
        if isinstance(payload, dict):
            if isinstance(payload.get("rows"), list):
                return [r for r in payload["rows"] if isinstance(r, dict)]
            if isinstance(payload.get("data"), list):
                return [r for r in payload["data"] if isinstance(r, dict)]
        return []

    def find_buyer_by_domain(self, domain: str) -> dict[str, Any] | None:
        response = requests.get(
            self._rows_url.format(table_id=self.config.buyer_table_id),
            headers=self._headers,
            params={"field": "domain", "value": domain, "limit": 1},
            timeout=30,
        )
        response.raise_for_status()
        rows = self._extract_rows(response.json())
        return rows[0] if rows else None

    def create_row(self, table_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        response = requests.post(
            self._rows_url.format(table_id=table_id),
            headers=self._headers,
            json={"fields": fields},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict):
            if isinstance(payload.get("row"), dict):
                return payload["row"]
            if isinstance(payload.get("data"), dict):
                return payload["data"]
            return payload
        raise ValueError("Unexpected Clay create_row response shape")

    def upsert_buyer(self, buyer_name: str, buyer_domain: str) -> dict[str, Any]:
        normalized_domain = self.normalize_domain(buyer_domain)
        if not normalized_domain:
            raise ValueError("buyer_domain is required")

        existing = self.find_buyer_by_domain(normalized_domain)
        if existing:
            return existing

        return self.create_row(
            self.config.buyer_table_id,
            {
                "domain": normalized_domain,
                "company_name": buyer_name,
            },
        )

    def create_tender(self, buyer_domain: str, tender_analysis: dict[str, Any]) -> dict[str, Any]:
        normalized_domain = self.normalize_domain(buyer_domain)
        if not normalized_domain:
            raise ValueError("buyer_domain is required")

        return self.create_row(
            self.config.tender_table_id,
            {
                "buyer_domain": normalized_domain,
                "tender_title": tender_analysis.get("tender_title") or "Untitled Tender",
                "tender_summary": tender_analysis.get("tender_summary") or "",
                "delivery_scope_summary": tender_analysis.get("delivery_scope") or "",
                "complexity": tender_analysis.get("complexity") or "medium",
                "key_requirements": "\n".join(tender_analysis.get("requirements", [])),
                "evaluation_criteria": "\n".join(tender_analysis.get("evaluation_criteria", [])),
                "key_risks": "\n".join(tender_analysis.get("risks", [])),
                "cross_document_insights": "\n".join(tender_analysis.get("cross_document_insights", [])),
                "analysis_timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    def upsert_buyer_and_create_tender(
        self,
        buyer_name: str,
        buyer_domain: str,
        tender_analysis: dict[str, Any],
    ) -> dict[str, Any]:
        buyer = self.upsert_buyer(buyer_name=buyer_name, buyer_domain=buyer_domain)
        tender = self.create_tender(buyer_domain=buyer_domain, tender_analysis=tender_analysis)
        return {"buyer": buyer, "tender": tender}
