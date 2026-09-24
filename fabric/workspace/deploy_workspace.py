#!/usr/bin/env python3
"""Find or create the workspace (config ``workspace_name``) and assign it to the capacity.

Idempotent. Saves ``workspace_id`` to the profile's state.json.

  python -m fabric.workspace.deploy_workspace
"""
import os, sys
from fabric._shared.platform_env import bootstrap
bootstrap()

import requests

from fabric._shared.helpers import (check_account, configure_profile_cli, fabric_headers,
                                    get_fabric_token, load_config, load_state,
                                    poll_operation, print_step, require_config, save_state)

DESCRIPTION = ("Zava Service Desk: data foundation of an agentic service desk "
               "(ontology, graph, real-time intelligence, AgentOps, XLA value). Synthetic data.")


def _find_workspace(api: str, h: dict, name: str):
    url = f"{api}/workspaces"
    while url:
        body = requests.get(url, headers=h, timeout=60).json()
        for w in body.get("value", []):
            if w.get("displayName") == name:
                return w
        url = body.get("continuationUri")
    return None


def main() -> int:
    cfg, state = load_config(), load_state()
    configure_profile_cli(cfg)
    api = require_config(cfg, "fabric_api_base")
    name = require_config(cfg, "workspace_name")
    cap = require_config(cfg, "capacity_id")

    print_step(1, 4, "Check account and capacity")
    print(f"   signed in as {check_account(cfg)}")
    token = get_fabric_token()
    h = fabric_headers(token)
    caps = requests.get(f"{api}/capacities", headers=h, timeout=60).json().get("value", [])
    c = next((c for c in caps if c.get("id", "").lower() == str(cap).lower()), None)
    if not c:
        raise RuntimeError("The capacity from config.yaml is not visible to this account")
    print(f"   {c.get('displayName')} | {c.get('sku')} | {c.get('region')} | {c.get('state')}")
    if c.get("state") != "Active":
        raise RuntimeError(f"Capacity state is {c.get('state')}, not Active")

    print_step(2, 4, f"Find or create workspace '{name}'")
    ws = _find_workspace(api, h, name)
    if ws:
        ws_id = ws["id"]
        print(f"   reusing {ws_id}")
    else:
        r = requests.post(f"{api}/workspaces", headers=h,
                          json={"displayName": name, "description": DESCRIPTION}, timeout=60)
        if r.status_code == 202 and r.headers.get("x-ms-operation-id"):
            poll_operation(token, api, r.headers["x-ms-operation-id"])
            ws_id = _find_workspace(api, h, name)["id"]
        elif r.status_code in (200, 201):
            ws_id = r.json()["id"]
        else:
            raise RuntimeError(f"Create workspace failed ({r.status_code}): {r.text[:400]}")
        print(f"   created {ws_id}")

    print_step(3, 4, "Assign capacity")
    r = requests.post(f"{api}/workspaces/{ws_id}/assignToCapacity", headers=h,
                      json={"capacityId": cap}, timeout=60)
    if r.status_code == 202 and r.headers.get("x-ms-operation-id"):
        poll_operation(token, api, r.headers["x-ms-operation-id"])
    elif r.status_code not in (200, 202) and "already" not in r.text.lower():
        raise RuntimeError(f"assignToCapacity failed ({r.status_code}): {r.text[:300]}")
    print("   assigned")

    print_step(4, 4, "Persist state")
    state["workspace_id"] = ws_id
    save_state(state)
    print(f"   workspace_id saved")
    return 0


if __name__ == "__main__":
    sys.exit(main())
