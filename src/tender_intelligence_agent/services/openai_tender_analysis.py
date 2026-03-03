"""OpenAI-powered tender analysis service with multi-document reasoning."""

from __future__ import annotations

import json

from openai import OpenAI

from tender_intelligence_agent.config import settings
from tender_intelligence_agent.models import TenderAnalysis, TenderDocument, TenderPackage
from tender_intelligence_agent.services.document_ingestion import chunk_text

PRIMARY_ANALYSIS_PROMPT = """
You are an expert procurement analyst.
Analyse ONLY the primary tender document and return strict JSON:
{
  "requirements": ["..."],
  "evaluation_criteria": ["..."],
  "risks": ["..."],
  "complexity": "low|medium|high",
  "delivery_scope": "..."
}
Only return valid JSON.
""".strip()

SUPPORTING_ANALYSIS_PROMPT = """
You are an expert procurement analyst.
From the supporting tender document extract strict JSON:
{
  "additional_requirements": ["..."],
  "legal_or_commercial_constraints": ["..."],
  "pricing_or_resource_implications": ["..."],
  "new_risks": ["..."],
  "contribution_summary": "..."
}
Only return valid JSON.
""".strip()

CROSS_DOCUMENT_PROMPT = """
You are an expert procurement analyst.
Given primary findings and supporting findings, identify cross-document issues.
Return strict JSON:
{
  "cross_document_insights": [
    "Conflicting requirements: ...",
    "Hidden obligations in terms: ...",
    "Unscored requirements: ...",
    "Commercial constraints impacting feasibility: ..."
  ]
}
Only return valid JSON.
""".strip()


