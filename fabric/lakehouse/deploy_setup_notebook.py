#!/usr/bin/env python3
"""Deploy and run the setup notebook: ``Files/raw/*.csv`` -> Delta tables.

Types come from ``fabric/data/schema.py``, never from inference. Every column is read as
a string and cast explicitly, so a date key stays a timestamp (``2026-06-23`` and
``2026-06-23T08:43:26Z`` both cast cleanly in UTC), counts are 64-bit (Direct Lake
pushes SUM down to the SQL endpoint, where a 32-bit SUM overflows) and booleans are real
booleans the ontology can bind.

  python -m fabric.lakehouse.deploy_setup_notebook
"""
import os, sys
from fabric._shared.platform_env import bootstrap
bootstrap()

import json

from fabric._shared.helpers import deploy_context, print_step, require_state, save_state
from fabric.data.schema import LAKEHOUSE, LAKEHOUSE_EDGES
from fabric.lakehouse.notebook_utils import recreate_notebook, run_notebook

SPARK_TYPES = {"string": "string", "bigint": "bigint", "double": "double",
               "datetime": "timestamp", "boolean": "boolean"}


def build_notebook_py(ws_id: str, lh_id: str, lh_name: str) -> str:
    schemas = {t: [[c, SPARK_TYPES[k]] for c, k in cols] for t, cols in LAKEHOUSE.items()}
    return f'''# Fabric notebook source

# METADATA ********************

# META {{
# META   "kernel_info": {{
# META     "name": "synapse_pyspark"
# META   }},
# META   "dependencies": {{
# META     "lakehouse": {{
# META       "default_lakehouse": "{lh_id}",
# META       "default_lakehouse_name": "{lh_name}",
# META       "default_lakehouse_workspace_id": "{ws_id}"
# META     }}
# META   }}
# META }}

# MARKDOWN ********************

# # Zava Service Desk setup: CSV (Files/raw) -> Delta tables
#
# Schemas are generated from fabric/data/schema.py. Re-run the deploy script to refresh.

# CELL ********************

import json
from pyspark.sql import functions as F

spark.conf.set("spark.sql.session.timeZone", "UTC")
SCHEMAS = json.loads({json.dumps(json.dumps(schemas))})
created = []
for table, cols in SCHEMAS.items():
    raw = spark.read.option("header", True).option("inferSchema", False) \\
        .option("escape", '"').option("multiLine", True).csv(f"Files/raw/{{table}}.csv")
    missing = [c for c, _ in cols if c not in raw.columns]
    if missing:
        raise ValueError(f"{{table}}: CSV lacks columns {{missing}}")
    df = raw.select([F.col(c).cast(t).alias(c) for c, t in cols])
    df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(table)
    n = spark.table(table).count()
    created.append((table, n))
    print(f"{{table}}: {{n}} rows")

# Edge tables for nullable foreign keys: the ontology binds a relationship to a table
# whose target key is never null.
EDGES = json.loads({json.dumps(json.dumps(LAKEHOUSE_EDGES))})
for edge, (src, key, fk) in EDGES.items():
    df = spark.table(src).select(key, fk).where(F.col(fk).isNotNull() & (F.col(fk) != ""))
    df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(edge)
    n = spark.table(edge).count()
    created.append((edge, n))
    print(f"{{edge}}: {{n}} rows")

print("DONE", created)
'''


def main() -> int:
    cfg, state, api, ws, token = deploy_context()
    lh_id = require_state(state, "lakehouse_id")
    lh_name = cfg["lakehouse"]["name"]
    nb_name = cfg["lakehouse"]["setup_notebook"]

    print_step(1, 3, f"Build and (re)create notebook '{nb_name}'")
    nb_id = recreate_notebook(ws, nb_name, build_notebook_py(ws, lh_id, lh_name), token)
    print(f"   notebook {nb_id}")

    print_step(2, 3, "Run notebook (Spark cold start 1-2 min)")
    run_notebook(ws, nb_id, token, max_wait=1500, poll_interval=20)
    print("   completed")

    print_step(3, 3, "Persist state")
    state["setup_notebook_id"] = nb_id
    save_state(state)
    print(f"   {len(LAKEHOUSE)} Delta tables + {len(LAKEHOUSE_EDGES)} edge tables written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
