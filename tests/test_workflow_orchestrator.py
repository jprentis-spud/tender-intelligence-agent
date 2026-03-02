from tender_intelligence_agent.services.workflow_orchestrator import WorkflowDependencies, run_tender_workflow


def test_orchestrator_success_order_and_outputs() -> None:
    calls: list[str] = []

    def ingest_tender_documents(**_: object) -> dict:
        calls.append("ingest")
        return {
            "documents": [{"filename": "a.txt", "type": "main_rfp", "text": "x", "chunk_count": 1}],
            "combined_text": "x",
            "primary_document_type": "main_rfp",
            "primary_document_filename": "a.txt",
        }

    def analyse_tender(**_: object) -> dict:
        calls.append("analyse")
        return {
            "requirements": ["r1"],
            "evaluation_criteria": ["c1"],
            "risks": ["risk"],
            "complexity": "medium",
            "delivery_scope": "scope",
            "cross_document_insights": [],
            "document_contributions": {},
        }

    def sync_tender_to_clay(**_: object) -> dict:
        calls.append("sync")
        return {"buyer": {"id": "b1"}, "tender": {"id": "t1"}}

    def get_clay_intelligence(_: str) -> dict:
        calls.append("clay")
        return {
            "organisation": "Acme",
            "company_profile": "Profile",
            "strategic_signals": [],
            "leadership_changes": [],
            "market_activity": [],
            "relationships": [],
            "competitive_context": [],
            "source": "mock",
        }

    def qualify_bid(**_: object) -> dict:
        calls.append("qualify")
        return {
            "recommendation": "Bid",
            "win_probability": 0.8,
            "strategic_value": "High",
            "risk_level": "Low",
            "key_risks": [],
            "required_resources": ["team"],
            "scoring_breakdown": {"x": 1.0},
            "rationale": "good",
        }

    def generate_briefing(*_: object, **__: object) -> dict:
        calls.append("briefing")
        return {
            "title": "t",
            "summary": "s",
            "recommendation": "Bid",
            "win_probability": 0.8,
            "top_considerations": [],
            "immediate_actions": [],
        }

    result = run_tender_workflow(
        deps=WorkflowDependencies(
            ingest_tender_documents=ingest_tender_documents,
            analyse_tender=analyse_tender,
            sync_tender_to_clay=sync_tender_to_clay,
            get_clay_intelligence=get_clay_intelligence,
            qualify_bid=qualify_bid,
            generate_briefing=generate_briefing,
        ),
        buyer_name="Acme",
        buyer_domain="acme.com",
    )

    assert result.ok is True
    assert calls == ["ingest", "analyse", "sync", "clay", "qualify", "briefing"]


def test_orchestrator_fails_fast_before_sync_when_buyer_missing() -> None:
    calls: list[str] = []

    def ingest_tender_documents(**_: object) -> dict:
        calls.append("ingest")
        return {
            "documents": [{"filename": "a.txt", "type": "main_rfp", "text": "x", "chunk_count": 1}],
            "combined_text": "x",
            "primary_document_type": "main_rfp",
            "primary_document_filename": "a.txt",
        }

    def analyse_tender(**_: object) -> dict:
        calls.append("analyse")
        return {
            "requirements": ["r1"],
            "evaluation_criteria": ["c1"],
            "risks": ["risk"],
            "complexity": "medium",
            "delivery_scope": "scope",
            "cross_document_insights": [],
            "document_contributions": {},
        }

    def never_called(**_: object) -> dict:
        calls.append("later")
        return {}

    result = run_tender_workflow(
        deps=WorkflowDependencies(
            ingest_tender_documents=ingest_tender_documents,
            analyse_tender=analyse_tender,
            sync_tender_to_clay=never_called,
            get_clay_intelligence=lambda *_: {},
            qualify_bid=never_called,
            generate_briefing=lambda *_, **__: {},
        ),
        buyer_name="",
        buyer_domain="acme.com",
    )

    assert result.ok is False
    assert result.error is not None
    assert result.error.step == "validate_buyer_identity"
    assert calls == ["ingest", "analyse"]
