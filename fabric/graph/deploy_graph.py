#!/usr/bin/env python3
"""Populate the ontology's Graph Model definition, then refresh it.

Deploying the ontology through REST does NOT generate the child Graph Model. This builds
the graph definition (graphType + dataSources + graphDefinition) from the SAME entities and
relationships as ``deploy_ontology``, pushes it with updateDefinition, then runs
RefreshGraph to ingest.

Data source paths are the REAL OneLake locations from ``GET /lakehouses/{id}/tables``: a
constructed path is accepted by the API and then silently yields an empty graph.

  python -m fabric.graph.deploy_graph
"""
import os, sys
from fabric._shared.platform_env import bootstrap
bootstrap()

import hashlib
import time
import uuid
from typing import Dict, Tuple

import requests

from fabric._shared.helpers import (deploy_context, fabric_headers, get_fabric_token,
                                    list_items, part,
                                    print_step, require_state, save_state, update_definition)
from fabric.ontology.deploy_ontology import ENTITIES, RELATIONSHIPS

GT = {"string": "STRING", "bigint": "INT", "double": "FLOAT",
      "datetime": "ZONED DATETIME", "boolean": "BOOLEAN"}
SCHEMA_BASE = "https://developer.microsoft.com/json-schemas/fabric/item/graphInstance/definition"


def alias(seed: str) -> str:
    return str(int(hashlib.md5(seed.encode()).hexdigest()[:15], 16))


def guid(seed: str) -> str:
    return str(uuid.UUID(bytes=hashlib.md5(seed.encode()).digest()))


def find_graph_model(token: str, api: str, ws: str, ontology_name: str,
                     retries: int = 12) -> Tuple[str, str]:
    """The Graph Model child of the ontology (``<ontology>_graph...``); it can lag creation."""
    for attempt in range(retries):
        for it in list_items(token, api, ws):
            if it.get("type") == "GraphModel" and \
                    f"{ontology_name}_graph" in (it.get("displayName") or ""):
                return it["id"], it["displayName"]
        time.sleep(10)
    raise RuntimeError("Graph Model item not found (run deploy_ontology first)")


def table_locations(token: str, api: str, ws: str, lh: str) -> Dict[str, str]:
    r = requests.get(f"{api}/workspaces/{ws}/lakehouses/{lh}/tables",
                     headers=fabric_headers(token), timeout=60)
    r.raise_for_status()
    body = r.json()
    return {row["name"]: row["location"] for row in (body.get("data") or body.get("value") or [])}


def build_definition(lh: str, locations: Dict[str, str]):
    # Types are known for entity tables; edge/bridge key columns are all strings.
    tbl_cols = {table: dict(cols) for _, table, _, cols in ENTITIES}
    node_alias, node_types, node_tables, data_sources = {}, [], [], {}

    def add_ds(table: str) -> str:
        name = f"{lh}_{table}"
        if name not in data_sources:
            path = locations.get(table)
            if not path:
                raise RuntimeError(f"Table '{table}' is not in the Lakehouse: run "
                                   "python -m fabric.lakehouse.deploy_setup_notebook first")
            data_sources[name] = {"name": name, "type": "DeltaTable", "properties": {"path": path}}
        return name

    for name, table, keys, cols in ENTITIES:
        a = alias(f"node-{name}")
        node_alias[name] = a
        node_types.append({"primaryKeyProperties": list(keys), "alias": a, "labels": [name],
                           "properties": [{"name": c, "type": GT[t]} for c, t in cols]})
        node_tables.append({"nodeTypeAlias": a, "id": guid(f"nodetable-{name}"),
                            "dataSourceName": add_ds(table),
                            "propertyMappings": [{"propertyName": c, "sourceColumn": c}
                                                 for c, _t in cols]})

    edge_types, edge_tables = [], []
    for rname, src, tgt, fk_table, src_keys, tgt_fks in RELATIONSHIPS:
        a = alias(f"edge-{rname}")
        props = [{"name": c, "type": GT[tbl_cols.get(fk_table, {}).get(c, "string")]}
                 for c in dict.fromkeys(list(src_keys) + list(tgt_fks))]
        edge_types.append({"sourceNodeType": {"alias": node_alias[src]}, "alias": a,
                           "destinationNodeType": {"alias": node_alias[tgt]},
                           "labels": [rname], "properties": props})
        edge_tables.append({"edgeTypeAlias": a, "id": guid(f"edgetable-{rname}"),
                            "edgeIdMapping": None, "dataSourceName": add_ds(fk_table),
                            "sourceNodeKeyColumns": list(src_keys),
                            "propertyMappings": [{"propertyName": p["name"],
                                                  "sourceColumn": p["name"]} for p in props],
                            "destinationNodeKeyColumns": list(tgt_fks)})

    gt = {"$schema": f"{SCHEMA_BASE}/graphType/1.0.0/schema.json",
          "nodeTypes": node_types, "edgeTypes": edge_types}
    ds = {"$schema": f"{SCHEMA_BASE}/dataSources/1.0.0/schema.json",
          "dataSources": list(data_sources.values())}
    gd = {"$schema": f"{SCHEMA_BASE}/graphDefinition/1.0.0/schema.json",
          "nodeTables": node_tables, "edgeTables": edge_tables}
    st = {"$schema": f"{SCHEMA_BASE}/stylingConfiguration/1.0.0/schema.json",
          "modelLayout": {"positions": {}, "styles": {}, "pan": {"x": 0.0, "y": 0.0},
                          "zoomLevel": 1.0},
          "visualFormat": None, "scenario": "Ontology"}
    return gt, ds, gd, st


