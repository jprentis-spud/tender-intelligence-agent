"""Lightweight proxy client for Sculpt_Hack MCP HTTP gateway."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests


@dataclass(frozen=True)
class SculptHackProxyConfig:
    base_url: str
    api_key: str
    auth_header: str = "Authorization"
    auth_scheme: str = "Bearer"
    timeout_seconds: float = 30.0
    retries: int = 2


class SculptHackProxyClient:
    """Proxy wrapper with conservative endpoint fallback for Clay MCP gateway."""

    def __init__(self, config: SculptHackProxyConfig) -> None:
        self.config = config

    @property
    def _headers(self) -> dict[str, str]:
        token_value = f"{self.config.auth_scheme} {self.config.api_key}".strip()
        return {
            self.config.auth_header: token_value,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    @property
    def _candidate_urls(self) -> list[str]:
        base = self.config.base_url.rstrip("/")
        return [
            f"{base}/tools/call",
            f"{base}/tool/call",
            f"{base}/call-tool",
            base,
        ]

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a remote Sculpt_Hack tool with fallback payload/endpoint formats."""
        last_error: Exception | None = None
        attempts = max(1, self.config.retries)

        payloads: list[dict[str, Any]] = [
            {"name": tool_name, "arguments": arguments},
            {"tool": tool_name, "input": arguments},
            {"method": "tools/call", "params": {"name": tool_name, "arguments": arguments}},
            {"jsonrpc": "2.0", "id": "1", "method": "tools/call", "params": {"name": tool_name, "arguments": arguments}},
        ]

        for _ in range(attempts):
            for url in self._candidate_urls:
                for payload in payloads:
                    try:
                        response = requests.post(
                            url,
                            headers=self._headers,
                            json=payload,
                            timeout=self.config.timeout_seconds,
                        )
                        if response.status_code in {404, 405, 422}:
                            continue
                        response.raise_for_status()
                        body = response.json()
                        if isinstance(body, dict):
                            # Normalize common MCP wrappers.
                            if isinstance(body.get("result"), dict):
                                return body["result"]
                            if isinstance(body.get("data"), dict):
                                return body["data"]
                            return body
                    except requests.RequestException as exc:
                        last_error = exc
                        continue

        detail = str(last_error) if last_error else "Unknown proxy error"
        raise RuntimeError(f"Sculpt_Hack proxy call failed for tool '{tool_name}': {detail}")

