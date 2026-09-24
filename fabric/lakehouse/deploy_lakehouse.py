#!/usr/bin/env python3
"""Create the Lakehouse and upload every Lakehouse CSV to OneLake ``Files/raw/``.

Delta tables are built afterwards by ``deploy_setup_notebook`` (explicit schemas from
``fabric/data/schema.py``). Idempotent; saves ``lakehouse_id`` and the SQL endpoint.

OneLake upload uses one reusable ``http.client.HTTPSConnection`` in three DFS steps
(PUT create -> PATCH append -> PATCH flush): requests/urllib3 hang on OneLake DFS.

  python -m fabric.lakehouse.deploy_lakehouse
"""
import os, sys
from fabric._shared.platform_env import bootstrap
bootstrap()

import http.client
import time

import requests

from fabric._shared.helpers import (create_fabric_item, deploy_context, fabric_headers,
                                    find_item_or_none, get_storage_token, print_step,
                                    save_state)
from fabric._shared.paths import LAKEHOUSE_DATA
from fabric.data.schema import LAKEHOUSE

ONELAKE_HOST = "onelake.dfs.fabric.microsoft.com"
# Append in chunks: a single PATCH of the 4 MB experience table is fine, but chunking
# keeps every request well under the DFS limits whatever the dataset size.
CHUNK = 4 * 1024 * 1024


def _check(resp: http.client.HTTPResponse, what: str) -> None:
    body = resp.read()
    if resp.status >= 300:
        raise RuntimeError(f"{what} failed ({resp.status}): {body[:300]!r}")


def upload_files(ws_id: str, lh_id: str, token: str) -> None:
    hdr = {"Authorization": "Bearer " + token}
    conn = http.client.HTTPSConnection(ONELAKE_HOST, timeout=300)
    try:
        for name in LAKEHOUSE:
            path = LAKEHOUSE_DATA / f"{name}.csv"
            if not path.exists():
                raise FileNotFoundError(f"{path} missing: run `python -m fabric.data.generate_data`")
            data = path.read_bytes()
            base = f"/{ws_id}/{lh_id}/Files/raw/{name}.csv"
            conn.request("PUT", base + "?resource=file&overwrite=true", headers=hdr)
            _check(conn.getresponse(), f"create {name}")
            pos = 0
            h2 = dict(hdr, **{"Content-Type": "application/octet-stream"})
            while pos < len(data):
                chunk = data[pos:pos + CHUNK]
                conn.request("PATCH", base + f"?action=append&position={pos}", body=chunk,
                             headers=h2)
                _check(conn.getresponse(), f"append {name}")
                pos += len(chunk)
            conn.request("PATCH", base + f"?action=flush&position={len(data)}", headers=hdr)
            _check(conn.getresponse(), f"flush {name}")
            print(f"   raw/{name}.csv  {len(data):>10,} bytes")
    finally:
        conn.close()


def main() -> int:
    cfg, state, api, ws, token = deploy_context()
    name = cfg["lakehouse"]["name"]
    h = fabric_headers(token)

    print_step(1, 3, f"Find or create Lakehouse '{name}'")
    lh = find_item_or_none(token, api, ws, name, "Lakehouse")
    if lh:
        print(f"   reusing {lh['id']}")
    else:
        lh = create_fabric_item(token, api, ws, name, "Lakehouse",
                                "Zava Service Desk: reference data, 90-day history, XLA contracts")
        print(f"   created {lh['id']}")
    lh_id = lh["id"]

    print_step(2, 3, f"Upload {len(LAKEHOUSE)} CSVs to Files/raw/")
    upload_files(ws, lh_id, get_storage_token())

    print_step(3, 3, "Persist state (+ SQL endpoint)")
    sql = None
    for _ in range(12):
        det = requests.get(f"{api}/workspaces/{ws}/lakehouses/{lh_id}", headers=h,
                           timeout=60).json()
        sql = (det.get("properties", {}).get("sqlEndpointProperties") or {})
        if sql.get("connectionString"):
            break
        time.sleep(10)
    state["lakehouse_id"] = lh_id
    if sql and sql.get("connectionString"):
        state["lakehouse_sql_endpoint"] = sql["connectionString"]
        state["lakehouse_sql_endpoint_id"] = sql.get("id", "")
    save_state(state)
    print("   lakehouse_id saved")
    return 0


if __name__ == "__main__":
    sys.exit(main())
