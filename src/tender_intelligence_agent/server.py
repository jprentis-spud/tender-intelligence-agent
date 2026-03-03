"""MCP server entrypoint for tender intelligence tools."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError

from tender_intelligence_agent.config import settings
from tender_intelligence_agent.models import (
    Briefing,
    ClayIntelligence,
    QualificationResult,
    StyleConfig,
    TenderAnalysis,
    TenderPackage,
    WorkflowResult,
)
from tender_intelligence_agent.services.briefing import generate_briefing as build_briefing
from tender_intelligence_agent.services.clay_adapter import ClayAdapter, ClayRestAdapter, MockClayAdapter
from tender_intelligence_agent.services.clay_client import ClayComClient
from tender_intelligence_agent.services.clay_pipeline_sync import ClayPipelineSync, ClaySyncConfig
from tender_intelligence_agent.services.document_ingestion import build_tender_package
from tender_intelligence_agent.services.openai_tender_analysis import TenderAnalyser
from tender_intelligence_agent.services.qualification import qualify_bid as compute_qualification
from tender_intelligence_agent.services.style_controller import (
    FINAL_BRIEFING_PROMPT,
    INTERMEDIATE_ANALYSE_PROMPT,
    INTERMEDIATE_QUALIFY_PROMPT,
    build_intermediate_status,
    render_response,
)
from tender_intelligence_agent.services.workflow_orchestrator import (
    WorkflowDependencies,
    run_tender_workflow as orchestrate,
)

mcp = FastMCP("tender-intelligence-agent", host=settings.host, port=settings.port)


def _build_clay_adapter() -> ClayAdapter:
    if settings.clay_adapter_mode == "rest":
        table_id = settings.clay_company_table_id or settings.clay_buyer_table_id
        if not settings.clay_api_key or not table_id:
            raise RuntimeError(
                "CLAY_ADAPTER_MODE=rest requires CLAY_API_KEY and CLAY_COMPANY_TABLE_ID (or CLAY_BUYER_TABLE_ID)."
            )
        client = ClayComClient(api_key=settings.clay_api_key, base_url=settings.clay_base_url)
        return ClayRestAdapter(client=client, table_id=table_id)

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
def analyse_tender(
    tender_package: dict | None = None,
    cleaned_tender_text: str | None = None,
    style_config: dict | None = None,
) -> dict:
    """Analyse tender package using primary document plus supporting context."""
    analyser = TenderAnalyser()

    if tender_package:
        package = TenderPackage.model_validate(tender_package)
    elif cleaned_tender_text:
        package = build_tender_package(text=cleaned_tender_text)
    else:
        raise ValueError("Provide tender_package or cleaned_tender_text.")

    analysis = analyser.analyse_package(package)
    style = StyleConfig.model_validate(style_config or {"mode": "INTERMEDIATE", "audience": "BID_MANAGER"})
    status = build_intermediate_status(
        "analyse_tender",
        {
            "requirements": len(analysis.requirements),
            "risks": len(analysis.risks),
            "complexity": analysis.complexity,
        },
        style,
    )
    return {
        **analysis.model_dump(),
        "agent_response": status,
        "prompt_template": INTERMEDIATE_ANALYSE_PROMPT if style.mode == "INTERMEDIATE" else FINAL_BRIEFING_PROMPT,
    }


@mcp.tool()
def get_clay_intelligence(organisation: str) -> dict:
    """Get buyer intelligence from Clay adapter (mock by default; REST optional)."""
    intelligence = clay_adapter.get_intelligence(organisation)
    return intelligence.model_dump()


@mcp.tool()
def qualify_bid(
    tender_analysis: dict,
    clay_intelligence: dict,
    us_context: dict | None = None,
    competitor_context: dict | None = None,
    style_config: dict | None = None,
) -> dict:
    """Combine tender analysis and Clay intelligence into transparent bid qualification."""
    try:
        analysis = TenderAnalysis.model_validate(tender_analysis)
        clay = ClayIntelligence.model_validate(clay_intelligence)
    except ValidationError as exc:
        raise ValueError(f"Invalid input schema for qualify_bid: {exc}") from exc

    _ = us_context, competitor_context

    qualification: QualificationResult = compute_qualification(analysis, clay)
    style = StyleConfig.model_validate(style_config or {"mode": "INTERMEDIATE", "audience": "BID_MANAGER"})
    message = build_intermediate_status(
        "qualify_bid",
        {
            "recommendation": qualification.recommendation,
            "win_probability": qualification.win_probability,
            "risk_level": qualification.risk_level,
        },
        style,
    )
    return {
        **qualification.model_dump(),
        "agent_response": message,
        "prompt_template": INTERMEDIATE_QUALIFY_PROMPT if style.mode == "INTERMEDIATE" else FINAL_BRIEFING_PROMPT,
    }


@mcp.tool()
def generate_briefing(
    qualification: dict,
    tender_analysis: dict | None = None,
    clay_intelligence: dict | None = None,
    style_config: dict | None = None,
) -> dict:
    """Generate executive tender briefing."""
    qualified = QualificationResult.model_validate(qualification)

    if tender_analysis and clay_intelligence:
        analysis = TenderAnalysis.model_validate(tender_analysis)
        clay = ClayIntelligence.model_validate(clay_intelligence)
        briefing = build_briefing(analysis, clay, qualified)
    else:
        briefing = Briefing(
            title="Tender Qualification Briefing",
            summary=qualified.rationale,
            recommendation=qualified.recommendation,
            win_probability=qualified.win_probability,
            top_considerations=qualified.key_risks[:3],
            immediate_actions=qualified.required_resources[:3],
        )

    style = StyleConfig.model_validate(style_config or {"mode": "FINAL", "audience": "BID_MANAGER"})
    detailed = (
        f"Executive Summary\n{briefing.summary}\n\n"
        f"Recommendation\n{qualified.recommendation} (win_probability={qualified.win_probability:.2f}, "
        f"risk_level={qualified.risk_level}, strategic_value={qualified.strategic_value}).\n\n"
        "Win Themes\n- Align response to evaluation criteria\n- Emphasize delivery credibility\n\n"
        "Key Risks\n- "
        + "\n- ".join(qualified.key_risks[:5] or ["No critical risks provided"])
        + "\n\n"
        "Next Actions\n- "
        + "\n- ".join(briefing.immediate_actions[:5] or ["Confirm bid governance"])
    )
    rendered = render_response(detailed if style.mode == "FINAL" else briefing.summary, style)
    return {
        **briefing.model_dump(),
        "agent_response": rendered,
        "prompt_template": FINAL_BRIEFING_PROMPT if style.mode == "FINAL" else INTERMEDIATE_QUALIFY_PROMPT,
    }


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


@mcp.tool()
def run_tender_workflow(
    files: list[str] | None = None,
    text: str | None = None,
    buyer_name: str | None = None,
    buyer_domain: str | None = None,
    us_context: dict | None = None,
    competitor_context: dict | None = None,
    correlation_id: str | None = None,
) -> dict:
    """Deterministic end-to-end tender workflow orchestrator."""
    deps = WorkflowDependencies(
        ingest_tender_documents=ingest_tender_documents,
        analyse_tender=analyse_tender,
        sync_tender_to_clay=sync_tender_to_clay,
        get_clay_intelligence=get_clay_intelligence,
        qualify_bid=qualify_bid,
        generate_briefing=generate_briefing,
    )

    workflow: WorkflowResult = orchestrate(
        deps=deps,
        files=files,
        text=text,
        buyer_name=buyer_name,
        buyer_domain=buyer_domain,
        us_context=us_context,
        competitor_context=competitor_context,
        correlation_id=correlation_id,
    )
    return workflow.model_dump()


def run() -> None:
    """Run the MCP server with configured transport."""
    mcp.run(transport=settings.transport)


if __name__ == "__main__":
    run()
