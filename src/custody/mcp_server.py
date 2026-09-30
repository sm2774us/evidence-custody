"""Read-only MCP server so an agent (e.g. a shift-supervisor copilot) can *observe* custody
health. It exposes no write, download or delete tools; every call is audited under the
gateway principal. Requires the `mcp` extra:  pip install 'evidence-custody[mcp]'"""

from __future__ import annotations

from typing import Any

from .app import build_service
from .audit import Ctx
from .auth import Principal, Role
from .config import Settings


def build_server(agency: str = "agency-1") -> Any:  # pragma: no cover - needs optional dep
    try:  # mcp >= 2 renamed FastMCP -> MCPServer
        from mcp.server.mcpserver import MCPServer as FastMCP
    except ImportError:
        from mcp.server.fastmcp import FastMCP  # type: ignore[no-redef,attr-defined]

    svc = build_service(Settings.from_env().with_dev_secrets())
    gw = Principal("mcp-gateway", Role.AUDITOR, agency)
    ctx = Ctx(ip="mcp", request_id="mcp")
    mcp = FastMCP("evidence-custody")

    @mcp.tool()
    def open_alerts() -> list[dict[str, Any]]:
        """List open integrity/access alerts with their triage advisories."""
        return svc.list_alerts(gw, "open", ctx)

    @mcp.tool()
    def verify_audit_chain() -> dict[str, Any]:
        """Recompute the audit hash chain and verify signed checkpoints."""
        s = svc.audit.verify()
        return {"ok": s.ok, "entries": s.entries, "error": s.error}

    @mcp.tool()
    def upload_status(session_id: str) -> dict[str, Any]:
        """State machine position and audit trail for one upload session."""
        return svc.upload_inspect(gw, session_id, ctx)

    @mcp.tool()
    def explain_quarantine(session_id: str) -> dict[str, Any]:
        """Deterministic (+ optional AI-enriched) advisory for a quarantined upload."""
        return svc.triage_session(gw, session_id, ctx).model_dump()

    return mcp


if __name__ == "__main__":  # pragma: no cover
    build_server().run()
