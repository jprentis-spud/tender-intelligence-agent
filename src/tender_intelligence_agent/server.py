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

mcp = FastMCP("tender-intelligence-agent", host=settings.host, port=settings.port)


def _build_clay_adapter() -> ClayAdapter:
    if settings.clay_adapter_mode == "rest":
        if not settings.clay_api_key or not settings.clay_buyer_table_id:
            raise RuntimeError(
                "CLAY_ADAPTER_MODE=rest requires CLAY_API_KEY and CLAY_BUYER_TABLE_ID to be set."
            )
        client = ClayComClient(api_key=settings.clay_api_key, base_url=settings.clay_base_url)
        return ClayRestAdapter(client=client, table_id=settings.clay_buyer_table_id)

    # Future extension point for additional Clay providers.
    return MockClayAdapter()


clay_adapter = _build_clay_adapter()


@mcp.tool()
def ingest_tender_documents(
    file_paths: list[str] | None = None,
    file_path: str | None = None,
    text: str | None = None,
) -> dict:
    """Step 1: Ingest tender documents into a structured package.

    Call this first when the user provides tender text or file paths.
    After calling, briefly confirm what was ingested (document count, primary doc type)
    and ask the user if they'd like to proceed with analysis.
    Do NOT summarise the full contents — just confirm receipt.
    """
    package = build_tender_package(file_paths=file_paths, file_path=file_path, text=text)
    return package.model_dump()


@mcp.tool()
def analyse_tender(tender_package: dict | None = None, cleaned_tender_text: str | None = None) -> dict:
    """Step 2: Analyse the tender package to extract requirements, risks, and evaluation criteria.

    Call this after ingestion. Present the key findings conversationally — highlight
    the most important requirements and risks, then ask the user if they want to
    pull buyer intelligence from Clay before qualifying the bid.
    Do NOT dump the entire analysis at once.
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
async def sync_and_get_intelligence(
    buyer_name: str,
    buyer_domain: str,
    tender_analysis: dict,
) -> dict:
    """Step 3: Sync buyer/tender to Clay pipeline, then fetch buyer intelligence.

    Call this after analysis. Requires the buyer name, buyer domain, and the
    tender_analysis dict from step 2. This tool:
      1. First upserts the Buyer row and creates a Tender row in Clay so the
         opportunity is tracked in the pipeline immediately.
      2. Then fetches buyer intelligence (strategic signals, leadership changes,
         competitive landscape) to enrich qualification.

    Present the most relevant buyer signals conversationally, confirm the
    tender was saved to Clay, then ask the user if they want to qualify the bid.
    """
    result: dict = {}

    # 1. Sync buyer + tender to Clay pipeline tables first.
    if settings.clay_api_key and settings.clay_buyer_table_id and settings.clay_tender_table_id:
        analysis_obj = TenderAnalysis.model_validate(tender_analysis)
        sync = ClayPipelineSync(
            ClaySyncConfig(
                api_key=settings.clay_api_key,
                base_url=settings.clay_base_url,
                buyer_table_id=settings.clay_buyer_table_id,
                tender_table_id=settings.clay_tender_table_id,
            )
        )
        result["sync"] = sync.upsert_buyer_and_create_tender(
            buyer_name=buyer_name,
            buyer_domain=buyer_domain,
            tender_analysis=analysis_obj.model_dump(),
        )

    # 2. Then fetch buyer intelligence.
    intelligence = await clay_adapter.get_intelligence(buyer_domain)
    result["intelligence"] = intelligence.model_dump()

    return result


@mcp.tool()
def qualify_bid(tender_analysis: dict, clay_intelligence: dict) -> dict:
    """Step 4: Score the bid opportunity using tender analysis and buyer intelligence.

    Produces a Bid / No Bid / Conditional recommendation with a transparent
    scoring breakdown. Present the recommendation and key factors, then ask
    if the user wants a full executive briefing.
    """
    try:
        analysis = TenderAnalysis.model_validate(tender_analysis)
        clay = ClayIntelligence.model_validate(clay_intelligence)
    except ValidationError as exc:
        raise ValueError(f"Invalid input schema for qualify_bid: {exc}") from exc

    qualification: QualificationResult = compute_qualification(analysis, clay)
    return qualification.model_dump()


@mcp.tool()
def generate_briefing(tender_analysis: dict, clay_intelligence: dict, qualification: dict) -> dict:
    """Step 5: Generate an executive briefing summarising the tender opportunity.

    Call this when the user wants the full briefing document with recommendations
    and immediate actions for decision stakeholders.
    """
    analysis = TenderAnalysis.model_validate(tender_analysis)
    clay = ClayIntelligence.model_validate(clay_intelligence)
    qualified = QualificationResult.model_validate(qualification)

    briefing = build_briefing(analysis, clay, qualified)
    return briefing.model_dump()


def run() -> None:
    """Run the MCP server.

    Transport is controlled by MCP_TRANSPORT env var:
      - "sse"   (default) — HTTP+SSE for remote deployment (Railway, etc.)
      - "stdio" — local stdio for ChatGPT Apps / desktop clients
    """
    mcp.run(transport=settings.transport)


if __name__ == "__main__":
    run()
