from pathlib import Path

from tender_intelligence_agent.services.document_ingestion import build_tender_package


def test_build_tender_package_prefers_main_rfp(tmp_path: Path) -> None:
    main = tmp_path / "main_rfp.txt"
    main.write_text("Request for proposal for digital contact center modernization.")
    pricing = tmp_path / "pricing_schedule.txt"
    pricing.write_text("Pricing and rate card details for implementation.")

    package = build_tender_package(file_paths=[str(main), str(pricing)])

    assert len(package.documents) == 2
    assert package.primary_document_type == "main_rfp"
    assert package.primary_document_filename == "main_rfp.txt"
    assert "Document: main_rfp.txt" in package.combined_text


def test_build_tender_package_backward_compat_text() -> None:
    package = build_tender_package(text="Statement of work and requirements for service delivery.")

    assert len(package.documents) == 1
    assert package.documents[0].filename == "inline_text.txt"
    assert package.documents[0].chunk_count >= 1
