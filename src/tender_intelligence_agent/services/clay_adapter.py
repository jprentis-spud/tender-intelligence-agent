"""Clay intelligence adapter layer."""

from __future__ import annotations

from abc import ABC, abstractmethod

from tender_intelligence_agent.models import ClayIntelligence


class ClayAdapter(ABC):
    """Abstraction layer so real Clay implementation can be swapped later."""

    @abstractmethod
    def get_intelligence(self, organisation: str) -> ClayIntelligence:
        raise NotImplementedError


class MockClayAdapter(ClayAdapter):
    """Mock implementation when real Clay MCP integration is unavailable."""

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
