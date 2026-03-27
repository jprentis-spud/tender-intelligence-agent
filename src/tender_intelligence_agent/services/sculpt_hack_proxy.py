"""Clay MCP client with OAuth auth, falling back to REST API.

Uses Clay's MCP endpoint via Streamable HTTP when OAuth credentials are
configured. Falls back to Clay's REST API when only an API key is available.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

from tender_intelligence_agent.services.async_bridge import run_coro
from tender_intelligence_agent.services.clay_oauth import ClayOAuthAuth

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SculptHackProxyConfig:
    base_url: str
    timeout_seconds: float = 30.0
    retries: int = 2
    # OAuth credentials (for MCP mode)
    oauth_client_id: str | None = None
    oauth_client_secret: str | None = None
    oauth_refresh_token: str | None = None
    # Legacy API key (for REST fallback)
    api_key: str | None = None
    company_table_id: str | None = None
    contacts_table_id: str | None = None

    @property
    def oauth_configured(self) -> bool:
        return bool(self.oauth_client_id and self.oauth_client_secret and self.oauth_refresh_token)


class SculptHackProxyClient:
    """Calls Clay tools via MCP (OAuth) or REST API (API key) depending on config."""

    def __init__(self, config: SculptHackProxyConfig) -> None:
        self.config = config
        self._auth: ClayOAuthAuth | None = None

    def _get_oauth_auth(self) -> ClayOAuthAuth:
        if self._auth is None:
            self._auth = ClayOAuthAuth(
                client_id=self.config.oauth_client_id or "",
                client_secret=self.config.oauth_client_secret or "",
                refresh_token=self.config.oauth_refresh_token or "",
            )
        return self._auth

    # ── MCP mode ──────────────────────────────────────────────────────────

    async def _call_tool_mcp_async(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool on Clay's MCP server via Streamable HTTP with OAuth."""
        url = self.config.base_url.rstrip("/")
        logger.info("Connecting to Clay MCP at %s (OAuth mode)", url)

        auth = self._get_oauth_auth()
        http_client = create_mcp_http_client(
            timeout=httpx.Timeout(self.config.timeout_seconds, read=self.config.timeout_seconds * 5),
            auth=auth,
        )

        async with http_client:
            async with streamable_http_client(url, http_client=http_client) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()

                    logger.info("Calling tool '%s' with args: %s", tool_name, list(arguments.keys()))
                    result = await session.call_tool(tool_name, arguments)

                    if result.isError:
                        error_text = " ".join(
                            getattr(c, "text", str(c)) for c in result.content
                        )
                        raise RuntimeError(
                            f"Clay MCP tool '{tool_name}' returned error: {error_text}"
                        )

                    if result.structuredContent and isinstance(result.structuredContent, dict):
                        return result.structuredContent

                    for content_block in result.content:
                        text = getattr(content_block, "text", None)
                        if text:
                            try:
                                parsed = json.loads(text)
                                if isinstance(parsed, dict):
                                    return parsed
                            except (json.JSONDecodeError, TypeError):
                                continue

                    texts = [getattr(c, "text", str(c)) for c in result.content]
                    return {"raw_content": texts, "tool": tool_name}

    # ── REST fallback mode ────────────────────────────────────────────────

    async def _call_tool_rest_async(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Fallback: call Clay's REST API directly (API key auth)."""
        from tender_intelligence_agent.services.clay_client import ClayComClient

        if not self.config.api_key:
            raise ValueError("No Clay API key configured for REST fallback")

        client = ClayComClient(api_key=self.config.api_key, base_url=self.config.base_url)

        if tool_name == "find-and-enrich-company":
            company_id = arguments.get("companyIdentifier", "")
            if not company_id:
                raise ValueError("companyIdentifier is required")
            if not self.config.company_table_id:
                raise ValueError("CLAY_COMPANY_TABLE_ID is required for REST-based enrichment")

            result = await client.get_by_domain(self.config.company_table_id, company_id)
            if not result:
                result = await client.get_by_field(self.config.company_table_id, "company_name", company_id)
            if not result:
                return {"companyIdentifier": company_id, "found": False}
            return {**result, "companyIdentifier": company_id, "found": True}

        elif tool_name == "find-and-enrich-contacts-at-company":
            company_id = arguments.get("companyIdentifier", "")
            if not company_id or not self.config.contacts_table_id:
                return {"companyIdentifier": company_id, "contacts": [], "found": False}
            result = await client.get_by_field(self.config.contacts_table_id, "company_domain", company_id, limit=10)
            contacts = result if isinstance(result, list) else ([result] if result else [])
            return {"companyIdentifier": company_id, "contacts": contacts, "found": bool(contacts)}

        raise ValueError(f"Unknown tool: {tool_name}")

    # ── Public interface ──────────────────────────────────────────────────

    async def _call_tool_async(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.config.oauth_configured:
            return await self._call_tool_mcp_async(tool_name, arguments)
        logger.warning("Clay OAuth not configured, using REST API fallback")
        return await self._call_tool_rest_async(tool_name, arguments)

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Sync wrapper — call Clay via MCP (OAuth) or REST (API key)."""
        last_error: Exception | None = None

        for attempt in range(max(1, self.config.retries)):
            try:
                return run_coro(
                    lambda: self._call_tool_async(tool_name, arguments),
                    timeout=self.config.timeout_seconds + 10,
                )
            except Exception as exc:
                logger.warning(
                    "Clay call attempt %d/%d for '%s' failed: %s",
                    attempt + 1,
                    self.config.retries,
                    tool_name,
                    exc,
                )
                last_error = exc

        detail = str(last_error) if last_error else "Unknown Clay error"
        raise RuntimeError(f"Clay call failed for tool '{tool_name}': {detail}")
