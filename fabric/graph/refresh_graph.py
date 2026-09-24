#!/usr/bin/env python3
"""Re-ingest the Graph Model from the Lakehouse (no definition rebuild).

Run after the Lakehouse tables change (new dataset + deploy_lakehouse +
deploy_setup_notebook). Not needed after an Eventhouse load or an injection: live signals
are read through the ontology's TimeSeries bindings and KQL, never ingested into the graph.

  python -m fabric.graph.refresh_graph
"""
import os, sys
from fabric._shared.platform_env import bootstrap
bootstrap()

from fabric._shared.helpers import deploy_context
from fabric.graph.deploy_graph import find_graph_model, refresh_graph


def main() -> int:
    cfg, state, api, ws, token = deploy_context()
    gid = state.get("graph_model_id") or find_graph_model(token, api, ws,
                                                          cfg["ontology"]["name"])[0]
    print("RefreshGraph (re-ingest the Lakehouse tables)...")
    status = refresh_graph(token, api, ws, gid)
    print(f"Final status: {status}")
    return 0 if status in ("Completed", "Started") else 1


if __name__ == "__main__":
    sys.exit(main())
