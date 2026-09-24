#!/usr/bin/env python3
"""One-shot idempotent orchestrator for the Zava Service Desk Fabric demo.

Runs every deploy step in dependency order. Each step reuses the items recorded in
``state.json``, so a re-run resumes rather than duplicates. Each step runs as its own
``python -m`` process (no shell), which keeps every module's own CLI and exit code.

  python deploy_all.py                          # full deploy, then warm-up
  python deploy_all.py --from ontology          # resume from a step to the end
  python deploy_all.py semantic_model report    # only these steps (canonical order)
  python deploy_all.py --skip generate_data     # keep the current dataset
  python deploy_all.py --list                   # print the steps and exit
  python deploy_all.py --warmup                 # warm-up only

Steps that are UI-only after this script (Operations Agent bindings, Activator start,
Teams recipient) are listed in the README.
"""
import os, sys
from fabric._shared.platform_env import bootstrap
bootstrap()

import argparse
import subprocess
import time
from typing import List, Tuple

STEPS: List[Tuple[str, str, List[str]]] = [
    ("generate_data",     "fabric.data.generate_data",               ["--shift-weeks", "auto"]),
    ("workspace",         "fabric.workspace.deploy_workspace",        []),
    ("lakehouse",         "fabric.lakehouse.deploy_lakehouse",        []),
    ("setup_notebook",    "fabric.lakehouse.deploy_setup_notebook",   []),
    ("eventhouse",        "fabric.eventhouse.deploy_eventhouse",      []),
    ("preload",           "fabric.eventhouse.preload_eventhouse",     []),
    ("ontology",          "fabric.ontology.deploy_ontology",          []),
    ("graph",             "fabric.graph.deploy_graph",                []),
    ("semantic_model",    "fabric.powerbi.deploy_semantic_model",     []),
    ("verify_model",      "fabric.powerbi.verify_semantic_model",     []),
    ("report",            "fabric.powerbi.deploy_report",             []),
    ("dashboard",         "fabric.rti.deploy_dashboard",              []),
    ("activator",         "fabric.rti.deploy_activator",              []),
    ("operations_agent",  "fabric.rti.deploy_operations_agent",       []),
    ("data_agent",        "fabric.data_agent.deploy_data_agent",      []),
    ("app",               "fabric.app.deploy_app",                    []),
]
STEP_NAMES = [s[0] for s in STEPS]


def select_steps(steps: List[str], from_step: str, skip: str) -> List[str]:
    if steps:
        unknown = [s for s in steps if s not in STEP_NAMES]
        if unknown:
            raise SystemExit(f"Unknown step(s): {unknown}. Valid: {STEP_NAMES}")
        chosen = [s for s in STEP_NAMES if s in steps]
    elif from_step:
        if from_step not in STEP_NAMES:
            raise SystemExit(f"Unknown --from step '{from_step}'. Valid: {STEP_NAMES}")
        chosen = STEP_NAMES[STEP_NAMES.index(from_step):]
    else:
        chosen = list(STEP_NAMES)
    skipped = {s.strip() for s in (skip or "").split(",") if s.strip()}
    unknown = skipped - set(STEP_NAMES)
    if unknown:
        raise SystemExit(f"Unknown --skip step(s): {sorted(unknown)}. Valid: {STEP_NAMES}")
    return [s for s in chosen if s not in skipped]


def run_steps(names: List[str]) -> None:
    spec = {name: (module, args) for name, module, args in STEPS}
    root = os.path.dirname(os.path.abspath(__file__))
    for i, name in enumerate(names, 1):
        module, args = spec[name]
        print(f"\n{'=' * 72}\n[{i}/{len(names)}] {name}  (python -m {module} {' '.join(args)})\n{'=' * 72}",
              flush=True)
        t0 = time.time()
        rc = subprocess.call([sys.executable, "-m", module, *args], cwd=root)
        if rc != 0:
            raise SystemExit(f"\nStep '{name}' failed (exit {rc}). Fix it, then resume with:\n"
                             f"  python deploy_all.py --from {name}")
        print(f"   ✓ {name} done in {time.time() - t0:.0f}s", flush=True)
    print(f"\n✓ {len(names)} step(s) completed.")


def warm_up() -> None:
    """Pay the first-query latency (Fabric auth, Kusto cold start) off-stage."""
    import requests
    from fabric._shared.helpers import (deploy_context, fabric_headers, get_kusto_token,
                                        kusto_query)
    print("\nWarm-up")
    try:
        cfg, state, api, ws, token = deploy_context()
        items = requests.get(f"{api}/workspaces/{ws}/items", headers=fabric_headers(token),
                             timeout=60).json().get("value", [])
        print(f"   Fabric OK: {len(items)} items in the workspace")
        uri = state["kusto_query_uri"]
        t0 = time.time()
        rows = kusto_query(uri, get_kusto_token(uri), cfg["eventhouse"]["kql_database"],
                           "dem_telemetry | summarize n = count(), latest = max(timestamp)")
        print(f"   Kusto OK: {rows[0][0]} telemetry rows, latest {rows[0][1]} "
              f"({time.time() - t0:.1f}s)")
    except Exception as e:  # warm-up is best effort
        print(f"   warm-up skipped: {e}")


def main() -> int:
    p = argparse.ArgumentParser(description="Zava Service Desk deploy orchestrator")
    p.add_argument("steps", nargs="*", help=f"run only these steps. Valid: {STEP_NAMES}")
    p.add_argument("--from", dest="from_step", help="resume from this step to the end")
    p.add_argument("--skip", help="comma-separated steps to skip")
    p.add_argument("--list", action="store_true", help="print the steps and exit")
    p.add_argument("--warmup", action="store_true", help="warm-up only, no deploy")
    p.add_argument("--no-warmup", dest="no_warmup", action="store_true")
    args = p.parse_args()

    if args.list:
        for name, module, extra in STEPS:
            print(f"  {name:<18} python -m {module} {' '.join(extra)}")
        return 0
    if args.warmup:
        warm_up()
        return 0
    names = select_steps(args.steps, args.from_step, args.skip)
    print(f"Plan: {names}")
    run_steps(names)
    if not args.no_warmup:
        warm_up()
    return 0


if __name__ == "__main__":
    sys.exit(main())