class TenderAnalyser:
    def __init__(self) -> None:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required for analyse_tender tool.")
        self.client = OpenAI(api_key=settings.openai_api_key)

    def _call_json(self, system_prompt: str, user_content: str) -> dict:
        response = self.client.responses.create(
            model=settings.openai_model,
            instructions=system_prompt,
            input=user_content,
            temperature=0,
        )
        return json.loads(response.output_text.strip())

    def _analyse_primary_document(self, primary_doc: TenderDocument) -> TenderAnalysis:
        chunks = chunk_text(primary_doc.text, settings.max_chunk_chars)
        partial_results: list[TenderAnalysis] = []

        for chunk in chunks:
            data = self._call_json(
                PRIMARY_ANALYSIS_PROMPT,
                f"Primary document: {primary_doc.filename} ({primary_doc.type})\n\n{chunk}",
            )
            partial_results.append(TenderAnalysis.model_validate({**data, "cross_document_insights": [], "document_contributions": {}}))

        requirements: list[str] = []
        evaluation_criteria: list[str] = []
        risks: list[str] = []
        scopes: list[str] = []
        complexities: list[str] = []

        for item in partial_results:
            requirements.extend(item.requirements)
            evaluation_criteria.extend(item.evaluation_criteria)
            risks.extend(item.risks)
            scopes.append(item.delivery_scope)
            complexities.append(item.complexity)

        complexity = "medium"
        if "high" in complexities:
            complexity = "high"
        elif complexities and all(c == "low" for c in complexities):
            complexity = "low"

        return TenderAnalysis(
            requirements=sorted(set(requirements)),
            evaluation_criteria=sorted(set(evaluation_criteria)),
            risks=sorted(set(risks)),
            complexity=complexity,
            delivery_scope=" ".join(scopes),
            cross_document_insights=[],
            document_contributions={},
        )

    def _analyse_supporting_document(self, supporting_doc: TenderDocument) -> dict:
        chunks = chunk_text(supporting_doc.text, settings.max_chunk_chars)
        aggregated = {
            "additional_requirements": [],
            "legal_or_commercial_constraints": [],
            "pricing_or_resource_implications": [],
            "new_risks": [],
            "contribution_summary": [],
        }

        for chunk in chunks:
            data = self._call_json(
                SUPPORTING_ANALYSIS_PROMPT,
                f"Supporting document: {supporting_doc.filename} ({supporting_doc.type})\n\n{chunk}",
            )
            aggregated["additional_requirements"].extend(data.get("additional_requirements", []))
            aggregated["legal_or_commercial_constraints"].extend(data.get("legal_or_commercial_constraints", []))
            aggregated["pricing_or_resource_implications"].extend(data.get("pricing_or_resource_implications", []))
            aggregated["new_risks"].extend(data.get("new_risks", []))
            if data.get("contribution_summary"):
                aggregated["contribution_summary"].append(data["contribution_summary"])

        for key in (
            "additional_requirements",
            "legal_or_commercial_constraints",
            "pricing_or_resource_implications",
            "new_risks",
        ):
            aggregated[key] = sorted(set(aggregated[key]))

        aggregated["contribution_summary"] = " ".join(aggregated["contribution_summary"]).strip()
        return aggregated

    def _cross_document_reasoning(
        self,
        primary_analysis: TenderAnalysis,
        supporting_findings: dict[str, dict],
    ) -> list[str]:
        if not supporting_findings:
            return []

        payload = {
            "primary_analysis": primary_analysis.model_dump(),
            "supporting_findings": supporting_findings,
        }
        data = self._call_json(CROSS_DOCUMENT_PROMPT, json.dumps(payload))
        return data.get("cross_document_insights", [])

    def _select_primary_document(self, package: TenderPackage) -> TenderDocument:
        if package.primary_document_filename:
            explicit = next(
                (doc for doc in package.documents if doc.filename == package.primary_document_filename),
                None,
            )
            if explicit:
                return explicit

        primary_docs = [doc for doc in package.documents if doc.type == package.primary_document_type]
        if primary_docs:
            return max(primary_docs, key=lambda d: len(d.text))

        return max(package.documents, key=lambda d: len(d.text))

    def analyse_package(self, package: TenderPackage) -> TenderAnalysis:
        primary_doc = self._select_primary_document(package)
        supporting_docs = [doc for doc in package.documents if doc.filename != primary_doc.filename]

        primary_analysis = self._analyse_primary_document(primary_doc)

        if not supporting_docs:
            # Backward-compatible single-document behavior.
            return primary_analysis

        supporting_findings: dict[str, dict] = {}
        for doc in supporting_docs:
            supporting_findings[doc.filename] = self._analyse_supporting_document(doc)

        all_additional_requirements: list[str] = []
        all_new_risks: list[str] = []
        all_constraints: list[str] = []
        all_pricing_implications: list[str] = []
        document_contributions: dict[str, str] = {
            primary_doc.type: "Primary source for core requirements, criteria, scope and complexity."
        }

        for doc in supporting_docs:
            finding = supporting_findings[doc.filename]
            all_additional_requirements.extend(finding.get("additional_requirements", []))
            all_new_risks.extend(finding.get("new_risks", []))
            all_constraints.extend(finding.get("legal_or_commercial_constraints", []))
            all_pricing_implications.extend(finding.get("pricing_or_resource_implications", []))
            summary = finding.get("contribution_summary", "").strip()
            if summary:
                document_contributions[doc.type] = summary

        cross_document_insights = self._cross_document_reasoning(primary_analysis, supporting_findings)

        merged_risks = sorted(
            set(primary_analysis.risks + all_new_risks + all_constraints + all_pricing_implications)
        )
        merged_requirements = sorted(set(primary_analysis.requirements + all_additional_requirements))

        return TenderAnalysis(
            requirements=merged_requirements,
            evaluation_criteria=primary_analysis.evaluation_criteria,
            risks=merged_risks,
            complexity=primary_analysis.complexity,
            delivery_scope=primary_analysis.delivery_scope,
            cross_document_insights=sorted(set(cross_document_insights)),
            document_contributions=document_contributions,
        )
