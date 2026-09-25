#!/usr/bin/env python3
"""tools.py  --  pluggable tool wiring for the TOOLS axis
=========================================================

The TOOLS axis of the grid is on/off:

  off -- the model answers from its own knowledge only (no `tools` sent).
  on  -- the model gets a retrieval tool it can call.

Both are `ToolProvider`s. The runner only ever sees this interface, so swapping
web search for a fixed-literature-corpus retrieval tool later is a matter of
adding one class here and pointing config.yaml at it -- `run_study.py`,
`parse.py` and `aggregate.py` do not change.

To add a corpus retriever later
-------------------------------
Implement the three members below (`name`, `tool_definitions`, `extract_usage`).
A client-side tool also needs an execution loop, which `WebSearchTools` does not
require because web search runs server-side; put that loop inside the provider
so the runner still just calls `tool_definitions()` once and reads usage once.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ToolProvider(Protocol):
    """What the runner needs from any tool setting."""

    name: str

    def tool_definitions(self) -> list[dict[str, Any]]:
        """The `tools` list passed to the Messages API ([] = send no tools)."""
        ...

    def extract_usage(self, response: Any) -> dict[str, Any]:
        """Per-call tool telemetry: {tool_calls_count, tool_tokens}."""
        ...


class NoTools:
    """Tools OFF -- the model answers from its own knowledge only."""

    name = "off"

    def tool_definitions(self) -> list[dict[str, Any]]:
        return []

    def extract_usage(self, response: Any) -> dict[str, Any]:
        return {"tool_calls_count": 0, "tool_tokens": None}


class WebSearchTools:
    """Tools ON -- Anthropic server-side web search.

    Server-side: the model issues searches and the results come back inside the
    same response, so there is no client-side execution loop to run.

    The tool `type` is version-pinned in config.yaml. The installed SDK
    (anthropic 0.75.0) ships `web_search_20250305`; the newer
    `web_search_20260209` (dynamic filtering) needs a much newer SDK. Bump the
    config value after upgrading -- no code change needed.
    """

    name = "on"

    def __init__(self, tool_cfg: dict[str, Any]):
        ws = (tool_cfg or {}).get("web_search") or {}
        self.type = ws.get("type", "web_search_20250305")
        self.tool_name = ws.get("name", "web_search")
        self.max_uses = ws.get("max_uses")

    def tool_definitions(self) -> list[dict[str, Any]]:
        d: dict[str, Any] = {"type": self.type, "name": self.tool_name}
        if self.max_uses is not None:
            d["max_uses"] = int(self.max_uses)
        return [d]

    def extract_usage(self, response: Any) -> dict[str, Any]:
        """Count server-side searches and read tool token usage if reported.

        `server_tool_use.web_search_requests` is the count of searches the model
        actually ran. Token attribution for server tools is folded into the
        normal input/output counts, so `tool_tokens` stays None unless the API
        reports it separately.
        """
        count = 0
        tool_tokens = None

        usage = getattr(response, "usage", None)
        server_tool_use = getattr(usage, "server_tool_use", None)
        if server_tool_use is not None:
            count = int(getattr(server_tool_use, "web_search_requests", 0) or 0)

        # Fall back to counting server_tool_use blocks in the content when the
        # usage field is absent (older/newer SDK shapes differ here).
        if not count:
            for block in getattr(response, "content", None) or []:
                if getattr(block, "type", None) == "server_tool_use":
                    count += 1

        return {"tool_calls_count": count, "tool_tokens": tool_tokens}


def get_tool_provider(setting: str, tool_cfg: dict[str, Any]) -> ToolProvider:
    """Resolve a TOOLS axis value ("on"/"off") to a provider."""
    s = (setting or "").strip().lower()
    if s in ("off", "false", "none", "no"):
        return NoTools()
    if s in ("on", "true", "web_search", "yes"):
        return WebSearchTools(tool_cfg)
    raise ValueError(f"unknown tools setting {setting!r}; expected 'on' or 'off'")


TOOL_SETTINGS = ("off", "on")
