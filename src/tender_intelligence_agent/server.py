"""MCP server entrypoint for tender intelligence tools."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError

from tender_intelligence_agent.config import settings
from tender_intelligence_agent.models import (
    ClayIntelligence,
    QualificationResult,
    TenderAnalysis,
    TenderPackage,
)
from tender_intelligence_agent.services.briefing import generate_briefing as build_briefing
from tender_intelligence_agent.services.clay_adapter import ClayAdapter, ClayRestAdapter, MockClayAdapter
from tender_intelligence_agent.services.clay_client import ClayComClient
from tender_intelligence_agent.services.document_ingestion import build_tender_package
from tender_intelligence_agent.services.clay_pipeline_sync import ClayPipelineSync, ClaySyncConfig
from tender_intelligence_agent.services.openai_tender_analysis import TenderAnalyser
from tender_intelligence_agent.services.qualification import qualify_bid as compute_qualification

mcp = FastMCP("tender-intelligence-agent")


def _build_clay_adapter() -> ClayAdapter:
    if settings.clay_adapter_mode == "rest":
        if not settings.clay_api_key or not settings.clay_company_table_id:
            raise RuntimeError(
                "CLAY_ADAPTER_MODE=rest requires CLAY_API_KEY and CLAY_COMPANY_TABLE_ID to be set."
            )
        client = ClayComClient(api_key=settings.clay_api_key, base_url=settings.clay_base_url)
        return ClayRestAdapter(client=client, table_id=settings.clay_company_table_id)

    # Future extension point for additional Clay providers.
    return MockClayAdapter()


clay_adapter = _build_clay_adapter()


@mcp.tool()
def ingest_tender_documents(
    file_paths: list[str] | None = None,
    file_path: str | None = None,
    text: str | None = None,
) -> dict:
    """Ingest one-or-many tender docs into a structured TenderPackage."""
    package = build_tender_package(file_paths=file_paths, file_path=file_path, text=text)
    return package.model_dump()


@mcp.tool()
def analyse_tender(tender_package: dict | None = None, cleaned_tender_text: str | None = None) -> dict:
    """Analyse tender package using primary document plus supporting context.

    Backward compatibility: cleaned_tender_text is wrapped into a single-document package.
    """
    analyser = TenderAnalyser()

    if tender_package:
        package = TenderPackage.model_validate(tender_package)
    elif cleaned_tender_text:
        package = build_tender_package(text=cleaned_tender_text)
    else:
        raise ValueError("Provide tender_package or cleaned_tender_text.")

    analysis = analyser.analyse_package(package)
    return analysis.model_dump()


@mcp.tool()
def get_clay_intelligence(organisation: str) -> dict:
    """Get buyer intelligence from Clay adapter (mock by default; REST optional)."""
    intelligence = clay_adapter.get_intelligence(organisation)
    return intelligence.model_dump()


@mcp.tool()
def qualify_bid(tender_analysis: dict, clay_intelligence: dict) -> dict:
    """Combine tender analysis and Clay intelligence into transparent bid qualification."""
    try:
        analysis = TenderAnalysis.model_validate(tender_analysis)
        clay = ClayIntelligence.model_validate(clay_intelligence)
    except ValidationError as exc:
        raise ValueError(f"Invalid input schema for qualify_bid: {exc}") from exc

    qualification: QualificationResult = compute_qualification(analysis, clay)
    return qualification.model_dump()


@mcp.tool()
def generate_briefing(tender_analysis: dict, clay_intelligence: dict, qualification: dict) -> dict:
    """Generate executive tender briefing for decision stakeholders."""
    analysis = TenderAnalysis.model_validate(tender_analysis)
    clay = ClayIntelligence.model_validate(clay_intelligence)
    qualified = QualificationResult.model_validate(qualification)

    briefing = build_briefing(analysis, clay, qualified)
    return briefing.model_dump()


@mcp.tool()
def sync_tender_to_clay(buyer_name: str, buyer_domain: str, tender_analysis: dict) -> dict:
    """Upsert Buyer by domain, then create Tender row linked via buyer_domain."""
    if not settings.clay_api_key or not settings.clay_buyer_table_id or not settings.clay_tender_table_id:
        raise ValueError(
            "CLAY_API_KEY, CLAY_BUYER_TABLE_ID and CLAY_TENDER_TABLE_ID are required for sync_tender_to_clay."
        )

    analysis = TenderAnalysis.model_validate(tender_analysis)
    sync = ClayPipelineSync(
        ClaySyncConfig(
            api_key=settings.clay_api_key,
            base_url=settings.clay_base_url,
            buyer_table_id=settings.clay_buyer_table_id,
            tender_table_id=settings.clay_tender_table_id,
        )
    )

    return sync.upsert_buyer_and_create_tender(
        buyer_name=buyer_name,
        buyer_domain=buyer_domain,
        tender_analysis=analysis.model_dump(),
    )


def run() -> None:
    """Run the MCP server with stdio transport for ChatGPT Apps integration."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    run()
