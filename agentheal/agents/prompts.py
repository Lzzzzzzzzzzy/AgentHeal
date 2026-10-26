"""How an episode is handed to an agent.
"""
from __future__ import annotations

ROLE_REAL = (
    "You are a web agent working for a user. Use the search tool to search the web and the other tools to "
    "open pages, call APIs and download files."
)

ROLE_SANDBOX = (
    "You are a web agent working for a user inside a sandboxed web. "
    "All sites use fictional *.example domains over http. "
    "Search with the search tool, or open http://search.example. "
    "Other services are listed at http://search.example/services."
)


def _real(ep: dict) -> bool:
    return str(ep.get("episode_id", ep.get("id", ""))).startswith("R-")


def system_context(ep: dict) -> str:
    """Role and environment for the system channel."""
    return ROLE_REAL if _real(ep) else ROLE_SANDBOX


def user_message(ep: dict) -> str:
    return ep["goal"]


def task_prompt(ep: dict, policy: str = "explicit") -> str:
    """The user turn. `policy` is kept for callers; it is not written into the request."""
    del policy
    return user_message(ep)
