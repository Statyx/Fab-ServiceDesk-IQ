#!/usr/bin/env python3
"""Deploy the ``OA_ServiceDesk_Ops`` Fabric Operations Agent over ``KQL_ServiceDesk``.

The Operations Agent watches the Eventhouse and raises alerts in plain language, naming
the site or AI agent and the metric that breached. This script creates the item
(``/OperationsAgents``) and pushes ``Configurations.json`` with goals + instructions and
``shouldRun: false``.

What the API cannot do (verified on Fab-Network-Operations, 2026-06): a raw definition
push zeroes the Knowledge Source id, drops the message destination and rejects an empty
playbook. Finish in the Fabric UI: add Knowledge Source = KQL database ``KQL_ServiceDesk``,
set the Teams / email destination, Generate playbook, set a schedule, then enable.

  python -m fabric.rti.deploy_operations_agent
"""
import os, sys
from fabric._shared.platform_env import bootstrap
bootstrap()

import time

import requests

from fabric._shared.helpers import (deploy_context, fabric_headers, part, print_step,
                                    save_state, wait_lro)

SCHEMA = ("https://developer.microsoft.com/json-schemas/fabric/item/operationsAgents/"
          "definition/1.0.0/schema.json")

GOALS = """You are the operations agent of the Zava Service Desk, a managed service desk
run by AI agents for several enterprise customers. You continuously monitor the live
end-user experience telemetry and the AI agent telemetry in the Eventhouse, and you alert
the service desk lead the moment a customer site or an AI agent breaches a threshold,
naming the site (and its customer) or the agent, and the metric that breached. Whenever
you raise an alert, also state the single most likely next step: for high VPN latency or a
low experience score at a site, recommend checking the VPN concentrator serving that site
and opening a major incident so the AI agents can deflect the ticket wave; for AI agent
errors, recommend checking the upstream tool the agent calls and routing its work to a
human (HITL); for gateway throttling (HTTP 429), recommend raising the model deployment
quota or spreading traffic across deployments."""

INSTRUCTIONS = """*** Operational Instructions ***
1. Alert me when a site has high VPN latency.
2. Alert me when a site has a low experience score.
3. Alert me when an AI agent has a spike of errors.
4. Alert me when the AI gateway throttles requests.

*** Semantic Instructions ***
1. The "dem_telemetry" table holds end-user device telemetry. Each record belongs to ONE
   site, uniquely identified by the "site_id" column. Use only "site_id" as the entity
   identifier for this table; ignore "device_id" and "user_id" for identity. The
   "customer_id" column names the customer that owns the site.
2. VPN latency is the "vpn_latency_ms" column. High VPN latency is an average above 200
   over the last 5 minutes.
3. The experience score is the "experience_score" column (0 to 100). A low experience
   score is an average below 60 over the last 15 minutes.
4. The "agent_traces" table holds AI agent spans. Each record belongs to ONE agent,
   uniquely identified by the "agent_id" column. A span failed when "status" is "error";
   the "error_type" column says why. A spike of errors is more than 10 failed spans for
   the same agent in 15 minutes.
5. The "gateway_logs" table holds AI gateway requests. Each record belongs to ONE agent,
   uniquely identified by the "agent_id" column. Throttling is a "status_code" of 429.
   Alert when an agent gets more than 5 throttled requests in 15 minutes.
6. Use the "timestamp" column to evaluate the most recent data."""


def find_agent(api: str, ws: str, headers: dict, name: str):
    items = requests.get(f"{api}/workspaces/{ws}/items", headers=headers,
                         timeout=60).json().get("value", [])
    for it in items:
        if it.get("type") in ("OperationsAgent", "OperationsAgents") and \
                it.get("displayName") == name:
            return it["id"]
    return None


def main() -> int:
    cfg, state, api, ws, token = deploy_context()
    name = (cfg.get("operations_agent") or {}).get("name", "OA_ServiceDesk_Ops")
    headers = fabric_headers(token)

    print_step(1, 3, f"Create Operations Agent '{name}'")
    aid = find_agent(api, ws, headers, name)
    if aid:
        print(f"   reusing {aid}")
    else:
        resp = requests.post(f"{api}/workspaces/{ws}/OperationsAgents", headers=headers,
                             timeout=60, json={
                                 "displayName": name,
                                 "description": "Zava Service Desk real-time monitor over "
                                                "KQL_ServiceDesk (finish bindings in the UI)"})
        body = wait_lro(token, api, resp, f"Create OperationsAgent '{name}'")
        aid = (body or {}).get("id")
        for _ in range(6):
            if aid:
                break
            time.sleep(5)
            aid = find_agent(api, ws, headers, name)
        if not aid:
            raise RuntimeError(f"Operations Agent '{name}' not found after create")
        print(f"   created {aid}")

    print_step(2, 3, "Push Configurations.json (goals + instructions, shouldRun=false)")
    config = {"$schema": SCHEMA,
              "configuration": {"goals": GOALS, "instructions": INSTRUCTIONS,
                                "dataSources": {}, "actions": {}},
              "shouldRun": False}
    resp = requests.post(f"{api}/workspaces/{ws}/items/{aid}/updateDefinition",
                         headers=headers, timeout=120,
                         json={"definition": {"parts": [part("Configurations.json", config)]}})
    wait_lro(token, api, resp, "updateDefinition OperationsAgent")
    print("   goals + instructions uploaded")

    print_step(3, 3, "Persist state")
    state["operations_agent_id"] = aid
    save_state(state)
    print("   operations_agent_id saved")
    print("\n   Finish in the Fabric UI: Knowledge Source = KQL_ServiceDesk, destination "
          "(Teams/email), Generate playbook, schedule, then enable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
