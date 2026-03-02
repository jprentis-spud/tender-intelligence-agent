"""Transparent bid qualification logic with cross-document decisioning."""

from __future__ import annotations

from tender_intelligence_agent.models import ClayIntelligence, QualificationResult, TenderAnalysis


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in terms)


def _extract_signal_counts(analysis: TenderAnalysis) -> dict[str, int]:
    insights_text = " ".join(analysis.cross_document_insights)
    risks_text = " ".join(analysis.risks)
    combined = f"{insights_text} {risks_text}".lower()

    return {
        "conflicts": sum(1 for i in analysis.cross_document_insights if _contains_any(i, ("conflict", "contradict"))),
        "hidden_obligations": 1 if _contains_any(combined, ("hidden obligation", "indemn", "liability", "penalt", "service credit")) else 0,
        "timeline_issues": 1 if _contains_any(combined, ("unrealistic timeline", "aggressive timeline", "compressed", "short timeline")) else 0,
        "pricing_constraints": 1 if _contains_any(combined, ("pricing constraint", "price cap", "fixed fee", "not-to-exceed", "margin")) else 0,
        "missing_info": 1 if _contains_any(combined, ("tbd", "missing", "unclear", "unknown", "not provided")) else 0,
        "custom_demands": 1 if _contains_any(combined, ("custom integration", "bespoke", "non-standard", "legacy integration")) else 0,
    }


def _score_strategic_fit(clay: ClayIntelligence) -> float:
    score = 35.0
    profile = clay.company_profile.lower()
    if _contains_any(profile, ("enterprise", "public sector", "regulated", "global")):
        score += 8.0

    score += min(len(clay.strategic_signals) * 6.0, 30.0)
    score += min(len(clay.market_activity) * 2.0, 10.0)
    return max(min(score, 100.0), 0.0)


def _score_capability_fit(analysis: TenderAnalysis, signal_counts: dict[str, int]) -> float:
    score = 45.0
    score += min(len(analysis.requirements) * 2.0, 24.0)

    if analysis.complexity == "high":
        score -= 12.0
    elif analysis.complexity == "low":
        score += 8.0

    score -= signal_counts["custom_demands"] * 8.0
    return max(min(score, 100.0), 0.0)


def _score_commercial_viability(analysis: TenderAnalysis, signal_counts: dict[str, int]) -> float:
    score = 60.0
    score += min(len(analysis.evaluation_criteria) * 2.0, 12.0)
    score -= signal_counts["pricing_constraints"] * 18.0
    score -= signal_counts["hidden_obligations"] * 12.0
    return max(min(score, 100.0), 0.0)


def _score_risk_level(analysis: TenderAnalysis, signal_counts: dict[str, int]) -> float:
    score = 20.0 + min(len(analysis.risks) * 6.0, 36.0)
    score += min(signal_counts["conflicts"] * 12.0, 30.0)
    score += signal_counts["hidden_obligations"] * 12.0
    score += signal_counts["timeline_issues"] * 10.0
    score += signal_counts["pricing_constraints"] * 10.0
    score += signal_counts["missing_info"] * 8.0
    return max(min(score, 100.0), 0.0)


def _score_relationship_advantage(clay: ClayIntelligence) -> float:
    score = 40.0
    score += min(len(clay.relationships) * 10.0, 35.0)

    positive_signals = sum(
        1
        for signal in clay.strategic_signals
        if _contains_any(signal, ("investment", "expansion", "transformation", "growth", "initiative"))
    )
    disruption_signals = sum(
        1
        for signal in clay.strategic_signals
        if _contains_any(signal, ("leadership change", "restructure", "cost cutting", "budget freeze"))
    )
    score += min(positive_signals * 5.0, 15.0)
    score -= min(disruption_signals * 6.0, 18.0)
    return max(min(score, 100.0), 0.0)


