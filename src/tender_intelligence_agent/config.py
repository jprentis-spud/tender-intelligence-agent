"""Runtime configuration for the tender intelligence MCP server."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    """Environment-backed application settings."""

    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    clay_adapter_mode: str = os.getenv("CLAY_ADAPTER_MODE", "mock")
    clay_api_key: str | None = os.getenv("CLAY_API_KEY")
    clay_base_url: str = os.getenv("CLAY_BASE_URL", "https://api.clay.com")
    clay_company_table_id: str | None = os.getenv("CLAY_COMPANY_TABLE_ID")
    clay_buyer_table_id: str | None = os.getenv("CLAY_BUYER_TABLE_ID")
    clay_tender_table_id: str | None = os.getenv("CLAY_TENDER_TABLE_ID")
    max_chunk_chars: int = int(os.getenv("MAX_CHUNK_CHARS", "12000"))


settings = Settings()
