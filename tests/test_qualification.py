from tender_intelligence_agent.models import ClayIntelligence, TenderAnalysis
from tender_intelligence_agent.services.qualification import qualify_bid


def test_qualification_returns_valid_bounds() -> None:
    analysis = TenderAnalysis(
        requirements=["ISO27001", "SOC2"],
        evaluation_criteria=["Quality", "Price"],
        risks=["Aggressive timeline"],
        complexity="medium",
        delivery_scope="Managed service rollout",
        cross_document_insights=[],
        document_contributions={},
    )
    clay = ClayIntelligence(
        organisation="Acme Corp",
        company_profile="Enterprise buyer",
        strategic_signals=["Hiring surge", "New CTO"],
        market_activity=["Several tenders"],
        relationships=["Known advisory partners"],
        competitive_context=["Incumbent present"],
    )

    result = qualify_bid(analysis, clay)

    assert 0 <= result.win_probability <= 1
    assert result.recommendation in {"Bid", "No Bid", "Conditional"}
    assert result.strategic_value in {"Low", "Medium", "High"}
    assert result.risk_level in {"Low", "Medium", "High"}


def test_cross_document_conflict_drives_conditional_or_no_bid() -> None:
    analysis = TenderAnalysis(
        requirements=["24/7 support", "Custom ERP integration"],
        evaluation_criteria=["Technical", "Commercial"],
        risks=["Unrealistic timeline"],
        complexity="high",
        delivery_scope="Complex multi-country transformation",
        cross_document_insights=[
            "Conflict between terms and requirements on liability cap.",
            "Hidden obligation in terms: uncapped indemnity and penalties.",
            "Pricing constraint: fixed fee cap despite variable scope.",
            "Missing information: data migration volumes are unknown.",
        ],
        document_contributions={"main_rfp": "Core scope", "terms": "High legal burden"},
    )
    clay = ClayIntelligence(
        organisation="Acme Corp",
        company_profile="Enterprise buyer in regulated industry",
        strategic_signals=["Strategic transformation initiative", "Leadership change in procurement"],
        market_activity=["Active procurement pipeline"],
        relationships=["Existing supplier relationship"],
        competitive_context=["Incumbent with strong footprint"],
    )

    result = qualify_bid(analysis, clay)

    assert result.recommendation in {"Conditional", "No Bid"}
    assert result.risk_level == "High"
