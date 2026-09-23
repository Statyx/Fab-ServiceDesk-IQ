#!/usr/bin/env python3
"""Ask the published ``ServiceDesk_Analyst`` Data Agent a question through its MCP endpoint.

A published Fabric Data Agent can be exposed as a remote MCP server (Streamable HTTP,
JSON-RPC 2.0). This client is intentionally tiny — it is what an orchestrator does to
"ground" an answer in Fabric:

  1. ``initialize``                 → server capabilities (+ ``Mcp-Session-Id`` header)
  2. ``notifications/initialized``
  3. ``tools/list``                 → the Data Agent tool(s)
  4. ``tools/call``                 → the question, answered from ontology / DAX / KQL

  python -m fabric.data_agent.mcp_client "Is user USR-FAB-0061 impacted by an open major incident?"
  python -m fabric.data_agent.mcp_client --dry-run "Is Fabrikam in XLA breach this week?"

Endpoint resolution: ``--endpoint`` → state ``data_agent_mcp_url`` → the template in
config ``data_agent.mcp_endpoint_template``. The exact endpoint shape is confirmed at
publish time in phase 2. Auth: a Fabric token from the Azure CLI (``az login``).
"""
import os, sys
from fabric._shared.platform_env import bootstrap
bootstrap()

import argparse
import itertools
import json
from typing import Any, Dict, List, Optional, Tuple

import requests

PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "zava-service-desk-mcp-client", "version": "0.1.0"}
DEFAULT_QUESTION = "Is Fabrikam in XLA breach on zero-touch this week, and what credit applies?"


def rpc(method: str, params: Optional[Dict[str, Any]] = None,
        request_id: Optional[int] = None) -> Dict[str, Any]:
    msg: Dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        msg["params"] = params
    if request_id is not None:
        msg["id"] = request_id
    return msg


def handshake_messages(question: str, tool_name: str = "<first tool from tools/list>",
                       ) -> List[Dict[str, Any]]:
    """The JSON-RPC messages the client sends, in order (used by --dry-run and tests)."""
    return [
        rpc("initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                           "clientInfo": CLIENT_INFO}, 1),
        rpc("notifications/initialized"),
        rpc("tools/list", {}, 2),
        rpc("tools/call", {"name": tool_name, "arguments": question_arguments(question)}, 3),
    ]


def question_arguments(question: str, schema: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Map the question onto the tool's single string argument (whatever its name)."""
    props = (schema or {}).get("properties") or {}
    for name in ("userQuestion", "question", "query", "input", "prompt"):
        if name in props:
            return {name: question}
    for name, spec in props.items():
        if spec.get("type") == "string":
            return {name: question}
    return {"userQuestion": question}


def parse_response(resp: requests.Response) -> Dict[str, Any]:
    """Streamable HTTP answers either plain JSON or an SSE stream of JSON-RPC messages."""
    ctype = resp.headers.get("Content-Type", "")
    if "text/event-stream" in ctype:
        return parse_sse(resp.text)
    return resp.json() if resp.content else {}


def parse_sse(text: str) -> Dict[str, Any]:
    """Return the last JSON-RPC response (a message with ``result`` or ``error``)."""
    found: Dict[str, Any] = {}
    for block in text.replace("\r\n", "\n").split("\n\n"):
        data = "\n".join(line[5:].lstrip() for line in block.split("\n")
                         if line.startswith("data:"))
        if not data:
            continue
        try:
            msg = json.loads(data)
        except json.JSONDecodeError:
            continue
        if "result" in msg or "error" in msg:
            found = msg
    return found


class McpClient:
    def __init__(self, endpoint: str, token: str, timeout: int = 180):
        self.endpoint = endpoint
        self.timeout = timeout
        self.session_id: Optional[str] = None
        self.ids = itertools.count(1)
        self.http = requests.Session()
        self.http.headers.update({"Authorization": "Bearer " + token,
                                  "Content-Type": "application/json",
                                  "Accept": "application/json, text/event-stream"})

    def _post(self, msg: Dict[str, Any]) -> Tuple[requests.Response, Dict[str, Any]]:
        headers = {"MCP-Protocol-Version": PROTOCOL_VERSION}
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        resp = self.http.post(self.endpoint, json=msg, headers=headers, timeout=self.timeout)
        if resp.status_code >= 400:
            raise RuntimeError(f"MCP {msg['method']} failed: HTTP {resp.status_code}\n"
                               f"{resp.text[:800]}")
        self.session_id = resp.headers.get("Mcp-Session-Id", self.session_id)
        body = parse_response(resp) if "id" in msg else {}
        if "error" in body:
            raise RuntimeError(f"MCP {msg['method']} error: {body['error']}")
        return resp, body

    def request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._post(rpc(method, params, next(self.ids)))[1].get("result", {})

    def notify(self, method: str) -> None:
        self._post(rpc(method))

    def ask(self, question: str) -> Tuple[str, Dict[str, Any]]:
        init = self.request("initialize", {"protocolVersion": PROTOCOL_VERSION,
                                           "capabilities": {}, "clientInfo": CLIENT_INFO})
        self.notify("notifications/initialized")
        tools = self.request("tools/list", {}).get("tools", [])
        if not tools:
            raise RuntimeError("The MCP server exposes no tools — is the Data Agent published?")
        tool = tools[0]
        result = self.request("tools/call", {
            "name": tool["name"],
            "arguments": question_arguments(question, tool.get("inputSchema"))})
        text = "\n".join(c.get("text", "") for c in result.get("content", [])
                         if c.get("type") == "text")
        return text, {"server": init.get("serverInfo", {}), "tool": tool["name"],
                      "is_error": result.get("isError", False)}


def resolve_endpoint(explicit: Optional[str]) -> str:
    if explicit:
        return explicit
    from fabric._shared.helpers import is_placeholder, load_config, load_state
    state = load_state()
    if state.get("data_agent_mcp_url") and not is_placeholder(state["data_agent_mcp_url"]):
        return state["data_agent_mcp_url"]
    cfg = load_config()
    template = (cfg.get("data_agent") or {}).get("mcp_endpoint_template", "")
    ids = {"workspace_id": state.get("workspace_id", ""),
           "data_agent_id": state.get("data_agent_id", "")}
    if not template or not all(ids.values()):
        raise SystemExit("No MCP endpoint: pass --endpoint, or publish the Data Agent "
                         "(phase 2) so state.json holds data_agent_mcp_url.")
    return template.format(**ids)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Query the ServiceDesk_Analyst Data Agent over MCP.")
    ap.add_argument("question", nargs="?", default=DEFAULT_QUESTION)
    ap.add_argument("--endpoint", help="MCP endpoint URL (default: from state/config).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the JSON-RPC messages instead of calling the endpoint.")
    args = ap.parse_args(argv)

    if args.dry_run:
        print(json.dumps({"endpoint": args.endpoint or "<resolved from state/config>",
                          "messages": handshake_messages(args.question)}, indent=2))
        return 0

    from fabric._shared.helpers import get_fabric_token
    endpoint = resolve_endpoint(args.endpoint)
    client = McpClient(endpoint, get_fabric_token())
    answer, meta = client.ask(args.question)
    print(f"Q: {args.question}\n[{meta['tool']}]\n")
    print(answer or "(empty answer)")
    return 1 if meta["is_error"] else 0


if __name__ == "__main__":
    sys.exit(main())
