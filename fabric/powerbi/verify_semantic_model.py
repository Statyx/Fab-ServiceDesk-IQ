#!/usr/bin/env python3
"""Check the deployed semantic model against the dataset: DAX == reference, or fail.

Expected values are recomputed from ``artifacts/data`` (the CSVs that were loaded), so
the check follows the dataset whatever the shift: last closed week zero-touch per
customer, and total XLA credit per customer.

  python -m fabric.powerbi.verify_semantic_model
"""
import os, sys
from fabric._shared.platform_env import bootstrap
bootstrap()

import csv
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List

import requests

from fabric._shared.helpers import deploy_context, get_token, require_state
from fabric._shared.paths import ARTIFACTS

PBI_API = "https://api.powerbi.com/v1.0/myorg"
PBI_RESOURCE = "https://analysis.windows.net/powerbi/api"


def expected(data_dir: Path) -> Dict[str, Dict[str, float]]:
    lh = data_dir / "lakehouse"
    dates = [r["date"][:10] for r in csv.DictReader(open(lh / "dim_date.csv", encoding="utf-8"))]
    last = date.fromisoformat(max(dates))
    week = last - timedelta(days=last.weekday())
    if last.weekday() != 6:
        week -= timedelta(days=7)
    zt: Dict[str, List[int]] = {}
    for t in csv.DictReader(open(lh / "fact_ticket.csv", encoding="utf-8")):
        if week <= date.fromisoformat(t["created_date"][:10]) <= week + timedelta(days=6):
            cell = zt.setdefault(t["customer_id"], [0, 0])
            cell[0] += 1
            cell[1] += t["zero_touch"].lower() == "true"
    credit: Dict[str, float] = {}
    for e in csv.DictReader(open(lh / "fact_xla_evaluation.csv", encoding="utf-8")):
        credit[e["customer_id"]] = credit.get(e["customer_id"], 0.0) + float(e["penalty_eur"])
    return {"week": {"start": week.isoformat()},
            "zero_touch": {c: round(100 * z / n, 1) for c, (n, z) in zt.items()},
            "credit": {c: round(v, 2) for c, v in credit.items()}}


def run_dax(ws: str, sm_id: str, query: str) -> List[Dict]:
    token = get_token(PBI_RESOURCE)
    r = requests.post(f"{PBI_API}/groups/{ws}/datasets/{sm_id}/executeQueries",
                      headers={"Authorization": "Bearer " + token},
                      json={"queries": [{"query": query}],
                            "serializerSettings": {"includeNulls": True}}, timeout=180)
    if r.status_code != 200:
        raise RuntimeError(f"executeQueries {r.status_code}: {r.text[:800]}")
    return r.json()["results"][0]["tables"][0]["rows"]


def main() -> int:
    cfg, state, api, ws, _token = deploy_context()
    sm_id = require_state(state, "semantic_model_id")
    exp = expected(ARTIFACTS / "data")
    rows = run_dax(ws, sm_id, (
        'EVALUATE SUMMARIZECOLUMNS ( dim_customer[customer_id], '
        '"week", [Last Closed Week Start], '
        '"zt", [Zero-Touch % (Last Closed Week)], "credit", [XLA Credit (EUR)] )'))
    failures = 0
    print(f"Last closed week (expected): {exp['week']['start']}")
    # The blank member row carries only the constant week measure: skip it.
    rows = [r for r in rows if r["dim_customer[customer_id]"]]
    if len(rows) != len(exp["zero_touch"]):
        print(f"BAD: {len(rows)} customers in the model, {len(exp['zero_touch'])} in the data")
        failures = 1
    for r in sorted(rows, key=lambda x: x["dim_customer[customer_id]"]):
        cid = r["dim_customer[customer_id]"]
        zt = round(100 * (r["[zt]"] or 0), 1)
        credit = round(r["[credit]"] or 0, 2)
        ok = (zt == exp["zero_touch"].get(cid, 0.0)
              and credit == exp["credit"].get(cid, 0.0)
              and str(r["[week]"])[:10] == exp["week"]["start"])
        failures += not ok
        print(f"  {'OK ' if ok else 'BAD'} {cid}: zero-touch {zt}% "
              f"(expected {exp['zero_touch'].get(cid)}), credit {credit:,.2f} EUR "
              f"(expected {exp['credit'].get(cid, 0.0):,.2f}), week {str(r['[week]'])[:10]}")
    if failures:
        print(f"{failures} mismatch(es)")
        return 1
    print("Semantic model matches the dataset.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
