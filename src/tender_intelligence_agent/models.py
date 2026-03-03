"""Domain models and shared schemas for MCP tools."""

from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


DocumentType = Literal["main_rfp", "requirements", "pricing", "terms", "appendix", "unknown"]


class TenderDocument(BaseModel):
    filename: str
    type: DocumentType
    text: str
    chunk_count: int = Field(ge=1)


class TenderPackage(BaseModel):
    documents: list[TenderDocument] = Field(default_factory=list)
    combined_text: str
    primary_document_type: DocumentType
    primary_document_filename: str | None = None


class TenderAnalysis(BaseModel):
    requirements: list[str] = Field(default_factory=list)
    evaluation_criteria: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    complexity: Literal["low", "medium", "high"]
    delivery_scope: str
    cross_document_insights: list[str] = Field(default_factory=list)
    document_contributions: dict[str, str] = Field(default_factory=dict)


class ClayIntelligence(BaseModel):
    organisation: str
    company_profile: str
    strategic_signals: list[str] = Field(default_factory=list)
    leadership_changes: list[str] = Field(default_factory=list)
    market_activity: list[str] = Field(default_factory=list)
    relationships: list[str] = Field(default_factory=list)
    competitive_context: list[str] = Field(default_factory=list)
    source: str = "clay"


class QualificationResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    recommendation: Literal["Bid", "No Bid", "Conditional"]
    win_probability: float = Field(ge=0, le=1)
    strategic_value: Literal["Low", "Medium", "High"]
    risk_level: Literal["Low", "Medium", "High"]
    key_risks: list[str] = Field(default_factory=list)
    required_resources: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("required_resources", "resource_requirements"),
    )
    scoring_breakdown: dict[str, float] = Field(default_factory=dict)
    rationale: str


class Briefing(BaseModel):
    title: str
    summary: str
    recommendation: str
    win_probability: float
    top_considerations: list[str] = Field(default_factory=list)
    immediate_actions: list[str] = Field(default_factory=list)


class StyleConfig(BaseModel):
    mode: Literal["INTERMEDIATE", "FINAL"] = "INTERMEDIATE"
    audience: Literal["BID_MANAGER"] = "BID_MANAGER"


class WorkflowError(BaseModel):
    step: str
    error_type: str
    message: str
    debug_context: dict[str, str] = Field(default_factory=dict)


class WorkflowResult(BaseModel):
    ok: bool
    correlation_id: str
    started_at: str
    finished_at: str
    tender_package: TenderPackage | None = None
    tender_analysis: TenderAnalysis | None = None
    clay_sync: dict[str, object] = Field(default_factory=dict)
    clay_intelligence: ClayIntelligence | None = None
    qualification: QualificationResult | None = None
    briefing: Briefing | None = None
    error: WorkflowError | None = None
