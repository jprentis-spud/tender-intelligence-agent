"""Response style controller for intermediate vs final outputs."""

from __future__ import annotations

import re
from typing import Any

from tender_intelligence_agent.models import StyleConfig


INTERMEDIATE_ANALYSE_PROMPT = (
    "Mode: INTERMEDIATE. Respond concisely for a BID_MANAGER. "
    "Do not repeat source tender text. Max 120 words, up to 5 bullets, and end with one forward question."
)

INTERMEDIATE_QUALIFY_PROMPT = (
    "Mode: INTERMEDIATE. Provide short bid/no-bid rationale with key deltas only. "
    "Max 120 words, max 5 bullets, no tender-text restatement, and end with one decision-driving question."
)

FINAL_BRIEFING_PROMPT = (
    "Mode: FINAL for BID_MANAGER. Produce a detailed briefing with sections: "
    "Executive Summary, Recommendation, Win Themes, Key Risks, Next Actions. "
    "Include quantified values when available (win_probability, risk_level, strategic_value)."
)


def _strip_question_sentences(text: str) -> str:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    kept = [p for p in parts if not p.strip().endswith("?")]
    return " ".join(kept).strip() or text.strip()



def _limit_bullets(text: str, max_bullets: int) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    bullet_lines = [ln for ln in lines if ln.lstrip().startswith(("- ", "* "))]
    if not bullet_lines:
        return text

    kept: list[str] = []
    bullet_count = 0
    for line in lines:
        if line.lstrip().startswith(("- ", "* ")):
            bullet_count += 1
            if bullet_count <= max_bullets:
                kept.append(line)
        else:
            kept.append(line)
    return "\n".join(kept).strip()



def _trim_to_words(text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text.strip()
    return " ".join(words[:max_words]).strip()



def render_response(content: str, style_config: StyleConfig) -> str:
    text = content.strip()

    if style_config.mode == "INTERMEDIATE":
        text = _limit_bullets(text, max_bullets=5)
        text = _strip_question_sentences(text)
        question = "What should we validate next to keep this bid on track?"
        question_words = len(question.split())
        text = _trim_to_words(text, max_words=max(1, 120 - question_words))
        text = text.rstrip(" .")
        text = f"{text}. {question}"
        return text

    # FINAL mode: enforce headings and keep detailed structure.
    if "Executive Summary" in text and "Recommendation" in text:
        return text

    return (
        "Executive Summary\n"
        f"{text}\n\n"
        "Recommendation\n"
        "Use qualification outcome with quantified confidence.\n\n"
        "Win Themes\n"
        "- Differentiate on delivery certainty\n"
        "- Address evaluation criteria directly\n\n"
        "Key Risks\n"
        "- Confirm legal/commercial obligations\n"
        "- Resolve cross-document conflicts\n\n"
        "Next Actions\n"
        "- Align resources\n"
        "- Confirm assumptions with buyer\n"
    )



def build_intermediate_status(stage: str, data: dict[str, Any], style_config: StyleConfig) -> str:
    base = f"Stage {stage} complete with key signals: {data}."
    return render_response(base, style_config)