def _wait_active_refresh(headers: Dict, api: str, ws: str, graph_id: str,
                         max_polls: int) -> str:
    """Poll the in-flight RefreshGraph job that absorbed a deduped request."""
    url = f"{api}/workspaces/{ws}/items/{graph_id}/jobs/instances"
    for _ in range(max_polls):
        jobs = requests.get(url, headers=headers, timeout=60).json().get("value", [])
        active = [j for j in jobs if j.get("status") in ("NotStarted", "InProgress")]
        if not active:
            real = [j for j in jobs if j.get("status") != "Deduped"]
            latest = max(real, key=lambda j: j.get("startTimeUtc") or "", default={})
            return latest.get("status", "Completed")
        print(f"   waiting for in-flight refresh: {active[0].get('status')}")
        time.sleep(10)
    return "Timeout"


def refresh_graph(token: str, api: str, ws: str, graph_id: str, max_polls: int = 120) -> str:
    """Run RefreshGraph and poll it to a final status.

    An ontology update triggers its own refresh; a second request is then "Deduped"
    and we wait for the in-flight job instead.
    """
    headers = fabric_headers(token)
    jr = requests.post(f"{api}/workspaces/{ws}/items/{graph_id}/jobs/instances"
                       "?jobType=RefreshGraph", headers=headers, json={}, timeout=60)
    if jr.status_code not in (200, 201, 202):
        raise RuntimeError(f"RefreshGraph failed to start ({jr.status_code}): {jr.text[:400]}")
    loc = jr.headers.get("Location")
    if jr.status_code != 202 or not loc:
        return "Started"
    for _ in range(max_polls):
        time.sleep(10)
        try:
            resp = requests.get(loc, headers=headers, timeout=60)
        except requests.RequestException as e:
            print(f"   poll error, retrying: {type(e).__name__}")
            continue
        if resp.status_code == 401:
            headers = fabric_headers(get_fabric_token())
            continue
        status = resp.json().get("status") if resp.ok else None
        if status is None:
            print(f"   poll HTTP {resp.status_code}, retrying")
            continue
        print(f"   refresh: {status}")
        if status == "Deduped":
            return _wait_active_refresh(headers, api, ws, graph_id, max_polls)
        if status in ("Completed", "Failed", "Cancelled"):
            if status == "Failed":
                print("   failure:", resp.json().get("failureReason"))
            return status
    return "Timeout"


def main() -> int:
    cfg, state, api, ws, token = deploy_context()
    lh = require_state(state, "lakehouse_id")
    ont_name = cfg["ontology"]["name"]

    print_step(1, 4, "Locate the Graph Model item")
    gid, gname = find_graph_model(token, api, ws, ont_name)
    print(f"   {gname}")

    print_step(2, 4, "Build the graph definition from the real OneLake table locations")
    gt, ds, gd, st = build_definition(lh, table_locations(token, api, ws, lh))
    print(f"   {len(gt['nodeTypes'])} node types, {len(gt['edgeTypes'])} edge types, "
          f"{len(ds['dataSources'])} data sources")
    platform = {"$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/"
                           "platformProperties/2.0.0/schema.json",
                "metadata": {"type": "GraphModel", "displayName": gname},
                "config": {"version": "2.0", "logicalId": "00000000-0000-0000-0000-000000000000"}}
    parts = [part("graphType.json", gt), part("dataSources.json", ds),
             part("graphDefinition.json", gd), part("stylingConfiguration.json", st),
             part(".platform", platform)]

    print_step(3, 4, "Push the definition, then RefreshGraph")
    update_definition(token, api, ws, gid, {"parts": parts}, f"GraphModel '{gname}'")
    status = refresh_graph(token, api, ws, gid)
    state["graph_model_id"] = gid
    save_state(state)
    if status not in ("Completed", "Started"):
        raise RuntimeError(f"RefreshGraph ended {status}")

    print_step(4, 4, "Done")
    print("   graph_model_id saved")
    return 0


if __name__ == "__main__":
    sys.exit(main())
