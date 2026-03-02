"""Tender ingestion and cleaning service."""

from __future__ import annotations

from pathlib import Path

from tender_intelligence_agent.config import settings
from tender_intelligence_agent.models import TenderDocument, TenderPackage
from tender_intelligence_agent.services.document_typing import DocumentTypeDetector


def clean_text(raw_text: str) -> str:
    """Normalize whitespace and remove obvious control noise."""
    lines = [line.strip() for line in raw_text.replace("\x00", " ").splitlines()]
    filtered = [line for line in lines if line]
    return "\n".join(filtered)


def chunk_text(text: str, max_chunk_chars: int) -> list[str]:
    """Chunk long tender text for model-friendly processing."""
    if len(text) <= max_chunk_chars:
        return [text]

    words = text.split()
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for word in words:
        token_len = len(word) + 1
        if current and current_len + token_len > max_chunk_chars:
            chunks.append(" ".join(current))
            current = [word]
            current_len = len(word)
        else:
            current.append(word)
            current_len += token_len

    if current:
        chunks.append(" ".join(current))

    return chunks


def _read_text_from_file(file_path: str) -> tuple[str, str]:
    path = Path(file_path)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Tender file not found: {file_path}")
    raw_text = path.read_text(encoding="utf-8", errors="ignore")
    return path.name, raw_text


def _determine_primary_document(documents: list[TenderDocument]) -> TenderDocument:
    preferred = [doc for doc in documents if doc.type in {"main_rfp", "requirements"}]
    if preferred:
        for priority in ("main_rfp", "requirements"):
            first = next((doc for doc in preferred if doc.type == priority), None)
            if first:
                return first
    return max(documents, key=lambda d: len(d.text))


def build_tender_package(
    file_paths: list[str] | None = None,
    file_path: str | None = None,
    text: str | None = None,
) -> TenderPackage:
    """Ingest one-or-many tender inputs into a structured package."""
    provided_files = list(file_paths or [])
    if file_path:
        provided_files.append(file_path)

    if not provided_files and not text:
        raise ValueError("Provide file_paths (or file_path) and/or text.")

    detector = DocumentTypeDetector()
    documents: list[TenderDocument] = []

    for path in provided_files[:200]:
        filename, raw_text = _read_text_from_file(path)
        cleaned = clean_text(raw_text)
        if not cleaned:
            continue
        chunks = chunk_text(cleaned, settings.max_chunk_chars)
        doc_type = detector.detect(filename=filename, text=cleaned)
        documents.append(
            TenderDocument(
                filename=filename,
                type=doc_type,
                text=cleaned,
                chunk_count=len(chunks),
            )
        )

    if text:
        cleaned = clean_text(text)
        if cleaned:
            chunks = chunk_text(cleaned, settings.max_chunk_chars)
            doc_type = detector.detect(filename="inline_text.txt", text=cleaned)
            documents.append(
                TenderDocument(
                    filename="inline_text.txt",
                    type=doc_type,
                    text=cleaned,
                    chunk_count=len(chunks),
                )
            )

    if not documents:
        raise ValueError("No valid tender content found after cleaning.")

    primary_doc = _determine_primary_document(documents)
    combined_text = "\n\n".join(
        [
            f"## Document: {doc.filename} ({doc.type})\n{doc.text}"
            for doc in sorted(documents, key=lambda d: d.filename)
        ]
    )

    return TenderPackage(
        documents=documents,
        combined_text=combined_text,
        primary_document_type=primary_doc.type,
        primary_document_filename=primary_doc.filename,
    )
