"""Clay intelligence adapter layer."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any

from tender_intelligence_agent.models import ClayIntelligence
from tender_intelligence_agent.services.clay_client import ClayComClient


class ClayAdapter(ABC):
    """Abstraction layer so real Clay implementation can be swapped later."""

    @abstractmethod
    def get_intelligence(self, organisation: str) -> ClayIntelligence:
        raise NotImplementedError


class MockClayAdapter(ClayAdapter):
    """Mock implementation when real Clay integration is unavailable."""

    def get_intelligence(self, organisation: str) -> ClayIntelligence:
        return ClayIntelligence(
            organisation=organisation,
            company_profile=(
                f"{organisation} is an enterprise buyer with active procurement and digital "
                "transformation initiatives."
            ),
            strategic_signals=[
                "Recent leadership announcement indicating operational modernization.",
                "Increased hiring activity in procurement, data and transformation functions.",
                "Public statements around cost-efficiency and supplier performance governance.",
            ],
            leadership_changes=[
                "New procurement director appointed in the last 9 months.",
            ],
            market_activity=[
                "Issued multiple competitive tenders in the last 12 months.",
                "Running multi-vendor framework reviews in adjacent categories.",
            ],
            relationships=[
                "Prefers suppliers with prior regulated-industry delivery references.",
                "Collaborates with external advisory partners for complex procurements.",
            ],
            competitive_context=[
                "Incumbents may have delivery footprint advantages.",
                "Mid-tier specialist bidders can compete on innovation and agility.",
            ],
            source="mock_clay_adapter",
        )


class ClayRestAdapter(ClayAdapter):
    """Clay REST adapter using table enrichment rows keyed by company domain."""

    def __init__(self, client: ClayComClient, table_id: str) -> None:
        self.client = client
        self.table_id = table_id

    @staticmethod
    def _as_list(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(v) for v in value if str(v).strip()]
        if isinstance(value, str):
            return [value] if value.strip() else []
        return [str(value)]

    @staticmethod
    def _field(row: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            if key in row and row[key] is not None:
                return row[key]
            fields = row.get("fields")
            if isinstance(fields, dict) and key in fields and fields[key] is not None:
                return fields[key]
        return None

    def get_intelligence(self, organisation: str) -> ClayIntelligence:
        row = asyncio.run(self.client.get_by_domain(self.table_id, organisation))
        if not row:
            return ClayIntelligence(
                organisation=organisation,
                company_profile=f"No Clay REST enrichment row found for domain {organisation}.",
                source="clay_rest",
            )

        return ClayIntelligence(
            organisation=str(self._field(row, "organisation", "company_name") or organisation),
            company_profile=str(self._field(row, "company_profile", "firmographics_summary") or ""),
            strategic_signals=self._as_list(self._field(row, "strategic_signals", "signals")),
            leadership_changes=self._as_list(self._field(row, "leadership_changes", "leadership_signals")),
            market_activity=self._as_list(self._field(row, "market_activity", "market_signals")),
            relationships=self._as_list(self._field(row, "relationships", "relationship_signals")),
            competitive_context=self._as_list(self._field(row, "competitive_context", "competitive_signals")),
            source="clay_rest",
        )
