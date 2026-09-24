#!/usr/bin/env python3
"""Configure and deploy ``App-Zava-Service-Desk``, the Rayfin console (phase 3).

The console is a React + Vite app in ``app-zava-service-desk/``, hosted by Rayfin inside
Fabric. It reads SM_ServiceDesk_Analytics through the Fabric embed proxy (DAX, no secret
in the app) and links out to the live items: the RTI dashboard, the Power BI report, the
Data Agent, the Activator and the workspace.

Nothing tenant-specific is committed. This script writes, from config + state:

  app-zava-service-desk/fabric.yaml                 semantic model connection (git-ignored)
  app-zava-service-desk/src/fabric.generated.ts     generated from fabric.yaml (git-ignored)
  app-zava-service-desk/public/app-config.json      portal links + demo questions (git-ignored)

then runs ``rayfin up`` (it opens a browser sign-in when the Rayfin token has expired)
and saves ``app_item_id`` / ``app_url`` in state.

  python -m fabric.app.deploy_app                    # configure + deploy
  python -m fabric.app.deploy_app --configure-only   # write the local config files only
  python -m fabric.app.deploy_app --dry-run          # rayfin up --dry-run
"""
import os, sys
from fabric._shared.platform_env import bootstrap
bootstrap()

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from fabric._shared.helpers import (is_placeholder, load_config, load_state, print_step,
                                    require_config, require_state, save_state)
from fabric._shared.paths import ROOT
from fabric.data_agent.deploy_data_agent import DAX_FEWSHOTS, GQL_FEWSHOTS, KQL_FEWSHOTS

APP_DIR = Path(ROOT) / "app-zava-service-desk"
PORTAL = "https://app.fabric.microsoft.com"
CONNECTION = "serviceDesk"
NPX = "npx.cmd" if os.name == "nt" else "npx"
NPM = "npm.cmd" if os.name == "nt" else "npm"

# Files written by this script from config + state. They hold tenant IDs: git-ignored.
GENERATED_FILES = ("fabric.yaml", "src/fabric.generated.ts", "public/app-config.json")

# (key, label, portal path segment, state key, what it shows)
PORTAL_ITEMS = [
    ("rti_dashboard", "Real-Time dashboard", "kustodashboards", "rti_dashboard_id",
     "Live telemetry, AI agent errors and gateway throttling (Eventhouse)"),
    ("report", "Power BI report", "reports", "report_id",
     "XLA, zero-touch, CSAT and experience over closed weeks"),
    ("data_agent", "Data Agent", "aiskills", "data_agent_id",
     "Ask ServiceDesk_Analyst across the ontology, the semantic model and the Eventhouse"),
    ("activator", "Activator", "reflexes", "activator_id",
     "Alert rules on VPN latency and experience score"),
    ("semantic_model", "Semantic model", "datasets", "semantic_model_id",
     "SM_ServiceDesk_Analytics, the measures behind every number"),
]


def portal_links(state: Dict[str, Any]) -> List[Dict[str, str]]:
    ws = require_state(state, "workspace_id")
    links = []
    for key, label, segment, state_key, description in PORTAL_ITEMS:
        item = state.get(state_key)
        if item:
            links.append({"key": key, "label": label, "description": description,
                          "url": f"{PORTAL}/groups/{ws}/{segment}/{item}"})
    links.append({"key": "workspace", "label": "Workspace", "url": f"{PORTAL}/groups/{ws}/list",
                  "description": "Every item, including the ontology and the Operations Agent"})
    return links


def demo_questions() -> List[Dict[str, str]]:
    """The Data Agent few-shots: each one is run live on its source at deploy time."""
    out = []
    for source, shots in (("Ontology (GQL)", GQL_FEWSHOTS), ("Semantic model (DAX)", DAX_FEWSHOTS),
                          ("Eventhouse (KQL)", KQL_FEWSHOTS)):
        out += [{"source": source, "question": q} for q, _ in shots]
    return out


def app_config(cfg: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
    return {"workspaceName": require_config(cfg, "workspace_name"),
            "links": portal_links(state),
            "questions": demo_questions()}


def fabric_yaml(state: Dict[str, Any]) -> str:
    return ("activeProfile: default\n"
            "profiles:\n"
            "  default:\n"
            "    semanticModels:\n"
            f"      {CONNECTION}:\n"
            f"        workspaceId: {require_state(state, 'workspace_id')}\n"
            f"        itemId: {require_state(state, 'semantic_model_id')}\n")


def run(cmd: List[str]) -> None:
    print("   $", " ".join(cmd))
    subprocess.run(cmd, cwd=APP_DIR, check=True)


def configure(cfg: Dict[str, Any], state: Dict[str, Any]) -> None:
    (APP_DIR / "fabric.yaml").write_text(fabric_yaml(state), encoding="utf-8")
    public = APP_DIR / "public"
    public.mkdir(exist_ok=True)
    conf = app_config(cfg, state)
    (public / "app-config.json").write_text(json.dumps(conf, indent=2), encoding="utf-8")
    print(f"   fabric.yaml ({CONNECTION}) + app-config.json "
          f"({len(conf['links'])} links, {len(conf['questions'])} questions)")
    if not (APP_DIR / "node_modules").exists():
        run([NPM, "ci", "--no-audit", "--no-fund"])
    run([NPX, "fabric-app-data", "generate", "-o", "src/fabric.generated.ts"])


def rayfin_up_command(cfg: Dict[str, Any], state: Dict[str, Any], dry_run: bool = False) -> List[str]:
    """``rayfin up`` into the demo workspace, by id: no display-name lookup."""
    up = [NPX, "rayfin", "up", "--workspace-id", require_state(state, "workspace_id"), "--yes"]
    tenant = cfg.get("tenant_id")
    if not is_placeholder(tenant):
        up += ["-t", str(tenant)]
    return up + (["--dry-run"] if dry_run else [])


def deployment_record() -> Dict[str, Any]:
    path = APP_DIR / "rayfin" / ".deployments.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    stack = [data]
    while stack:  # the record layout varies by CLI version: find the first item id
        node = stack.pop()
        if isinstance(node, dict):
            if node.get("fabricItemId") or node.get("itemId"):
                return node
            stack += list(node.values())
        elif isinstance(node, list):
            stack += node
    return {}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--configure-only", action="store_true",
                    help="write fabric.yaml, fabric.generated.ts and app-config.json only")
    ap.add_argument("--dry-run", action="store_true", help="rayfin up --dry-run")
    args = ap.parse_args()

    cfg, state = load_config(), load_state()

    print_step(1, 3, "Write the app configuration from config + state")
    configure(cfg, state)
    if args.configure_only:
        return 0

    print_step(2, 3, "Build and deploy with rayfin up (browser sign-in if the token expired)")
    run(rayfin_up_command(cfg, state, dry_run=args.dry_run))
    if args.dry_run:
        return 0

    print_step(3, 3, "Persist state")
    record = deployment_record()
    item_id = record.get("fabricItemId") or record.get("itemId")
    if item_id:
        state["app_item_id"] = item_id
        state["app_url"] = record.get("hostingUrl") or record.get("url") or ""
        save_state(state)
        print("   app_item_id / app_url saved to state")
    else:
        print("   no deployment record found in rayfin/.deployments.json; state unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
