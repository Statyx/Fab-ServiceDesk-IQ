#!/usr/bin/env python3
"""Create the Eventhouse, the KQL database and the six real-time tables.

The KQL database is created as its own item (config ``eventhouse.kql_database``) inside
the Eventhouse, rather than relying on the database Fabric auto-creates with the
Eventhouse's name: every script, the ontology and the injector then address one known
name. Tables come from ``schema.EVENTHOUSE`` (``.create-merge``: idempotent) and get
streaming ingestion, which the preload and the injector both use.

Saves ``eventhouse_id``, ``kql_database_id`` and ``kusto_query_uri``.

  python -m fabric.eventhouse.deploy_eventhouse
"""
import os, sys
from fabric._shared.platform_env import bootstrap
bootstrap()

import time

import requests

from fabric._shared.helpers import (create_fabric_item, deploy_context, fabric_headers,
                                    find_item_or_none, get_kusto_token, kusto_mgmt,
                                    print_step, save_state)
from fabric.data.schema import EVENTHOUSE, kql_create_merge


def main() -> int:
    cfg, state, api, ws, token = deploy_context()
    eh_name = cfg["eventhouse"]["name"]
    db_name = cfg["eventhouse"]["kql_database"]
    h = fabric_headers(token)

    print_step(1, 4, f"Find or create Eventhouse '{eh_name}'")
    eh = find_item_or_none(token, api, ws, eh_name, "Eventhouse")
    if not eh:
        eh = create_fabric_item(token, api, ws, eh_name, "Eventhouse",
                                "Zava Service Desk: live DEM telemetry, tickets, conversations, "
                                "agent traces, AI gateway logs, CSAT")
        print(f"   created {eh['id']}")
    else:
        print(f"   reusing {eh['id']}")
    state["eventhouse_id"] = eh["id"]
    save_state(state)

    print_step(2, 4, f"Find or create KQL database '{db_name}'")
    db = find_item_or_none(token, api, ws, db_name, "KQLDatabase")
    if not db:
        db = create_fabric_item(token, api, ws, db_name, "KQLDatabase",
                                creation_payload={"databaseType": "ReadWrite",
                                                  "parentEventhouseItemId": eh["id"]})
        print(f"   created {db['id']}")
    else:
        print(f"   reusing {db['id']}")
    quri = None
    for _ in range(20):
        det = requests.get(f"{api}/workspaces/{ws}/eventhouses/{eh['id']}", headers=h,
                           timeout=60).json()
        quri = (det.get("properties") or {}).get("queryServiceUri")
        if quri:
            break
        time.sleep(10)
    if not quri:
        raise RuntimeError("Eventhouse query URI not available yet; re-run in a minute")
    state["kql_database_id"] = db["id"]
    state["kusto_query_uri"] = quri
    save_state(state)
    print(f"   query URI {quri}")

    print_step(3, 4, f"Create {len(EVENTHOUSE)} tables")
    ktok = get_kusto_token(quri)
    for attempt in range(10):
        try:
            kusto_mgmt(quri, ktok, db_name, ".show tables")
            break
        except RuntimeError as exc:
            print(f"   database not ready ({str(exc)[:80]}), waiting")
            time.sleep(15)
    for table in EVENTHOUSE:
        kusto_mgmt(quri, ktok, db_name, kql_create_merge(table))
        print(f"   {table}")

    print_step(4, 4, "Enable streaming ingestion")
    kusto_mgmt(quri, ktok, db_name, ".alter database ['" + db_name +
               "'] policy streamingingestion enable")
    print("   database-level streaming policy on")
    return 0


if __name__ == "__main__":
    sys.exit(main())
