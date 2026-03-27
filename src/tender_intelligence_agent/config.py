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
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-5-mini")
    clay_adapter_mode: str = os.getenv("CLAY_ADAPTER_MODE", "mock")
    clay_api_key: str | None = os.getenv("CLAY_API_KEY")
    clay_base_url: str = os.getenv("CLAY_BASE_URL", "https://api.clay.com")
    clay_mcp_base_url: str = os.getenv("CLAY_MCP_BASE_URL", "https://api.clay.com/v3/mcp")
    sculpt_hack_api_key: str | None = os.getenv("SCULPT_HACK_API_KEY") or os.getenv("CLAY_API_KEY")
    sculpt_hack_auth_header: str = os.getenv("SCULPT_HACK_AUTH_HEADER", "Authorization")
    sculpt_hack_auth_scheme: str = os.getenv("SCULPT_HACK_AUTH_SCHEME", "Bearer")
    sculpt_hack_timeout_seconds: float = float(os.getenv("SCULPT_HACK_TIMEOUT_SECONDS", "30"))
    sculpt_hack_retries: int = int(os.getenv("SCULPT_HACK_RETRIES", "2"))
    clay_company_table_id: str | None = os.getenv("CLAY_COMPANY_TABLE_ID")
    clay_buyer_table_id: str | None = os.getenv("CLAY_BUYER_TABLE_ID")
    clay_tender_table_id: str | None = os.getenv("CLAY_TENDER_TABLE_ID")
    max_chunk_chars: int = int(os.getenv("MAX_CHUNK_CHARS", "12000"))

    # Clay OAuth (for MCP endpoint)
    clay_oauth_client_id: str | None = os.getenv("CLAY_OAUTH_CLIENT_ID")
    clay_oauth_client_secret: str | None = os.getenv("CLAY_OAUTH_CLIENT_SECRET")
    clay_oauth_refresh_token: str | None = os.getenv("CLAY_OAUTH_REFRESH_TOKEN")

    # Server / transport settings
    transport: str = os.getenv("MCP_TRANSPORT", "streamable-http")
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8000"))


settings = Settings()
