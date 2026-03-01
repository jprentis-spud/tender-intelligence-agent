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
from tender_intelligence_agent.services.clay_adapter import ClayAdapter, MockClayAdapter
from tender_intelligence_agent.services.document_ingestion import build_tender_package
from tender_intelligence_agent.services.openai_tender_analysis import TenderAnalyser
from tender_intelligence_agent.services.qualification import qualify_bid as compute_qualification

mcp = FastMCP("tender-intelligence-agent")


def _build_clay_adapter() -> ClayAdapter:
    # Future extension point for real Clay MCP provider.
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
    """Get buyer intelligence from Clay (mock adapter by default)."""
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


def run() -> None:
    """Run the MCP server with stdio transport for ChatGPT Apps integration."""
    if settings.clay_adapter_mode != "mock":
        raise RuntimeError(
            "Only CLAY_ADAPTER_MODE=mock is currently implemented. "
            "Add a real Clay adapter to enable live integration."
        )
    mcp.run(transport="stdio")


if __name__ == "__main__":
    run()
