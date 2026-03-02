"""Executive briefing generation service."""

from __future__ import annotations

from tender_intelligence_agent.models import Briefing, ClayIntelligence, QualificationResult, TenderAnalysis


def generate_briefing(
    analysis: TenderAnalysis,
    clay: ClayIntelligence,
    qualification: QualificationResult,
) -> Briefing:
    top_considerations = [
        f"Recommendation: {qualification.recommendation} (~{qualification.win_probability:.0%} estimated win probability).",
        f"Tender complexity assessed as {analysis.complexity}.",
    ]

    top_considerations.extend(analysis.risks[:3])

    immediate_actions = [
        "Validate go/no-go against resource availability this week.",
        "Run capture strategy workshop with sales, delivery and legal leads.",
        "Map response plan directly to published evaluation criteria.",
    ]

    summary = (
        f"{clay.organisation} shows active strategic procurement signals. The tender has "
        f"{len(analysis.requirements)} key requirements and {len(analysis.risks)} notable risks. "
        f"Current recommendation: {qualification.recommendation}."
    )

    return Briefing(
        title=f"Tender Qualification Briefing: {clay.organisation}",
        summary=summary,
        recommendation=qualification.recommendation,
        win_probability=qualification.win_probability,
        top_considerations=top_considerations,
        immediate_actions=immediate_actions,
    )
