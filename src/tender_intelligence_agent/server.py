"""MCP server entrypoint for tender intelligence tools."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError
from starlette.requests import Request

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
from tender_intelligence_agent.services.sculpt_hack_proxy import SculptHackProxyClient, SculptHackProxyConfig
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


async def _health(request: Request) -> dict[str, str]:
    _ = request
    return {"status": "ok", "service": "tender-intelligence-agent"}


mcp.custom_route("/", methods=["GET"])(_health)
mcp.custom_route("/health", methods=["GET"])(_health)


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


def _build_sculpt_hack_proxy() -> SculptHackProxyClient:
    if not settings.sculpt_hack_api_key:
        raise ValueError("SCULPT_HACK_API_KEY (or CLAY_API_KEY) is required for Sculpt_Hack proxy tools.")
    return SculptHackProxyClient(
        SculptHackProxyConfig(
            base_url=settings.clay_mcp_base_url,
            api_key=settings.sculpt_hack_api_key,
            auth_header=settings.sculpt_hack_auth_header,
            auth_scheme=settings.sculpt_hack_auth_scheme,
            timeout_seconds=settings.sculpt_hack_timeout_seconds,
            retries=settings.sculpt_hack_retries,
        )
    )


def _normalize_domain(value: str | None) -> str:
    normalized = ClayPipelineSync.normalize_domain(value)
    return normalized or ""


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    return [str(value).strip()] if str(value).strip() else []


def _extract_first(data: Any, keys: tuple[str, ...]) -> Any:
    if isinstance(data, dict):
        for key in keys:
            if key in data and data[key] is not None:
                return data[key]
        for nested_key in ("fields", "data", "row", "company"):
            nested = data.get(nested_key)
            extracted = _extract_first(nested, keys)
            if extracted is not None:
                return extracted
    if isinstance(data, list):
        for item in data:
            extracted = _extract_first(item, keys)
            if extracted is not None:
                return extracted
    return None


@mcp.tool()
def sculpt_find_and_enrich_company(company_identifier: str, company_data_points: list[str] | None = None) -> dict:
    """Proxy to Sculpt_Hack find-and-enrich-company."""
    client = _build_sculpt_hack_proxy()
    args: dict[str, Any] = {"companyIdentifier": company_identifier}
    if company_data_points:
        args["companyDataPoints"] = company_data_points
    return client.call_tool("find-and-enrich-company", args)


@mcp.tool()
def sculpt_find_and_enrich_contacts_at_company(
    company_identifier: str,
    contact_filters: dict | None = None,
    data_points: dict | None = None,
) -> dict:
    """Proxy to Sculpt_Hack find-and-enrich-contacts-at-company."""
    client = _build_sculpt_hack_proxy()
    args: dict[str, Any] = {"companyIdentifier": company_identifier}
    if isinstance(contact_filters, dict) and contact_filters:
        args["contactFilters"] = contact_filters
    if isinstance(data_points, dict) and data_points:
        args["dataPoints"] = data_points
    return client.call_tool("find-and-enrich-contacts-at-company", args)


@mcp.tool()
def validate_buyer_identity(
    buyer_name: str | None = None,
    buyer_domain: str | None = None,
    buyer_enrichment: dict | None = None,
) -> dict:
    """Validate and canonicalize buyer identity using Sculpt_Hack enrichment payloads."""
    payload = buyer_enrichment or {}

    candidate_identifier = _normalize_domain(buyer_domain)
    if not candidate_identifier:
        candidate_identifier = _normalize_domain(str(_extract_first(payload, ("domain", "company_domain", "website", "url")) or ""))

    remote_payload: dict[str, Any] = {}
    if candidate_identifier:
        client = _build_sculpt_hack_proxy()
        response = client.call_tool("find-and-enrich-company", {"companyIdentifier": candidate_identifier})
        if isinstance(response, dict):
            remote_payload = response

    merged_payload = {**remote_payload, **payload}

    extracted_name = _extract_first(merged_payload, ("company_name", "organisation", "organization", "name"))
    extracted_domain = _extract_first(
        merged_payload,
        ("domain", "company_domain", "website", "company_website", "companyWebsite", "url"),
    )

    canonical_name = str(buyer_name or extracted_name or "").strip()
    canonical_domain = _normalize_domain(str(buyer_domain or extracted_domain or "").strip())

    if not canonical_name:
        raise ValueError(
            "buyer_name is required. Provide it directly or ensure Sculpt_Hack returns company_name."
        )
    if not canonical_domain:
        raise ValueError(
            "buyer_domain is required. Provide it directly or include it in Sculpt_Hack find-and-enrich-company payload."
        )

    company_profile = str(_extract_first(merged_payload, ("company_profile", "description", "firmographics_summary")) or "")
    strategic_signals = _as_string_list(_extract_first(merged_payload, ("strategic_signals", "signals")))
    relationship_signals = _as_string_list(_extract_first(merged_payload, ("relationships", "relationship_signals")))

    return {
        "buyer_name": canonical_name,
        "buyer_domain": canonical_domain,
        "company_profile": company_profile,
        "strategic_signals": strategic_signals,
        "relationship_signals": relationship_signals,
        "source": "sculpt_hack",
    }


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
    buyer_domain: str | None = None,
    competitor_context: dict | None = None,
    us_context: dict | None = None,
    us_table_path: str | None = None,
    style_config: dict | None = None,
) -> dict:
    """Analyse tender package and optionally include capability check output."""
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

    capability_check: dict[str, Any] = {"status": "skipped", "reason": "buyer_domain not provided"}
    if buyer_domain and str(buyer_domain).strip():
        reviewed_competitors = competitor_review(
            buyer_domain=buyer_domain,
            competitor_context=competitor_context,
        )
        assessed_capability = capability_assessment(
            buyer_domain=buyer_domain,
            competitor_review=reviewed_competitors,
            us_context=us_context,
            us_table_path=us_table_path,
        )
        capability_check = {
            "status": "completed",
            "competitor_review": reviewed_competitors,
            "capability_assessment": assessed_capability,
        }

    return {
        **analysis.model_dump(),
        "capability_check": capability_check,
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
    competitor_count = len(_as_string_list((competitor_context or {}).get("competitor_domains")))
    if isinstance(competitor_context, dict) and isinstance(competitor_context.get("competitors"), list):
        competitor_count = max(competitor_count, len(competitor_context.get("competitors", [])))

    capability_gaps = len(_as_string_list((us_context or {}).get("coverage_gaps")))
    context_penalty = min(0.12, competitor_count * 0.01 + capability_gaps * 0.02)
    adjusted_win_probability = round(max(min(qualification.win_probability - context_penalty, 0.98), 0.02), 4)

    context_rationale = (
        f" Context inputs: competitors={competitor_count}, capability_gaps={capability_gaps}, "
        f"context_penalty={context_penalty:.3f}."
    )
    qualification.rationale = qualification.rationale + context_rationale
    qualification.win_probability = adjusted_win_probability
    qualification.scoring_breakdown["competitor_count"] = float(competitor_count)
    qualification.scoring_breakdown["capability_gap_count"] = float(capability_gaps)
    qualification.scoring_breakdown["context_penalty"] = round(context_penalty, 4)
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
def competitor_review(buyer_domain: str, competitor_context: dict | None = None) -> dict:
    """Normalize competitor review context from Sculpt_Hack enrichment payloads."""
    normalized_buyer_domain = _normalize_domain(buyer_domain)
    if not normalized_buyer_domain:
        raise ValueError("buyer_domain is required")

    client = _build_sculpt_hack_proxy()
    remote_payload = client.call_tool(
        "find-and-enrich-company",
        {
            "companyIdentifier": normalized_buyer_domain,
            "companyDataPoints": ["Company Competitors"],
        },
    )
    payload = remote_payload if isinstance(remote_payload, dict) else {}
    if isinstance(competitor_context, dict):
        payload = {**payload, **competitor_context}
    raw_competitors = _extract_first(payload, ("competitors", "company_competitors", "Company Competitors")) or []

    competitors: list[dict[str, str]] = []
    if isinstance(raw_competitors, list):
        for item in raw_competitors:
            if isinstance(item, dict):
                name = str(item.get("name") or item.get("company_name") or item.get("company") or "").strip()
                domain = _normalize_domain(str(item.get("domain") or item.get("website") or ""))
                if name or domain:
                    competitors.append({"name": name, "domain": domain})
            else:
                value = str(item).strip()
                if value:
                    competitors.append({"name": value, "domain": _normalize_domain(value)})
    elif isinstance(raw_competitors, str):
        for token in [part.strip() for part in raw_competitors.split(",") if part.strip()]:
            competitors.append({"name": token, "domain": _normalize_domain(token)})

    competitor_domains = [c["domain"] for c in competitors if c.get("domain")]
    competitive_context = [f"{c.get('name') or c.get('domain')} active in buyer market." for c in competitors]

    return {
        "buyer_domain": normalized_buyer_domain,
        "competitors": competitors,
        "competitor_domains": competitor_domains,
        "competitive_context": competitive_context,
        "source": "sculpt_hack",
    }


@mcp.tool()
def capability_assessment(
    buyer_domain: str,
    competitor_review: dict | None = None,
    us_context: dict | None = None,
    us_table_path: str | None = None,
) -> dict:
    """Assess internal capability from US table context (inline JSON or file)."""
    normalized_buyer_domain = _normalize_domain(buyer_domain)
    if not normalized_buyer_domain:
        raise ValueError("buyer_domain is required")

    source_payload: dict[str, Any] = {}
    source = "empty"
    if isinstance(us_context, dict) and us_context:
        source_payload = us_context
        source = "us_context"
    elif us_table_path:
        path = Path(us_table_path)
        if not path.exists():
            raise ValueError(f"US table JSON file not found: {us_table_path}")
        source_payload = json.loads(path.read_text(encoding="utf-8"))
        source = "json_file"

    domains = source_payload.get("domains", {}) if isinstance(source_payload, dict) else {}
    buyer_capability = domains.get(normalized_buyer_domain, {}) if isinstance(domains, dict) else {}

    competitor_domains = []
    if isinstance(competitor_review, dict):
        competitor_domains = _as_string_list(competitor_review.get("competitor_domains"))

    competitor_capabilities = []
    for domain in competitor_domains:
        capability = domains.get(domain, {}) if isinstance(domains, dict) else {}
        competitor_capabilities.append({"domain": domain, "capability": capability})

    relationship_signals = _as_string_list(buyer_capability.get("relationship_signals") if isinstance(buyer_capability, dict) else [])
    strategic_signals = _as_string_list(buyer_capability.get("strategic_signals") if isinstance(buyer_capability, dict) else [])
    coverage_gaps = _as_string_list(buyer_capability.get("coverage_gaps") if isinstance(buyer_capability, dict) else [])

    return {
        "buyer_domain": normalized_buyer_domain,
        "buyer_summary": str((buyer_capability or {}).get("summary") or ""),
        "buyer_capability": buyer_capability if isinstance(buyer_capability, dict) else {},
        "competitor_capabilities": competitor_capabilities,
        "relationship_signals": relationship_signals,
        "strategic_signals": strategic_signals,
        "coverage_gaps": coverage_gaps,
        "source": source,
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
    buyer_enrichment: dict | None = None,
    us_context: dict | None = None,
    competitor_context: dict | None = None,
    us_table_path: str | None = None,
    correlation_id: str | None = None,
) -> dict:
    """Deterministic end-to-end tender workflow orchestrator."""
    deps = WorkflowDependencies(
        ingest_tender_documents=ingest_tender_documents,
        validate_buyer_identity=validate_buyer_identity,
        analyse_tender=analyse_tender,
        competitor_review=competitor_review,
        capability_assessment=capability_assessment,
        qualify_bid=qualify_bid,
        generate_briefing=generate_briefing,
    )

    workflow: WorkflowResult = orchestrate(
        deps=deps,
        files=files,
        text=text,
        buyer_name=buyer_name,
        buyer_domain=buyer_domain,
        buyer_enrichment=buyer_enrichment,
        us_context=us_context,
        competitor_context=competitor_context,
        us_table_path=us_table_path,
        correlation_id=correlation_id,
    )
    return workflow.model_dump()


def run() -> None:
    """Run the MCP server with configured transport."""
    mcp.run(transport=settings.transport)


if __name__ == "__main__":
    run()