def _risk_level_label(risk_score: float) -> str:
    if risk_score >= 70:
        return "High"
    if risk_score >= 40:
        return "Medium"
    return "Low"


def _strategic_value_label(strategic_fit: float, relationship_advantage: float) -> str:
    average = (strategic_fit + relationship_advantage) / 2
    if average >= 70:
        return "High"
    if average >= 45:
        return "Medium"
    return "Low"


def qualify_bid(analysis: TenderAnalysis, clay: ClayIntelligence) -> QualificationResult:
    signal_counts = _extract_signal_counts(analysis)

    strategic_fit = _score_strategic_fit(clay)
    capability_fit = _score_capability_fit(analysis, signal_counts)
    commercial_viability = _score_commercial_viability(analysis, signal_counts)
    risk_score = _score_risk_level(analysis, signal_counts)
    relationship_advantage = _score_relationship_advantage(clay)

    win_probability = (
        strategic_fit * 0.25
        + capability_fit * 0.25
        + commercial_viability * 0.20
        + relationship_advantage * 0.20
        + (100.0 - risk_score) * 0.10
    ) / 100.0

    # Cross-document conflict penalties.
    if signal_counts["conflicts"] > 0:
        win_probability -= min(0.08 + 0.03 * signal_counts["conflicts"], 0.20)
    if signal_counts["hidden_obligations"] > 0:
        win_probability -= 0.05

    win_probability = round(max(min(win_probability, 0.98), 0.02), 4)

    risk_level = _risk_level_label(risk_score)
    strategic_value = _strategic_value_label(strategic_fit, relationship_advantage)

    strong_fit = strategic_fit >= 65 and capability_fit >= 60
    high_uncertainty = signal_counts["missing_info"] > 0 or signal_counts["conflicts"] > 0

    if strategic_value == "High" and risk_level == "High":
        recommendation = "Conditional"
    elif strong_fit and high_uncertainty:
        recommendation = "Conditional"
    elif win_probability >= 0.65 and risk_level != "High":
        recommendation = "Bid"
    elif win_probability < 0.45 or (risk_level == "High" and strategic_value != "High"):
        recommendation = "No Bid"
    else:
        recommendation = "Conditional"

    required_resources = [
        "Bid manager and solution lead",
        "SME reviewers across compliance and delivery",
        "Commercial and pricing workstream",
    ]
    if analysis.complexity == "high" or signal_counts["hidden_obligations"]:
        required_resources.append("Dedicated legal and contract-risk review")
    if signal_counts["conflicts"]:
        required_resources.append("Cross-document reconciliation workshop")

    key_risks = list(dict.fromkeys(analysis.risks + analysis.cross_document_insights))[:8]

    rationale = (
        f"Decision={recommendation}. Document signals: {signal_counts['conflicts']} conflict indicators, "
        f"hidden obligations={signal_counts['hidden_obligations']}, timeline issues={signal_counts['timeline_issues']}, "
        f"missing info={signal_counts['missing_info']}. Clay signals: {len(clay.relationships)} relationship signals, "
        f"{len(clay.strategic_signals)} strategic signals. Scores -> strategic_fit={strategic_fit:.1f}, "
        f"capability_fit={capability_fit:.1f}, commercial_viability={commercial_viability:.1f}, "
        f"risk_score={risk_score:.1f}, relationship_advantage={relationship_advantage:.1f}."
    )

    return QualificationResult(
        recommendation=recommendation,
        win_probability=win_probability,
        strategic_value=strategic_value,
        risk_level=risk_level,
        key_risks=key_risks,
        required_resources=required_resources,
        scoring_breakdown={
            "strategic_fit": round(strategic_fit, 2),
            "capability_fit": round(capability_fit, 2),
            "commercial_viability": round(commercial_viability, 2),
            "risk_score": round(risk_score, 2),
            "relationship_advantage": round(relationship_advantage, 2),
            "conflict_penalty_count": float(signal_counts["conflicts"]),
        },
        rationale=rationale,
    )
