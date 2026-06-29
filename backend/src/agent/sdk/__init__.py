"""Claude Agent SDK integration: in-process MCP tool servers + the query() loop.

Replaces the hand-rolled AgentRuntime/ToolRegistry/OrchestratorAgent engine. Tools
are exposed to the agents as schema-validated in-process MCP servers
(create_sdk_mcp_server), and each agent (orchestrator + 3 workers) runs as its own
query() loop. See servers.py (tool servers), worker.py (run_worker), and
orchestrator.py (delegate + event stream).
"""
