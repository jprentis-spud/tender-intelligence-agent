"""Document type detection service using OpenAI with safe fallback heuristics."""

from __future__ import annotations

import json

from openai import OpenAI

from tender_intelligence_agent.config import settings
from tender_intelligence_agent.models import DocumentType

_DETECTION_PROMPT = """
You classify procurement tender document types.
Choose exactly one type from: main_rfp, requirements, pricing, terms, appendix, unknown.
Return strict JSON only: {"type": "..."}.
""".strip()


class DocumentTypeDetector:
    def __init__(self) -> None:
        self.client = OpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None

    def _heuristic_detect(self, filename: str, text: str) -> DocumentType:
        haystack = f"{filename} {text[:2000]}".lower()
        if any(t in haystack for t in ["rfp", "request for proposal", "invitation to tender"]):
            return "main_rfp"
        if any(t in haystack for t in ["requirement", "specification", "statement of work", "sow"]):
            return "requirements"
        if any(t in haystack for t in ["pricing", "price schedule", "commercial schedule", "rate card"]):
            return "pricing"
        if any(t in haystack for t in ["terms", "conditions", "msa", "contract"]):
            return "terms"
        if any(t in haystack for t in ["appendix", "annex", "attachment"]):
            return "appendix"
        return "unknown"

    def detect(self, filename: str, text: str) -> DocumentType:
        if not self.client:
            return self._heuristic_detect(filename, text)

        sample = text[:8000]
        try:
            response = self.client.responses.create(
                model=settings.openai_model,
                input=[
                    {"role": "system", "content": _DETECTION_PROMPT},
                    {
                        "role": "user",
                        "content": f"Filename: {filename}\n\nDocument excerpt:\n{sample}",
                    },
                ],
            )
            payload = json.loads(response.output_text.strip())
            doc_type = payload.get("type", "unknown")
            if doc_type in {"main_rfp", "requirements", "pricing", "terms", "appendix", "unknown"}:
                return doc_type
        except Exception:
            pass

        return self._heuristic_detect(filename, text)
