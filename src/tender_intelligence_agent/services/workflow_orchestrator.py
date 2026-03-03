"""Deterministic tender workflow orchestration with structured validation and errors."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from pydantic import ValidationError

from tender_intelligence_agent.models import (
    Briefing,
    ClayIntelligence,
    QualificationResult,
    TenderAnalysis,
    TenderPackage,
    WorkflowError,
    WorkflowResult,
)

LogFn = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class WorkflowDependencies:
    ingest_tender_documents: Callable[..., dict]
    validate_buyer_identity: Callable[..., dict]
    analyse_tender: Callable[..., dict]
    sync_tender_to_clay: Callable[..., dict]
    competitor_review: Callable[..., dict]
    capability_assessment: Callable[..., dict]
    qualify_bid: Callable[..., dict]
    generate_briefing: Callable[..., dict]



def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()



def _emit(log_fn: LogFn | None, correlation_id: str, step: str, status: str, debug_context: dict[str, Any] | None = None) -> None:
    if log_fn is None:
        return
    log_fn(
        {
            "timestamp": _utc_now(),
            "correlation_id": correlation_id,
            "step": step,
            "status": status,
            "debug_context": debug_context or {},
        }
    )



def _workflow_failure(
    *,
    correlation_id: str,
    started_at: str,
    step: str,
    exc: Exception,
    debug_context: dict[str, Any] | None = None,
) -> WorkflowResult:
    return WorkflowResult(
        ok=False,
        correlation_id=correlation_id,
        started_at=started_at,
        finished_at=_utc_now(),
        error=WorkflowError(
            step=step,
            error_type=type(exc).__name__,
            message=str(exc),
            debug_context={k: str(v) for k, v in (debug_context or {}).items()},
        ),
    )



def validate_tender_package(payload: dict) -> TenderPackage:
    package = TenderPackage.model_validate(payload)
    if not package.documents:
        raise ValueError("TenderPackage.documents must not be empty")
    if not package.primary_document_filename:
        raise ValueError("TenderPackage.primary_document_filename is required")
    return package



def validate_tender_analysis(payload: dict) -> TenderAnalysis:
    analysis = TenderAnalysis.model_validate(payload)
    if not analysis.delivery_scope.strip():
        raise ValueError("TenderAnalysis.delivery_scope is required")
    return analysis



def validate_clay_intelligence(payload: dict) -> ClayIntelligence:
    clay = ClayIntelligence.model_validate(payload)
    if not clay.organisation.strip():
        raise ValueError("ClayIntelligence.organisation is required")
    return clay


def compose_clay_intelligence(
    buyer_identity: dict[str, Any],
    competitor_review: dict[str, Any] | None = None,
    capability_assessment: dict[str, Any] | None = None,
) -> ClayIntelligence:
    competitor_review = competitor_review or {}
    capability_assessment = capability_assessment or {}

    organisation = str(buyer_identity.get("buyer_name") or buyer_identity.get("organisation") or "").strip()
    if not organisation:
        organisation = str(buyer_identity.get("buyer_domain") or "Unknown Organisation")

    company_profile = str(
        buyer_identity.get("company_profile")
        or capability_assessment.get("buyer_summary")
        or f"{organisation} buyer profile derived from workflow inputs."
    )

    competitive_signals = competitor_review.get("competitive_context")
    if not isinstance(competitive_signals, list):
        competitive_signals = []

    relationship_signals = capability_assessment.get("relationship_signals")
    if not isinstance(relationship_signals, list):
        relationship_signals = []

    strategic_signals = capability_assessment.get("strategic_signals")
    if not isinstance(strategic_signals, list):
        strategic_signals = []

    return ClayIntelligence(
        organisation=organisation,
        company_profile=company_profile,
        strategic_signals=[str(s) for s in strategic_signals if str(s).strip()],
        leadership_changes=[],
        market_activity=[],
        relationships=[str(s) for s in relationship_signals if str(s).strip()],
        competitive_context=[str(s) for s in competitive_signals if str(s).strip()],
        source="workflow_composite",
    )



def validate_qualification_result(payload: dict) -> QualificationResult:
    qualification = QualificationResult.model_validate(payload)
    if not qualification.rationale.strip():
        raise ValueError("QualificationResult.rationale is required")
    return qualification



def run_tender_workflow(
    *,
    deps: WorkflowDependencies,
    files: list[str] | None = None,
    text: str | None = None,
    buyer_name: str | None = None,
    buyer_domain: str | None = None,
    buyer_enrichment: dict[str, Any] | None = None,
    us_context: dict[str, Any] | None = None,
    competitor_context: dict[str, Any] | None = None,
    us_table_path: str | None = None,
    correlation_id: str | None = None,
    log_fn: LogFn | None = None,
) -> WorkflowResult:
    """Run deterministic tender workflow with step-by-step fail-fast handling."""
    corr_id = correlation_id or str(uuid4())
    started_at = _utc_now()

    try:
        step = "ingest_tender_documents"
        _emit(log_fn, corr_id, step, "started", {"files_count": len(files or []), "has_text": bool(text)})
        package_payload = deps.ingest_tender_documents(file_paths=files, text=text)
        package = validate_tender_package(package_payload)
        _emit(log_fn, corr_id, step, "completed", {"documents": len(package.documents)})

        step = "validate_buyer_identity"
        _emit(log_fn, corr_id, step, "started")
        buyer_identity = deps.validate_buyer_identity(
            buyer_name=buyer_name,
            buyer_domain=buyer_domain,
            buyer_enrichment=buyer_enrichment,
        )
        canonical_name = str(buyer_identity.get("buyer_name") or "").strip()
        canonical_domain = str(buyer_identity.get("buyer_domain") or "").strip()
        if not canonical_name:
            raise ValueError("validate_buyer_identity did not return buyer_name")
        if not canonical_domain:
            raise ValueError("validate_buyer_identity did not return buyer_domain")
        _emit(log_fn, corr_id, step, "completed", {"buyer_name": canonical_name, "buyer_domain": canonical_domain})

        step = "analyse_tender"
        _emit(log_fn, corr_id, step, "started", {"primary_document_type": package.primary_document_type})
        analysis_payload = deps.analyse_tender(
            tender_package=package.model_dump(),
            style_config={"mode": "INTERMEDIATE", "audience": "BID_MANAGER"},
        )
        analysis = validate_tender_analysis(analysis_payload)
        _emit(log_fn, corr_id, step, "completed", {"requirements": len(analysis.requirements)})

        step = "sync_tender_to_clay"
        _emit(log_fn, corr_id, step, "started")
        clay_sync = deps.sync_tender_to_clay(
            buyer_name=canonical_name,
            buyer_domain=canonical_domain,
            tender_analysis=analysis.model_dump(),
        )
        _emit(log_fn, corr_id, step, "completed", {"keys": sorted(clay_sync.keys()) if isinstance(clay_sync, dict) else []})

        step = "competitor_review"
        _emit(log_fn, corr_id, step, "started", {"buyer_domain": canonical_domain})
        competitor_review = deps.competitor_review(
            buyer_domain=canonical_domain,
            competitor_context=competitor_context,
        )
        _emit(
            log_fn,
            corr_id,
            step,
            "completed",
            {"competitors": len(competitor_review.get("competitors", [])) if isinstance(competitor_review, dict) else 0},
        )

        step = "capability_assessment"
        _emit(log_fn, corr_id, step, "started")
        capability_assessment = deps.capability_assessment(
            buyer_domain=canonical_domain,
            competitor_review=competitor_review,
            us_context=us_context,
            us_table_path=us_table_path,
        )
        _emit(log_fn, corr_id, step, "completed", {"source": capability_assessment.get("source", "unknown")})

        step = "compose_clay_intelligence"
        _emit(log_fn, corr_id, step, "started")
        clay = compose_clay_intelligence(
            buyer_identity=buyer_identity,
            competitor_review=competitor_review if isinstance(competitor_review, dict) else {},
            capability_assessment=capability_assessment if isinstance(capability_assessment, dict) else {},
        )
        clay = validate_clay_intelligence(clay.model_dump())
        _emit(log_fn, corr_id, step, "completed", {"signals": len(clay.strategic_signals)})

        step = "qualify_bid"
        _emit(log_fn, corr_id, step, "started")
        qualification_payload = deps.qualify_bid(
            tender_analysis=analysis.model_dump(),
            clay_intelligence=clay.model_dump(),
            us_context=capability_assessment if isinstance(capability_assessment, dict) else {},
            competitor_context=competitor_review if isinstance(competitor_review, dict) else {},
            style_config={"mode": "INTERMEDIATE", "audience": "BID_MANAGER"},
        )
        qualification = validate_qualification_result(qualification_payload)
        _emit(log_fn, corr_id, step, "completed", {"recommendation": qualification.recommendation})

        step = "generate_briefing"
        _emit(log_fn, corr_id, step, "started")
        briefing_payload = deps.generate_briefing(
            qualification.model_dump(),
            tender_analysis=analysis.model_dump(),
            clay_intelligence=clay.model_dump(),
            style_config={"mode": "FINAL", "audience": "BID_MANAGER"},
        )
        briefing = Briefing.model_validate(briefing_payload)
        _emit(log_fn, corr_id, step, "completed", {"title": briefing.title})

        return WorkflowResult(
            ok=True,
            correlation_id=corr_id,
            started_at=started_at,
            finished_at=_utc_now(),
            buyer_identity=buyer_identity if isinstance(buyer_identity, dict) else {},
            tender_package=package,
            tender_analysis=analysis,
            clay_sync=clay_sync if isinstance(clay_sync, dict) else {},
            competitor_review=competitor_review if isinstance(competitor_review, dict) else {},
            capability_assessment=capability_assessment if isinstance(capability_assessment, dict) else {},
            clay_intelligence=clay,
            qualification=qualification,
            briefing=briefing,
            error=None,
        )

    except (ValidationError, ValueError, RuntimeError) as exc:
        _emit(log_fn, corr_id, locals().get("step", "unknown"), "failed", {"message": str(exc)})
        return _workflow_failure(
            correlation_id=corr_id,
            started_at=started_at,
            step=locals().get("step", "unknown"),
            exc=exc,
            debug_context={"buyer_name": buyer_name, "buyer_domain": buyer_domain},
        )
    except Exception as exc:  # unexpected guardrail
        _emit(log_fn, corr_id, locals().get("step", "unknown"), "failed", {"message": str(exc)})
        return _workflow_failure(
            correlation_id=corr_id,
            started_at=started_at,
            step=locals().get("step", "unknown"),
            exc=exc,
            debug_context={"buyer_name": buyer_name, "buyer_domain": buyer_domain},
        )
