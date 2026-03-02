from tender_intelligence_agent.models import StyleConfig
from tender_intelligence_agent.services.style_controller import render_response


def test_intermediate_enforces_length_bullets_and_question() -> None:
    content = "\n".join([f"- item {i}" for i in range(1, 9)]) + "\nThis is a long body " + "word " * 150
    out = render_response(content, StyleConfig(mode="INTERMEDIATE", audience="BID_MANAGER"))
    assert out.endswith("What should we validate next to keep this bid on track?")
    assert len(out.split()) <= 121  # includes appended question sentence
    assert out.count("\n- ") <= 5


def test_final_keeps_headings() -> None:
    content = "Executive Summary\nA\n\nRecommendation\nB\n\nWin Themes\n- C\n\nKey Risks\n- D\n\nNext Actions\n- E"
    out = render_response(content, StyleConfig(mode="FINAL", audience="BID_MANAGER"))
    assert "Executive Summary" in out
    assert "Recommendation" in out
